import os
import asyncio
import logging
import threading
import time
import json
import re
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from flask import Flask
from playwright.async_api import async_playwright

# ============================================================
# KONFIGURACJA
# ============================================================

SCAN_INTERVAL = 25          # Przerwa między skanami (sekundy)
SEARCH_TEXT = "iphone"      # Szukana fraza
MAX_RESULTS = 30            # Liczba ogłoszeń
TIMEOUT = 20000             # Max czas czekania (20s)

# ============================================================
# LOGOWANIE
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("iphone-bot")

# ============================================================
# FLASK (Keep-Alive)
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot działa i monitoruje OLX + Vinted."

def start_web_server():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ============================================================
# DISCORD
# ============================================================

def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK")
    return webhook.strip() if webhook else None

async def send_discord(title, price, url, image="", source=""):
    webhook = get_webhook()
    if not webhook:
        log.error("❌ BRAK DISCORD_WEBHOOK W ZMIENNYCH RENDER!")
        return False

    color = 23295 if source == "OLX" else 38550

    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
        "url": url,
        "color": color,
        "description": f"💰 **Cena:** {price or 'Brak'}\n🌐 **Źródło:** {source}",
        "footer": {"text": "iPhone Notifier Bot"}
    }

    if image and image.startswith("http"):
        embed["thumbnail"] = {"url": image}

    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = Request(
        webhook, 
        data=payload, 
        headers={
            "Content-Type": "application/json", 
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
    )

    try:
        def _post():
            with urlopen(req, timeout=10) as resp:
                return resp.status

        status = await asyncio.to_thread(_post)
        if 200 <= status < 300:
            log.info(f"🚀 [DISCORD SENT] [{source}] {title[:40]} - {price}")
            return True
        log.error(f"❌ Discord odpowiedział kodem HTTP {status}")
    except Exception as e:
        log.error(f"❌ Błąd wysyłania powiadomienia na Discord: {e}")
    return False

# ============================================================
# SKANER OLX (Poprawiona obsługa ciasteczek i nawigacji)
# ============================================================

async def scan_olx(page):
    found = []
    url = f"https://www.olx.pl/d/oferty/q-{quote(SEARCH_TEXT)}/?search%5Border%5D=created_at:desc"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        
        # Szybkie zamknięcie banera RODO bez czekania 30s
        try:
            cookie_btn = page.locator("#onetrust-accept-btn-handler")
            if await cookie_btn.is_visible(timeout=2000):
                await cookie_btn.click(force=True, timeout=2000)
        except Exception:
            pass

        await asyncio.sleep(1.5)
        await page.evaluate("window.scrollBy(0, 500)")
        await asyncio.sleep(1)

        cards = page.locator('[data-cy="l-card"]')
        card_count = await cards.count()

        for i in range(min(card_count, MAX_RESULTS)):
            try:
                card = cards.nth(i)
                link_elem = card.locator('a[href*="/d/oferta/"]').first
                if await link_elem.count() == 0:
                    continue

                href = await link_elem.get_attribute("href")
                if not href:
                    continue

                full_url = urljoin("https://www.olx.pl", href).split("?")[0]

                title_elem = card.locator('[data-cy="ad-card-title"], h6, h4').first
                title = await title_elem.inner_text() if await title_elem.count() > 0 else "Oferta OLX"

                price_elem = card.locator('[data-element-type="price"], [data-testid="ad-price"]').first
                price = await price_elem.inner_text() if await price_elem.count() > 0 else "Brak ceny"

                img_elem = card.locator("img").first
                image = ""
                if await img_elem.count() > 0:
                    image = await img_elem.get_attribute("src") or await img_elem.get_attribute("data-src") or ""

                found.append({
                    "source": "OLX",
                    "url": full_url,
                    "title": title.strip().replace("\n", " "),
                    "price": price.strip().replace("\n", " "),
                    "image": image
                })
            except Exception:
                continue

    except Exception as e:
        log.warning(f"⚠️ Problem podczas pobierania OLX: {e}")

    log.info(f"🔎 OLX: Znaleziono {len(found)} ofert.")
    return found

# ============================================================
# SKANER VINTED (Szybkie i bezbłędne pobieranie HTTP)
# ============================================================

def _fetch_vinted_http():
    found = []
    url = f"https://www.vinted.pl/api/v2/catalog/items?search_text={quote(SEARCH_TEXT)}&order=newest_first&per_page={MAX_RESULTS}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9",
    }

    try:
        # Pobieranie wstępnych ciasteczek
        session_req = Request("https://www.vinted.pl", headers=headers)
        cookie_str = ""
        with urlopen(session_req, timeout=8) as resp:
            cookies = resp.headers.get_all("Set-Cookie")
            if cookies:
                cookie_str = "; ".join([c.split(";")[0] for c in cookies])

        if cookie_str:
            headers["Cookie"] = cookie_str

        # Pobieranie danych ogłoszeń
        req = Request(url, headers=headers)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])
            for item in items:
                title = item.get("title") or "Oferta Vinted"
                price_val = item.get("price") or item.get("total_item_price") or "Brak ceny"
                currency = item.get("currency") or "PLN"
                price_str = f"{price_val} {currency}"

                item_url = item.get("url")
                if not item_url:
                    item_id = item.get("id")
                    item_url = f"https://www.vinted.pl/items/{item_id}"

                photos = item.get("photos", [])
                image = photos[0].get("url", "") if photos else ""

                found.append({
                    "source": "Vinted",
                    "url": item_url.split("?")[0],
                    "title": title.strip().replace("\n", " "),
                    "price": price_str,
                    "image": image
                })
    except Exception as e:
        log.warning(f"⚠️ Vinted HTTP pobieranie: {e}")

    return found

async def scan_vinted(page=None):
    found = await asyncio.to_thread(_fetch_vinted_http)
    log.info(f"🔎 Vinted: Znaleziono {len(found)} ofert.")
    return found

# ============================================================
# PĘTLA GŁÓWNA
# ============================================================

async def run_bot():
    if not get_webhook():
        log.error("❌ BŁĄD: Zmienna środowiskowa DISCORD_WEBHOOK jest pusta!")
        return

    log.info("🚀 Uruchamianie bota (OLX + Vinted)...")

    known_urls = set()
    first_scan = True

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        page = await context.new_page()

        while True:
            scan_start = time.monotonic()
            log.info("--------------------------------------------------")
            log.info("🔄 Skanowanie w toku...")

            olx_offers = await scan_olx(page)
            vinted_offers = await scan_vinted()

            all_offers = olx_offers + vinted_offers
            new_count = 0

            for offer in all_offers:
                url = offer["url"]
                if url in known_urls:
                    continue

                known_urls.add(url)

                if not first_scan:
                    new_count += 1
                    await send_discord(
                        title=offer["title"],
                        price=offer["price"],
                        url=url,
                        image=offer["image"],
                        source=offer["source"]
                    )
                    await asyncio.sleep(0.5)

            if first_scan:
                log.info(f"🟢 Pierwszy skan zakończony. Zapisano {len(known_urls)} istniejących ofert do pamięci.")
                first_scan = False
            else:
                log.info(f"📦 Zakończono skanowanie. Wysłąno nowych powiadomień: {new_count}")

            elapsed = time.monotonic() - scan_start
            sleep_time = max(0.0, SCAN_INTERVAL - elapsed)
            log.info(f"⏱️ Czas skanowania: {elapsed:.1f}s. Następny skan za {sleep_time:.1f}s.")
            await asyncio.sleep(sleep_time)

# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    asyncio.run(run_bot())
