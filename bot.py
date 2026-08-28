import os
import asyncio
import logging
import threading
import time
from urllib.parse import quote

import requests
from flask import Flask
from playwright.async_api import async_playwright


# ============================================================
# KONFIGURACJA
# ============================================================

SCAN_INTERVAL = 15

SEARCHES = [
    "iphone 11",
    "iphone 12",
    "iphone 13",
    "iphone 14",
    "iphone 15",
]

MAX_RESULTS_PER_SEARCH = 15

PLAYWRIGHT_TIMEOUT = 8000


# ============================================================
# LOGOWANIE
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "iPhone Flip Bot działa."


def start_web_server():
    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


# ============================================================
# DISCORD
# ============================================================

def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK")

    if webhook:
        webhook = webhook.strip()

    return webhook


def send_discord(title, price, url, image=None, source=""):
    webhook = get_webhook()

    if not webhook:
        log.error("❌ Brak DISCORD_WEBHOOK.")
        return False

    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
        "url": url,
        "color": 5814783 if source == "OLX" else 65490,
        "description": (
            f"💰 **Cena:** {price or 'Brak informacji'}\n"
            f"🌐 **Źródło:** {source}"
        ),
        "footer": {
            "text": "iPhone Flip Bot"
        }
    }

    if image and image.startswith("http"):
        embed["thumbnail"] = {
            "url": image
        }

    payload = {
        "embeds": [embed]
    }

    try:
        response = requests.post(
            webhook,
            json=payload,
            timeout=10
        )

        if 200 <= response.status_code < 300:
            log.info(
                f"✅ Discord [{source}]: wysłano -> "
                f"{(title or 'Ogłoszenie')[:50]}"
            )
            return True

        log.error(
            f"❌ Discord HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    except Exception as e:
        log.error(f"❌ Discord error: {e}")

    return False


# ============================================================
# WIADOMOŚĆ TESTOWA
# ============================================================

def send_test_message():
    webhook = get_webhook()

    if not webhook:
        log.error(
            "❌ DISCORD_WEBHOOK nie jest dostępny. "
            "Sprawdź Render Environment Variables."
        )
        return False

    payload = {
        "embeds": [
            {
                "title": "🟢 iPhone Flip Bot — TEST",
                "description": (
                    "Bot uruchomił się poprawnie.\n\n"
                    "OLX + Vinted będą skanowane wspólnie."
                ),
                "color": 3066993,
                "footer": {
                    "text": "iPhone Flip Bot"
                }
            }
        ]
    }

    try:
        response = requests.post(
            webhook,
            json=payload,
            timeout=10
        )

        if 200 <= response.status_code < 300:
            log.info("✅ Discord: wiadomość testowa wysłana")
            return True

        log.error(
            f"❌ Discord test HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    except Exception as e:
        log.error(f"❌ Discord test error: {e}")

    return False


# ============================================================
# OLX
# ============================================================

async def scan_olx(page):
    found = []

    for search in SEARCHES:
        try:
            url = (
                "https://www.olx.pl/d/elektronika/telefony/"
                "telefony-komorkowe/"
                f"q-{quote(search)}/"
                "?search%5Border%5D=created_at:desc"
            )

            log.info(f"OLX: sprawdzam {search}")

            await page.goto(
                url,
                wait_until="commit",
                timeout=PLAYWRIGHT_TIMEOUT
            )

            await page.wait_for_timeout(800)

            cards = await page.locator(
                '[data-cy="l-card"]'
            ).all()

            count = 0

            for card in cards:
                try:
                    link_elem = card.locator("a").first

                    href = await link_elem.get_attribute("href")

                    if not href or "/d/oferta/" not in href:
                        continue

                    if href.startswith("/"):
                        full_url = "https://www.olx.pl" + href
                    else:
                        full_url = href.split("?")[0]

                    title_elem = card.locator("h6, h4").first

                    if await title_elem.count() > 0:
                        title = await title_elem.inner_text()
                    else:
                        title = "Ogłoszenie OLX"

                    price_elem = card.locator(
                        '[data-testid="ad-price"]'
                    )

                    if await price_elem.count() > 0:
                        price = await price_elem.inner_text()
                    else:
                        price = "Brak ceny"

                    img_elem = card.locator("img").first

                    if await img_elem.count() > 0:
                        image = await img_elem.get_attribute("src")
                    else:
                        image = ""

                    found.append(
                        {
                            "source": "OLX",
                            "url": full_url,
                            "title": title.strip(),
                            "price": price.strip(),
                            "image": image or ""
                        }
                    )

                    count += 1

                    if count >= MAX_RESULTS_PER_SEARCH:
                        break

                except Exception:
                    continue

            log.info(
                f"OLX {search}: znaleziono {count} ofert"
            )

        except Exception as e:
            log.warning(
                f"⚠️ OLX {search}: {type(e).__name__}: {e}"
            )

    log.info(
        f"OLX: znaleziono łącznie {len(found)} ofert"
    )

    return found


# ============================================================
# VINTED
# ============================================================

async def scan_vinted(page):
    found = []

    for search in SEARCHES:
        try:
            url = (
                "https://www.vinted.pl/catalog"
                f"?search_text={quote(search)}"
                "&order=newest_first"
            )

            log.info(f"Vinted: sprawdzam {search}")

            await page.goto(
                url,
                wait_until="commit",
                timeout=PLAYWRIGHT_TIMEOUT
            )

            await page.wait_for_timeout(1000)

            items = await page.locator(
                '[data-testid="grid-item"]'
            ).all()

            count = 0

            for item in items:
                try:
                    link_elem = item.locator("a").first

                    href = await link_elem.get_attribute("href")

                    if not href or "/items/" not in href:
                        continue

                    if href.startswith("/"):
                        full_url = (
                            "https://www.vinted.pl" + href
                        )
                    else:
                        full_url = href.split("?")[0]

                    title = await link_elem.get_attribute(
                        "title"
                    )

                    if not title:
                        try:
                            text = await item.inner_text()
                            title = text.split("\n")[0]
                        except Exception:
                            title = "Ogłoszenie Vinted"

                    price_elem = item.locator(
                        '[data-testid*="price"]'
                    )

                    if await price_elem.count() > 0:
                        price = await price_elem.inner_text()
                    else:
                        price = "Brak ceny"

                    img_elem = item.locator("img").first

                    if await img_elem.count() > 0:
                        image = await img_elem.get_attribute("src")
                    else:
                        image = ""

                    found.append(
                        {
                            "source": "Vinted",
                            "url": full_url,
                            "title": (
                                title.strip()
                                if title
                                else "Ogłoszenie Vinted"
                            ),
                            "price": price.strip(),
                            "image": image or ""
                        }
                    )

                    count += 1

                    if count >= MAX_RESULTS_PER_SEARCH:
                        break

                except Exception:
                    continue

            log.info(
                f"Vinted {search}: znaleziono {count} ofert"
            )

        except Exception as e:
            log.warning(
                f"⚠️ Vinted {search}: "
                f"{type(e).__name__}: {e}"
            )

    log.info(
        f"Vinted: znaleziono łącznie {len(found)} ofert"
    )

    return found


# ============================================================
# WSPÓLNY SKAN OLX + VINTED
# ============================================================

async def scan_both(olx_page, vinted_page):
    log.info(
        "🔎 OLX + VINTED — SKAN RÓWNOCZESNY"
    )

    olx_task = asyncio.create_task(
        scan_olx(olx_page)
    )

    vinted_task = asyncio.create_task(
        scan_vinted(vinted_page)
    )

    results = await asyncio.gather(
        olx_task,
        vinted_task,
        return_exceptions=True
    )

    olx_results = []
    vinted_results = []

    if isinstance(results[0], Exception):
        log.error(
            f"❌ OLX — błąd całego skanu: "
            f"{results[0]}"
        )
    else:
        olx_results = results[0]

    if isinstance(results[1], Exception):
        log.error(
            f"❌ Vinted — błąd całego skanu: "
            f"{results[1]}"
        )
    else:
        vinted_results = results[1]

    return olx_results + vinted_results


# ============================================================
# GŁÓWNA PĘTLA
# ============================================================

async def run_bot():
    webhook = get_webhook()

    if not webhook:
        log.error(
            "❌ DISCORD_WEBHOOK nie został znaleziony."
        )
        log.error(
            "❌ Sprawdź Render → Environment → "
            "DISCORD_WEBHOOK."
        )
        return

    log.info("======================================")
    log.info("📱 IPHONE FLIP BOT")
    log.info("OLX + VINTED")
    log.info("⏱️ Wspólny skan co 15 sekund")
    log.info("======================================")

    send_test_message()

    known = set()
    first_scan = True

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = await browser.new_context(
            viewport={
                "width": 1280,
                "height": 720
            },
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            )
        )

        olx_page = await context.new_page()
        vinted_page = await context.new_page()

        while True:

            cycle_start = time.monotonic()

            log.info(
                "🔎 ROZPOCZYNAM WSPÓLNY SKAN OLX + VINTED"
            )

            try:
                all_results = await scan_both(
                    olx_page,
                    vinted_page
                )

                log.info(
                    f"📦 Znaleziono łącznie: "
                    f"{len(all_results)}"
                )

                new_count = 0

                if first_scan:

                    for offer in all_results:
                        offer_url = offer.get("url")

                        if offer_url:
                            known.add(offer_url)

                    first_scan = False

                    log.info(
                        f"🟢 Pierwszy skan — zapisano "
                        f"{len(known)} istniejących ofert. "
                        f"Nie wysyłam ich."
                    )

                else:

                    for offer in all_results:

                        offer_url = offer.get("url")

                        if not offer_url:
                            continue

                        if offer_url in known:
                            continue

                        known.add(offer_url)
                        new_count += 1

                        send_discord(
                            title=offer.get(
                                "title",
                                "Nowe ogłoszenie"
                            ),
                            price=offer.get(
                                "price",
                                "Brak ceny"
                            ),
                            url=offer_url,
                            image=offer.get(
                                "image",
                                ""
                            ),
                            source=offer.get(
                                "source",
                                ""
                            )
                        )

                        await asyncio.sleep(0.5)

                log.info(
                    f"🆕 Nowych ofert: {new_count}"
                )

            except Exception as e:

                log.exception(
                    f"❌ Błąd wspólnego skanu: {e}"
                )

            elapsed = time.monotonic() - cycle_start

            wait_time = max(
                0,
                SCAN_INTERVAL - elapsed
            )

            log.info(
                f"⏱️ Następny wspólny skan za "
                f"{wait_time:.1f} sekund"
            )

            await asyncio.sleep(wait_time)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    asyncio.run(run_bot())
