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

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

SCAN_INTERVAL = 15

# Zmień frazy, jeśli chcesz inne modele
SEARCHES = [
    "iphone",
    "iphone 11",
    "iphone 12",
    "iphone 13",
    "iphone 14",
    "iphone 15",
    "iphone 16",
]

# Maksymalna liczba ofert pobieranych z każdej strony wyszukiwania
MAX_RESULTS_PER_SEARCH = 30


# ============================================================
# LOGOWANIE
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")


# ============================================================
# FLASK — ŻEBY RENDER WIDZIAŁ AKTYWNY SERWER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "iPhone Flip Bot działa."


def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ============================================================
# DISCORD
# ============================================================

def send_discord(title, price, url, image=None, source=""):
    if not DISCORD_WEBHOOK:
        log.error("Brak zmiennej DISCORD_WEBHOOK.")
        return False

    embed = {
        "title": title[:256] if title else "Nowe ogłoszenie",
        "url": url,
        "description": (
            f"💰 **Cena:** {price or 'brak danych'}\n"
            f"🌐 **Źródło:** {source}"
        ),
        "footer": {
            "text": "iPhone Flip Bot"
        }
    }

    if image:
        embed["thumbnail"] = {"url": image}

    payload = {
        "embeds": [embed]
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK,
            json=payload,
            timeout=15
        )

        if 200 <= response.status_code < 300:
            log.info("✅ Discord: wiadomość wysłana")
            return True

        log.error(
            "❌ Discord HTTP %s: %s",
            response.status_code,
            response.text[:300]
        )

    except Exception as e:
        log.error("❌ Discord error: %s", e)

    return False


# ============================================================
# POMOCNICZE
# ============================================================

def clean_text(value):
    if not value:
        return ""

    return " ".join(value.split()).strip()


def normalize_url(url):
    if not url:
        return ""

    if url.startswith("/"):
        if "vinted" in url:
            return "https://www.vinted.pl" + url
        return "https://www.olx.pl" + url

    return url.split("?")[0]


# ============================================================
# OLX
# ============================================================

async def scan_olx(page):
    found = []

    for search in SEARCHES:
        try:
            url = (
                "https://www.olx.pl/d/oferty/q-"
                + quote(search)
                + "/"
            )

            log.info("OLX: sprawdzam %s", search)

            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            await page.wait_for_timeout(2500)

            links = await page.locator("a").evaluate_all(
                """
                elements => elements.map(a => ({
                    href: a.href,
                    text: a.innerText
                }))
                """
            )

            count = 0

            for item in links:
                href = normalize_url(item.get("href", ""))
                text = clean_text(item.get("text", ""))

                if not href:
                    continue

                if "/d/oferta/" not in href:
                    continue

                if href in {x["url"] for x in found}:
                    continue

                title = text or "Ogłoszenie OLX"

                found.append({
                    "source": "OLX",
                    "url": href,
                    "title": title,
                    "price": "",
                    "image": ""
                })

                count += 1

                if count >= MAX_RESULTS_PER_SEARCH:
                    break

            log.info(
                "OLX %s: znaleziono %s ofert",
                search,
                count
            )

        except Exception as e:
            log.error("OLX %s error: %s", search, e)

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
                "?search_text="
                + quote(search)
            )

            log.info("Vinted: sprawdzam %s", search)

            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            await page.wait_for_timeout(3000)

            links = await page.locator("a").evaluate_all(
                """
                elements => elements.map(a => ({
                    href: a.href,
                    text: a.innerText
                }))
                """
            )

            count = 0

            for item in links:
                href = normalize_url(item.get("href", ""))
                text = clean_text(item.get("text", ""))

                if not href:
                    continue

                if "/items/" not in href:
                    continue

                if href in {x["url"] for x in found}:
                    continue

                found.append({
                    "source": "Vinted",
                    "url": href,
                    "title": text or "Ogłoszenie Vinted",
                    "price": "",
                    "image": ""
                })

                count += 1

                if count >= MAX_RESULTS_PER_SEARCH:
                    break

            log.info(
                "Vinted %s: znaleziono %s ofert",
                search,
                count
            )

        except Exception as e:
            log.error("Vinted %s error: %s", search, e)

    return found


# ============================================================
# GŁÓWNY BOT
# ============================================================

async def run_bot():

    if not DISCORD_WEBHOOK:
        log.error(
            "❌ Nie ustawiono DISCORD_WEBHOOK w Render Environment."
        )
        return

    log.info("======================================")
    log.info("📱 IPHONE FLIP BOT")
    log.info("OLX + VINTED")
    log.info("⏱️ Wspólny skan co %s sekund", SCAN_INTERVAL)
    log.info("======================================")

    known = set()

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        context = await browser.new_context(
            viewport={
                "width": 1280,
                "height": 900
            },
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            )
        )

        olx_page = await context.new_page()
        vinted_page = await context.new_page()

        first_scan = True

        while True:

            cycle_start = time.time()

            log.info("🔎 OLX + VINTED — SKAN RÓWNOCZESNY")

            try:
                olx_task = scan_olx(olx_page)
                vinted_task = scan_vinted(vinted_page)

                olx_results, vinted_results = await asyncio.gather(
                    olx_task,
                    vinted_task,
                    return_exceptions=True
                )

                if isinstance(olx_results, Exception):
                    log.error("OLX error: %s", olx_results)
                    olx_results = []

                if isinstance(vinted_results, Exception):
                    log.error("Vinted error: %s", vinted_results)
                    vinted_results = []

                all_results = olx_results + vinted_results

                log.info(
                    "📦 Łącznie znaleziono: %s ofert",
                    len(all_results)
                )

                new_count = 0

                # ------------------------------------------------
                # PIERWSZY SKAN:
                # zapamiętujemy istniejące oferty,
                # ale NIE wysyłamy ich na Discord.
                # ------------------------------------------------

                if first_scan:

                    for offer in all_results:
                        known.add(offer["url"])

                    first_scan = False

                    log.info(
                        "🟢 Pierwszy skan zakończony."
                    )
                    log.info(
                        "Zapamiętano %s istniejących ofert.",
                        len(known)
                    )

                else:

                    for offer in all_results:

                        offer_url = offer["url"]

                        if not offer_url:
                            continue

                        if offer_url in known:
                            continue

                        known.add(offer_url)

                        new_count += 1

                        log.info(
                            "🆕 NOWA OFERTA | %s | %s",
                            offer["source"],
                            offer["title"][:100]
                        )

                        send_discord(
                            title=offer["title"],
                            price=offer["price"],
                            url=offer["url"],
                            image=offer["image"],
                            source=offer["source"]
                        )

                log.info(
                    "✅ Skan zakończony | nowych: %s | następny za %s sekund",
                    new_count,
                    SCAN_INTERVAL
                )

            except Exception as e:
                log.exception(
                    "❌ Błąd głównego skanowania: %s",
                    e
                )

            elapsed = time.time() - cycle_start

            wait_time = max(
                1,
                SCAN_INTERVAL - elapsed
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
