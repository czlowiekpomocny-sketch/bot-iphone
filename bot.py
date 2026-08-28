import os
import re
import asyncio
import logging
from urllib.parse import urljoin, quote

from flask import Flask
from threading import Thread
import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# KONFIGURACJA
# ============================================================

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

SCAN_INTERVAL = 15

# Szukamy iPhone 11–17
TARGET_MODELS = [
    "iphone 11",
    "iphone 12",
    "iphone 13",
    "iphone 14",
    "iphone 15",
    "iphone 16",
    "iphone 17",
]

# Dodatkowe słowa zwiększające szansę na okazję
FLIP_KEYWORDS = [
    "uszkodz",
    "zbity",
    "zbita",
    "pęknię",
    "peknię",
    "do naprawy",
    "naprawy",
    "na części",
    "na czesci",
    "bateria",
    "wyświetlacz",
    "wyswietlacz",
    "ekran",
    "face id",
    "nie działa",
    "nie dziala",
    "uszkodzona",
    "uszkodzony",
    "tył",
    "tyl",
    "klapa",
    "aparaty",
    "dotyk",
    "okazja",
    "tanio",
]

HEADLESS = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("iphone-bot")


# ============================================================
# PROSTY SERWER DLA RENDERA
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "📱 iPhone Flip Bot działa!"


def run_web_server():
    port = int(os.getenv("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


Thread(target=run_web_server, daemon=True).start()


# ============================================================
# DISCORD
# ============================================================

def send_discord_embed(
    title,
    price,
    url,
    source,
    image_url=None,
    reason="iPhone 11–17",
):
    if not DISCORD_WEBHOOK_URL:
        log.error("❌ Brak DISCORD_WEBHOOK_URL w Render → Environment")
        return

    embed = {
        "title": f"📱 NOWY iPhone — {source}",
        "description": f"**{title[:250]}**",
        "url": url,
        "fields": [
            {
                "name": "💰 Cena",
                "value": f"**{price}**",
                "inline": True,
            },
            {
                "name": "🔎 Wykryto",
                "value": reason[:1000],
                "inline": True,
            },
            {
                "name": "🌐 Portal",
                "value": source,
                "inline": True,
            },
        ],
        "footer": {
            "text": "iPhone Flip Bot • nowe ogłoszenie"
        },
    }

    if image_url:
        embed["thumbnail"] = {"url": image_url}

    payload = {
        "embeds": [embed],
        "username": "iPhone Flip Bot",
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=15,
        )

        if response.status_code in (200, 204):
            log.info("📨 Discord: wysłano → %s", title[:80])
        else:
            log.error(
                "❌ Discord HTTP %s: %s",
                response.status_code,
                response.text[:300],
            )

    except Exception as e:
        log.error("❌ Błąd Discord: %s", e)


# ============================================================
# FILTR
# ============================================================

def normalize(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def detect_model(title):
    text = normalize(title)

    for model in TARGET_MODELS:
        if model in text:
            return model

    return None


def get_reason(title):
    text = normalize(title)

    matched = [
        word
        for word in FLIP_KEYWORDS
        if word in text
    ]

    if matched:
        return "Słowa: " + ", ".join(matched[:6])

    return "iPhone 11–17"


def is_target(title):
    model = detect_model(title)

    if not model:
        return False

    return True


# ============================================================
# CENA
# ============================================================

def clean_price(text):
    if not text:
        return "Cena niepodana"

    text = text.replace("\xa0", " ")

    # np. 1 299 zł / 1299 PLN / 899,99 zł
    match = re.search(
        r"(\d[\d\s.,]*)\s*(zł|pln)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(0).strip()

    # czasem sam numer
    match = re.search(
        r"\b\d{2,5}(?:[,.]\d{1,2})?\b",
        text,
    )

    if match:
        return match.group(0) + " zł"

    return "Cena niepodana"


# ============================================================
# ID OFERTY
# ============================================================

def make_id(url, source):
    url = url.split("?")[0].rstrip("/")

    return f"{source}:{url}"


# ============================================================
# OLX
# ============================================================

async def scan_olx(page):
    results = []

    url = (
        "https://www.olx.pl/elektronika/"
        "telefony/smartfony/"
        "?q=iphone&search%5Border%5D=created_at%3Adesc"
    )

    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await page.wait_for_timeout(2500)

        # Akceptacja cookies, jeśli występuje
        try:
            buttons = page.locator("button")
            count = await buttons.count()

            for i in range(min(count, 20)):
                try:
                    text = normalize(await buttons.nth(i).inner_text())

                    if any(
                        x in text
                        for x in [
                            "akceptuję",
                            "akceptuj",
                            "zgadzam się",
                            "accept",
                        ]
                    ):
                        await buttons.nth(i).click(timeout=1000)
                        break
                except Exception:
                    pass
        except Exception:
            pass

        await page.wait_for_timeout(1000)

        cards = page.locator(
            '[data-cy="l-card"], '
            'article[data-cy="l-card"], '
            'div[data-cy="l-card"]'
        )

        count = await cards.count()

        log.info("OLX: znaleziono %s kart", count)

        for i in range(min(count, 30)):
            try:
                card = cards.nth(i)

                title = ""

                # różne wersje OLX
                for selector in [
                    "h6",
                    "h4",
                    '[data-cy="ad-card-title"]',
                    "a",
                ]:
                    try:
                        loc = card.locator(selector).first
                        if await loc.count():
                            txt = await loc.inner_text()
                            if txt.strip():
                                title = txt.strip()
                                break
                    except Exception:
                        pass

                if not title:
                    continue

                if not is_target(title):
                    continue

                link = card.locator("a").first

                if not await link.count():
                    continue

                href = await link.get_attribute("href")

                if not href:
                    continue

                item_url = urljoin(
                    "https://www.olx.pl",
                    href,
                )

                # cena
                price = "Cena niepodana"

                try:
                    price_loc = card.locator(
                        '[data-testid="ad-price"]'
                    ).first

                    if await price_loc.count():
                        price = clean_price(
                            await price_loc.inner_text()
                        )
                except Exception:
                    pass

                # obrazek
                image_url = None

                try:
                    img = card.locator("img").first

                    if await img.count():
                        image_url = await img.get_attribute("src")

                        if not image_url:
                            image_url = await img.get_attribute(
                                "data-src"
                            )
                except Exception:
                    pass

                results.append(
                    {
                        "id": make_id(item_url, "olx"),
                        "title": title,
                        "price": price,
                        "url": item_url,
                        "source": "OLX",
                        "image": image_url,
                        "reason": get_reason(title),
                    }
                )

            except Exception:
                continue

    except PlaywrightTimeoutError:
        log.warning("⚠️ OLX: timeout")
    except Exception as e:
        log.error("❌ OLX: %s", e)

    return results


# ============================================================
# VINTED
# ============================================================

async def scan_vinted(page):
    results = []

    url = (
        "https://www.vinted.pl/catalog?"
        "search_text=iphone&order=newest_first"
    )

    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await page.wait_for_timeout(3000)

        # cookies
        try:
            buttons = page.locator("button")
            count = await buttons.count()

            for i in range(min(count, 30)):
                try:
                    text = normalize(
                        await buttons.nth(i).inner_text()
                    )

                    if any(
                        x in text
                        for x in [
                            "akceptuj",
                            "zgadzam",
                            "accept",
                            "allow",
                        ]
                    ):
                        await buttons.nth(i).click(timeout=1000)
                        break
                except Exception:
                    pass
        except Exception:
            pass

        await page.wait_for_timeout(1000)

        # Vinted używa linków /items/...
        links = page.locator(
            'a[href*="/items/"]'
        )

        count = await links.count()

        log.info("Vinted: znaleziono %s linków", count)

        seen_urls = set()

        for i in range(min(count, 40)):
            try:
                link = links.nth(i)

                href = await link.get_attribute("href")

                if not href:
                    continue

                item_url = urljoin(
                    "https://www.vinted.pl",
                    href,
                )

                if item_url in seen_urls:
                    continue

                seen_urls.add(item_url)

                # tekst całej karty
                card = link

                for _ in range(4):
                    try:
                        parent = card.locator("..")
                        if await parent.count():
                            card = parent
                    except Exception:
                        break

                text = await card.inner_text()

                if not text:
                    text = await link.inner_text()

                lines = [
                    x.strip()
                    for x in text.splitlines()
                    if x.strip()
                ]

                title = ""

                for line in lines:
                    if detect_model(line):
                        title = line
                        break

                if not title:
                    # czasem tytuł jest w aria-label
                    try:
                        aria = await link.get_attribute(
                            "aria-label"
                        )

                        if aria and detect_model(aria):
                            title = aria
                    except Exception:
                        pass

                if not title:
                    continue

                if not is_target(title):
                    continue

                price = clean_price(text)

                image_url = None

                try:
                    img = link.locator("img").first

                    if await img.count():
                        image_url = await img.get_attribute("src")

                        if not image_url:
                            image_url = await img.get_attribute(
                                "data-src"
                            )
                except Exception:
                    pass

                results.append(
                    {
                        "id": make_id(item_url, "vinted"),
                        "title": title,
                        "price": price,
                        "url": item_url,
                        "source": "Vinted",
                        "image": image_url,
                        "reason": get_reason(title),
                    }
                )

            except Exception:
                continue

    except PlaywrightTimeoutError:
        log.warning("⚠️ Vinted: timeout")
    except Exception as e:
        log.error("❌ Vinted: %s", e)

    return results


# ============================================================
# JEDEN SKAN — OLX + VINTED RÓWNOCZEŚNIE
# ============================================================

async def scan_both(browser):
    context_olx = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        viewport={
            "width": 1366,
            "height": 900,
        },
        locale="pl-PL",
    )

    context_vinted = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        viewport={
            "width": 1366,
            "height": 900,
        },
        locale="pl-PL",
    )

    page_olx = await context_olx.new_page()
    page_vinted = await context_vinted.new_page()

    try:
        # KLUCZOWE:
        # oba portale startują w tym samym czasie
        olx_task = asyncio.create_task(
            scan_olx(page_olx)
        )

        vinted_task = asyncio.create_task(
            scan_vinted(page_vinted)
        )

        olx_results, vinted_results = await asyncio.gather(
            olx_task,
            vinted_task,
            return_exceptions=True,
        )

        if isinstance(olx_results, Exception):
            log.error(
                "❌ OLX task: %s",
                olx_results,
            )
            olx_results = []

        if isinstance(vinted_results, Exception):
            log.error(
                "❌ Vinted task: %s",
                vinted_results,
            )
            vinted_results = []

        return olx_results + vinted_results

    finally:
        await context_olx.close()
        await context_vinted.close()


# ============================================================
# GŁÓWNA PĘTLA
# ============================================================

async def run_bot():
    if not DISCORD_WEBHOOK_URL:
        log.error(
            "❌ Brak DISCORD_WEBHOOK_URL!"
        )
        log.error(
            "Render → Environment → "
            "DISCORD_WEBHOOK_URL"
        )
        return

    log.info("======================================")
    log.info("📱 IPHONE FLIP BOT")
    log.info("OLX + VINTED")
    log.info("Równoczesny skan co %s sekund", SCAN_INTERVAL)
    log.info("======================================")

    seen_ids = set()
    first_scan = True

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--single-process",
            ],
        )

        try:
            while True:
                cycle_start = asyncio.get_running_loop().time()

                log.info("")
                log.info("🔎 NOWY SKAN — OLX + VINTED RAZEM")

                try:
                    offers = await scan_both(browser)

                    # usuwamy duplikaty
                    unique = {}

                    for offer in offers:
                        unique[offer["id"]] = offer

                    offers = list(unique.values())

                    log.info(
                        "📦 Łącznie znaleziono pasujących ofert: %s",
                        len(offers),
                    )

                    new_offers = []

                    for offer in offers:
                        if offer["id"] not in seen_ids:
                            new_offers.append(offer)

                    if first_scan:
                        # Pierwszy skan tylko zapamiętuje istniejące
                        # ogłoszenia — nie spamuje Discorda.
                        for offer in offers:
                            seen_ids.add(offer["id"])

                        log.info(
                            "🟢 Pierwszy skan: zapisano %s ofert.",
                            len(offers),
                        )

                        log.info(
                            "📭 Nie wysyłam istniejących ofert."
                        )

                        first_scan = False

                    else:
                        for offer in new_offers:
                            seen_ids.add(offer["id"])

                            log.info(
                                "🆕 NOWA OFERTA: %s | %s",
                                offer["source"],
                                offer["title"][:100],
                            )

                            # Discord jest synchronicznym requestem,
                            # więc wykonujemy go poza głównym event loopem.
                            await asyncio.to_thread(
                                send_discord_embed,
                                offer["title"],
                                offer["price"],
                                offer["url"],
                                offer["source"],
                                offer["image"],
                                offer["reason"],
                            )

                    log.info(
                        "✅ Skan zakończony | nowych: %s",
                        len(new_offers)
                        if not first_scan
                        else 0,
                    )

                except Exception as e:
                    log.exception(
                        "❌ Błąd skanowania: %s",
                        e,
                    )

                # Dokładnie 15 sekund między STARTAMI kolejnych skanów.
                elapsed = (
                    asyncio.get_running_loop().time()
                    - cycle_start
                )

                sleep_time = max(
                    0,
                    SCAN_INTERVAL - elapsed,
                )

                log.info(
                    "⏱️ Następny skan za %.1f s",
                    sleep_time,
                )

                await asyncio.sleep(sleep_time)

        finally:
            await browser.close()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        log.info("🛑 Bot zatrzymany.")
    except Exception as e:
        log.exception(
            "💥 Krytyczny błąd: %s",
            e,
        )
