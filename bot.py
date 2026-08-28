import os
import asyncio
import logging
import threading
import time
from urllib.parse import quote, urljoin

import requests
from flask import Flask
from playwright.async_api import async_playwright


# ============================================================
# KONFIGURACJA
# ============================================================

SCAN_INTERVAL = 15

SEARCH_TEXT = "iphone"

MAX_RESULTS = 100

PLAYWRIGHT_TIMEOUT = 12000


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
        return webhook.strip()

    return None


def send_discord(title, price, url, image="", source=""):
    webhook = get_webhook()

    if not webhook:
        log.error("❌ Brak DISCORD_WEBHOOK.")
        return False

    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
        "url": url,
        "color": 5814783 if source == "OLX" else 65490,
        "description": (
            f"💰 **Cena:** {price or 'Brak ceny'}\n"
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

    try:
        response = requests.post(
            webhook,
            json={"embeds": [embed]},
            timeout=10
        )

        if 200 <= response.status_code < 300:
            log.info(
                f"✅ Discord [{source}]: wysłano -> "
                f"{(title or 'Ogłoszenie')[:70]}"
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
# OLX
# ============================================================

async def scan_olx(page):
    found = []
    seen = set()

    url = (
        "https://www.olx.pl/d/elektronika/telefony/"
        "telefony-komorkowe/"
        f"q-{quote(SEARCH_TEXT)}/"
        "?search%5Border%5D=created_at:desc"
    )

    log.info("OLX: sprawdzam iphone")

    try:
        await page.goto(
            url,
            wait_until="commit",
            timeout=PLAYWRIGHT_TIMEOUT
        )

    except Exception as e:
        log.warning(
            f"⚠️ OLX goto: {type(e).__name__}: {e}"
        )

    try:
        await page.wait_for_timeout(3500)
    except Exception:
        pass

    # --------------------------------------------------------
    # DIAGNOSTYKA
    # --------------------------------------------------------

    try:
        current_url = page.url

        title = await page.title()

        body_text = ""

        try:
            body_text = await page.locator("body").inner_text(
                timeout=3000
            )
        except Exception:
            pass

        log.info(
            f"OLX: aktualny URL: {current_url}"
        )

        log.info(
            f"OLX: tytuł strony: {title[:150]}"
        )

        log.info(
            f"OLX: tekst strony: "
            f"{body_text[:250].replace(chr(10), ' ')}"
        )

    except Exception as e:
        log.warning(
            f"⚠️ OLX diagnostyka: {e}"
        )

    # --------------------------------------------------------
    # GŁÓWNY PARSER
    # --------------------------------------------------------

    selectors = [
        '[data-cy="l-card"]',
        '[data-testid="l-card"]',
        'div[data-cy="l-card"]',
        'article'
    ]

    cards = None
    card_count = 0

    for selector in selectors:

        try:
            locator = page.locator(selector)

            count = await locator.count()

            if count > card_count:

                cards = locator
                card_count = count

        except Exception:
            continue

    log.info(
        f"OLX: parser kart widzi {card_count} elementów"
    )

    # --------------------------------------------------------
    # PARSOWANIE KART
    # --------------------------------------------------------

    if cards:

        for i in range(
            min(card_count, MAX_RESULTS)
        ):

            try:

                card = cards.nth(i)

                links = card.locator("a")

                link_count = await links.count()

                href = None

                for j in range(
                    min(link_count, 10)
                ):

                    try:

                        candidate = await links.nth(
                            j
                        ).get_attribute("href")

                        if candidate and "/d/oferta/" in candidate:

                            href = candidate
                            break

                    except Exception:
                        continue

                if not href:
                    continue

                full_url = urljoin(
                    "https://www.olx.pl",
                    href
                ).split("?")[0]

                if full_url in seen:
                    continue

                # -------------------------------
                # TYTUŁ
                # -------------------------------

                title = ""

                for selector in [
                    "h6",
                    "h4",
                    '[data-testid="ad-title"]',
                    "a"
                ]:

                    try:

                        element = card.locator(
                            selector
                        ).first

                        if await element.count() > 0:

                            text = await element.inner_text()

                            if text.strip():

                                title = text.strip()
                                break

                    except Exception:
                        continue

                if not title:
                    title = "Ogłoszenie OLX"

                # -------------------------------
                # CENA
                # -------------------------------

                price = "Brak ceny"

                for selector in [
                    '[data-testid="ad-price"]',
                    '[data-testid*="price"]'
                ]:

                    try:

                        element = card.locator(
                            selector
                        ).first

                        if await element.count() > 0:

                            text = await element.inner_text()

                            if text.strip():

                                price = text.strip()
                                break

                    except Exception:
                        continue

                # -------------------------------
                # ZDJĘCIE
                # -------------------------------

                image = ""

                try:

                    img = card.locator("img").first

                    if await img.count() > 0:

                        image = (
                            await img.get_attribute(
                                "src"
                            )
                            or
                            await img.get_attribute(
                                "data-src"
                            )
                            or
                            ""
                        )

                except Exception:
                    pass

                seen.add(full_url)

                found.append({
                    "source": "OLX",
                    "url": full_url,
                    "title": title[:256],
                    "price": price,
                    "image": image
                })

            except Exception:
                continue

    # --------------------------------------------------------
    # ALTERNATYWNY PARSER LINKÓW
    # --------------------------------------------------------

    if not found:

        try:

            links = page.locator(
                'a[href*="/d/oferta/"]'
            )

            link_count = await links.count()

            log.info(
                f"OLX: alternatywny parser widzi "
                f"{link_count} linków ofert"
            )

            for i in range(
                min(link_count, MAX_RESULTS)
            ):

                try:

                    link = links.nth(i)

                    href = await link.get_attribute(
                        "href"
                    )

                    if not href:
                        continue

                    if "/d/oferta/" not in href:
                        continue

                    full_url = urljoin(
                        "https://www.olx.pl",
                        href
                    ).split("?")[0]

                    if full_url in seen:
                        continue

                    title = ""

                    try:
                        title = await link.get_attribute(
                            "title"
                        )
                    except Exception:
                        pass

                    if not title:

                        try:
                            title = await link.inner_text()
                        except Exception:
                            title = ""

                    if not title:
                        title = "Ogłoszenie OLX"

                    title = title.strip()

                    price = "Brak ceny"

                    try:

                        parent = link.locator(
                            "xpath=.."
                        )

                        text = await parent.inner_text()

                        for line in text.split("\n"):

                            line = line.strip()

                            if "zł" in line.lower():

                                price = line
                                break

                    except Exception:
                        pass

                    image = ""

                    try:

                        img = link.locator(
                            "img"
                        ).first

                        if await img.count() > 0:

                            image = (
                                await img.get_attribute(
                                    "src"
                                )
                                or
                                ""
                            )

                    except Exception:
                        pass

                    seen.add(full_url)

                    found.append({
                        "source": "OLX",
                        "url": full_url,
                        "title": title[:256],
                        "price": price,
                        "image": image
                    })

                except Exception:
                    continue

        except Exception as e:

            log.warning(
                f"⚠️ OLX alternatywny parser: {e}"
            )

    log.info(
        f"OLX: znaleziono "
        f"{len(found)} poprawnych ofert"
    )

    return found


# ============================================================
# VINTED
# ============================================================

async def scan_vinted(page):
    found = []
    seen = set()

    url = (
        "https://www.vinted.pl/catalog"
        f"?search_text={quote(SEARCH_TEXT)}"
        "&order=newest_first"
    )

    log.info("Vinted: sprawdzam iphone")

    try:

        await page.goto(
            url,
            wait_until="commit",
            timeout=PLAYWRIGHT_TIMEOUT
        )

    except Exception as e:

        log.warning(
            f"⚠️ Vinted goto: "
            f"{type(e).__name__}: {e}"
        )

    try:
        await page.wait_for_timeout(3500)
    except Exception:
        pass

    items = page.locator(
        '[data-testid="grid-item"]'
    )

    item_count = await items.count()

    log.info(
        f"Vinted: parser widzi "
        f"{item_count} kart"
    )

    for i in range(
        min(item_count, MAX_RESULTS)
    ):

        try:

            item = items.nth(i)

            links = item.locator("a")

            link_count = await links.count()

            href = None

            for j in range(
                min(link_count, 10)
            ):

                try:

                    candidate = await links.nth(
                        j
                    ).get_attribute("href")

                    if candidate and "/items/" in candidate:

                        href = candidate
                        break

                except Exception:
                    continue

            if not href:
                continue

            full_url = urljoin(
                "https://www.vinted.pl",
                href
            ).split("?")[0]

            if full_url in seen:
                continue

            title = ""

            try:

                title = await links.first.get_attribute(
                    "title"
                )

            except Exception:
                pass

            if not title:

                try:
                    title = await item.inner_text()
                except Exception:
                    title = ""

            if title:
                title = title.split("\n")[0].strip()

            if not title:
                title = "Ogłoszenie Vinted"

            price = "Brak ceny"

            try:

                price_elem = item.locator(
                    '[data-testid*="price"]'
                ).first

                if await price_elem.count() > 0:

                    text = await price_elem.inner_text()

                    if text.strip():
                        price = text.strip()

            except Exception:
                pass

            image = ""

            try:

                img = item.locator("img").first

                if await img.count() > 0:

                    image = (
                        await img.get_attribute(
                            "src"
                        )
                        or
                        await img.get_attribute(
                            "data-src"
                        )
                        or
                        ""
                    )

            except Exception:
                pass

            seen.add(full_url)

            found.append({
                "source": "Vinted",
                "url": full_url,
                "title": title[:256],
                "price": price,
                "image": image
            })

        except Exception:
            continue

    log.info(
        f"Vinted: znaleziono "
        f"{len(found)} poprawnych ofert"
    )

    return found


# ============================================================
# WSPÓLNY SKAN
# ============================================================

async def scan_both(
    olx_page,
    vinted_page
):

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

    if isinstance(
        results[0],
        Exception
    ):

        log.error(
            f"❌ OLX — błąd całego skanu: "
            f"{results[0]}"
        )

    else:

        olx_results = results[0]

    if isinstance(
        results[1],
        Exception
    ):

        log.error(
            f"❌ Vinted — błąd całego skanu: "
            f"{results[1]}"
        )

    else:

        vinted_results = results[1]

    all_results = (
        olx_results +
        vinted_results
    )

    unique = []

    urls = set()

    for offer in all_results:

        offer_url = offer.get("url")

        if not offer_url:
            continue

        if offer_url in urls:
            continue

        urls.add(offer_url)

        unique.append(offer)

    log.info(
        f"📦 Łącznie poprawnych ofert: "
        f"{len(unique)}"
    )

    return unique


# ============================================================
# GŁÓWNA PĘTLA
# ============================================================

async def run_bot():

    webhook = get_webhook()

    if not webhook:

        log.error(
            "❌ DISCORD_WEBHOOK nie został znaleziony."
        )

        return

    log.info(
        "======================================"
    )

    log.info(
        "📱 IPHONE FLIP BOT"
    )

    log.info(
        "OLX + VINTED"
    )

    log.info(
        "🔎 WSPÓLNE WYSZUKIWANIE: IPHONE"
    )

    log.info(
        "📱 MODELE: IPHONE 11–17"
    )

    log.info(
        "⏱️ PRZERWA MIĘDZY SKANAMI: 15 SEKUND"
    )

    log.info(
        "======================================"
    )

    # --------------------------------------------------------
    # WAŻNE:
    # Nie wysyłamy wiadomości testowej przy starcie.
    # --------------------------------------------------------

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
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            )
        )

        olx_page = await context.new_page()

        vinted_page = await context.new_page()

        # ----------------------------------------------------
        # Dodatkowe zabezpieczenie timeoutów
        # ----------------------------------------------------

        olx_page.set_default_timeout(
            PLAYWRIGHT_TIMEOUT
        )

        vinted_page.set_default_timeout(
            PLAYWRIGHT_TIMEOUT
        )

        while True:

            scan_start = time.monotonic()

            log.info(
                "🔎 ROZPOCZYNAM WSPÓLNY SKAN"
            )

            try:

                all_results = await scan_both(
                    olx_page,
                    vinted_page
                )

                new_count = 0

                # ------------------------------------------------
                # PIERWSZY SKAN
                # ------------------------------------------------

                if first_scan:

                    for offer in all_results:

                        offer_url = offer.get(
                            "url"
                        )

                        if offer_url:

                            known.add(
                                offer_url
                            )

                    first_scan = False

                    log.info(
                        f"🟢 Pierwszy skan — zapisano "
                        f"{len(known)} istniejących ofert."
                    )

                    log.info(
                        "🟢 Istniejące oferty NIE "
                        "zostaną wysłane."
                    )

                # ------------------------------------------------
                # KOLEJNE SKANY
                # ------------------------------------------------

                else:

                    for offer in all_results:

                        offer_url = offer.get(
                            "url"
                        )

                        if not offer_url:
                            continue

                        if offer_url in known:
                            continue

                        known.add(
                            offer_url
                        )

                        new_count += 1

                        log.info(
                            f"🆕 NOWA OFERTA "
                            f"[{offer.get('source')}] "
                            f"{offer.get('title', '')[:80]}"
                        )

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

                        await asyncio.sleep(
                            0.5
                        )

                log.info(
                    f"🆕 Nowych ofert: "
                    f"{new_count}"
                )

            except Exception as e:

                log.exception(
                    f"❌ Błąd wspólnego skanu: "
                    f"{e}"
                )

            elapsed = (
                time.monotonic()
                - scan_start
            )

            log.info(
                f"⏱️ Skan trwał "
                f"{elapsed:.1f} s"
            )

            # ----------------------------------------------------
            # ZAWSZE PEŁNE 15 SEKUND PRZERWY
            # ----------------------------------------------------

            log.info(
                "⏳ Skan zakończony. "
                "Czekam 15 sekund..."
            )

            await asyncio.sleep(
                SCAN_INTERVAL
            )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    asyncio.run(
        run_bot()
    )
