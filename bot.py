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

PLAYWRIGHT_TIMEOUT = 15000


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
                f"{(title or 'Ogłoszenie')[:60]}"
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
            wait_until="domcontentloaded",
            timeout=PLAYWRIGHT_TIMEOUT
        )

    except Exception as e:
        log.warning(
            f"⚠️ OLX goto: {type(e).__name__}: {e}"
        )

        # Nawet jeśli domcontentloaded timeoutuje,
        # próbujemy parsować to, co zdążyło się załadować.
        try:
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    try:
        await page.wait_for_timeout(2500)
    except Exception:
        pass

    # --------------------------------------------------------
    # Parser OLX — kilka wariantów selektorów
    # --------------------------------------------------------

    cards = page.locator(
        '[data-cy="l-card"], '
        '[data-testid="l-card"], '
        'div[data-cy="l-card"]'
    )

    card_count = await cards.count()

    log.info(
        f"OLX: parser kart widzi {card_count} elementów"
    )

    # --------------------------------------------------------
    # Najpierw normalne karty
    # --------------------------------------------------------

    for i in range(min(card_count, MAX_RESULTS)):
        try:
            card = cards.nth(i)

            links = card.locator("a")
            link_count = await links.count()

            href = None

            for j in range(min(link_count, 5)):
                try:
                    candidate = await links.nth(j).get_attribute("href")

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

            # tytuł
            title = ""

            for selector in [
                "h6",
                "h4",
                '[data-testid="ad-title"]',
                "a"
            ]:
                try:
                    element = card.locator(selector).first

                    if await element.count() > 0:
                        text = await element.inner_text()

                        if text.strip():
                            title = text.strip()
                            break

                except Exception:
                    continue

            if not title:
                title = "Ogłoszenie OLX"

            # cena
            price = "Brak ceny"

            for selector in [
                '[data-testid="ad-price"]',
                '[data-testid*="price"]'
            ]:
                try:
                    element = card.locator(selector).first

                    if await element.count() > 0:
                        text = await element.inner_text()

                        if text.strip():
                            price = text.strip()
                            break

                except Exception:
                    continue

            # zdjęcie
            image = ""

            try:
                img = card.locator("img").first

                if await img.count() > 0:
                    image = (
                        await img.get_attribute("src")
                        or
                        await img.get_attribute("data-src")
                        or
                        ""
                    )

            except Exception:
                pass

            seen.add(full_url)

            found.append({
                "source": "OLX",
                "url": full_url,
                "title": title,
                "price": price,
                "image": image
            })

        except Exception:
            continue

    # --------------------------------------------------------
    # ALTERNATYWNY PARSER
    #
    # Jeżeli OLX zmienił HTML i karty nie są dostępne,
    # szukamy wszystkich linków do /d/oferta/
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

            for i in range(min(link_count, MAX_RESULTS)):

                try:
                    link = links.nth(i)

                    href = await link.get_attribute("href")

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
                        title = await link.get_attribute("title")
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

                    # próbujemy znaleźć rodzica zawierającego cenę
                    price = "Brak ceny"

                    try:
                        parent = link.locator("xpath=..")

                        parent_text = await parent.inner_text()

                        if parent_text:
                            lines = [
                                x.strip()
                                for x in parent_text.split("\n")
                                if x.strip()
                            ]

                            for line in lines:
                                if "zł" in line.lower():
                                    price = line
                                    break

                    except Exception:
                        pass

                    image = ""

                    try:
                        img = link.locator("img").first

                        if await img.count() > 0:
                            image = (
                                await img.get_attribute("src")
                                or ""
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
        f"OLX: znaleziono {len(found)} poprawnych ofert"
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
            wait_until="domcontentloaded",
            timeout=PLAYWRIGHT_TIMEOUT
        )

    except Exception as e:
        log.warning(
            f"⚠️ Vinted goto: {type(e).__name__}: {e}"
        )

        try:
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    try:
        await page.wait_for_timeout(2500)
    except Exception:
        pass

    items = page.locator(
        '[data-testid="grid-item"]'
    )

    item_count = await items.count()

    log.info(
        f"Vinted: parser widzi {item_count} kart"
    )

    for i in range(min(item_count, MAX_RESULTS)):

        try:
            item = items.nth(i)

            links = item.locator("a")

            link_count = await links.count()

            href = None

            for j in range(min(link_count, 5)):

                try:
                    candidate = await links.nth(j).get_attribute(
                        "href"
                    )

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

            # tytuł
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

            # cena
            price = "Brak ceny"

            for selector in [
                '[data-testid*="price"]'
            ]:

                try:
                    price_elem = item.locator(
                        selector
                    ).first

                    if await price_elem.count() > 0:
                        text = await price_elem.inner_text()

                        if text.strip():
                            price = text.strip()
                            break

                except Exception:
                    continue

            # zdjęcie
            image = ""

            try:
                img = item.locator("img").first

                if await img.count() > 0:
                    image = (
                        await img.get_attribute("src")
                        or
                        await img.get_attribute("data-src")
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
        f"Vinted: znaleziono {len(found)} poprawnych ofert"
    )

    return found


# ============================================================
# WSPÓLNY SKAN
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
            f"❌ OLX — błąd skanu: {results[0]}"
        )

    else:

        olx_results = results[0]

    if isinstance(results[1], Exception):

        log.error(
            f"❌ Vinted — błąd skanu: {results[1]}"
        )

    else:

        vinted_results = results[1]

    all_results = (
        olx_results +
        vinted_results
    )

    # --------------------------------------------------------
    # Usunięcie duplikatów
    # --------------------------------------------------------

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
        f"📦 Łącznie poprawnych ofert: {len(unique)}"
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
        "📱 MODELE: IPHONE 11–17 I Nowsze"
    )

    log.info(
        "⏱️ PRZERWA MIĘDZY SKANAMI: 15 SEKUND"
    )

    log.info(
        "======================================"
    )

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

                        offer_url = offer.get("url")

                        if offer_url:
                            known.add(offer_url)

                    first_scan = False

                    log.info(
                        f"🟢 Pierwszy skan — zapisano "
                        f"{len(known)} istniejących ofert."
                    )

                    log.info(
                        "🟢 Istniejące oferty NIE zostaną "
                        "wysłane na Discord."
                    )

                # ------------------------------------------------
                # KOLEJNE SKANY
                # ------------------------------------------------

                else:

                    for offer in all_results:

                        offer_url = offer.get("url")

                        if not offer_url:
                            continue

                        if offer_url in known:
                            continue

                        known.add(offer_url)

                        new_count += 1

                        log.info(
                            f"🆕 NOWA OFERTA [{offer.get('source')}] "
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

                        await asyncio.sleep(0.5)

                log.info(
                    f"🆕 Nowych ofert: {new_count}"
                )

            except Exception as e:

                log.exception(
                    f"❌ Błąd wspólnego skanu: {e}"
                )

            # ----------------------------------------------------
            # WAŻNE:
            #
            # ZAWSZE czekamy pełne 15 sekund PO SKANIE.
            #
            # Nie ma już:
            # max(0, 15 - elapsed)
            #
            # Dzięki temu nie będzie:
            # "Następny wspólny skan za 0.0 sekund"
            # ----------------------------------------------------

            elapsed = time.monotonic() - scan_start

            log.info(
                f"⏱️ Skan trwał {elapsed:.1f} s"
            )

            log.info(
                "⏳ Skan zakończony. "
                "Czekam 15 sekund przed kolejnym..."
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
