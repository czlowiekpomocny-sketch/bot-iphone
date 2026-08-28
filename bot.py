import os
import asyncio
import logging
import threading
import time
import json
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from flask import Flask
from playwright.async_api import async_playwright

# ============================================================
# KONFIGURACJA
# ============================================================

SCAN_INTERVAL = 15          # Czas przerwy między skanami (sekundy)
SEARCH_TEXT = "iphone"      # Szukana fraza
MAX_RESULTS = 50            # Maksymalna liczba analizowanych kart na skan
PLAYWRIGHT_TIMEOUT = 30000  # Timeout dla ładowania stron (ms)

# ============================================================
# LOGOWANIE
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("iphone-bot")

# ============================================================
# FLASK (Keep-Alive dla serwerów chmurowych)
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "iPhone Flip Bot (OLX + Vinted) działa poprawnie."

def start_web_server():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ============================================================
# DISCORD (Wbudowane urllib — zerowa zależność od aiohttp)
# ============================================================

def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK")
    return webhook.strip() if webhook else None

async def send_discord(title, price, url, image="", source=""):
    webhook = get_webhook()
    if not webhook:
        log.error("❌ Brak DISCORD_WEBHOOK w zmiennych środowiskowych.")
        return False

    color = 38550  # Zielony dla OLX / Turkusowy dla Vinted
    if source == "OLX":
        color = 23295

    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
        "url": url,
        "color": color,
        "description": f"💰 **Cena:** {price or 'Brak ceny'}\n🌐 **Źródło:** {source}",
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
            log.info(f"✅ Discord [{source}]: wysłano -> {(title or 'Ogłoszenie')[:40]}")
            return True
        log.error(f"❌ Discord odpowiedział kodem HTTP {status}")
    except Exception as e:
        log.error(f"❌ Błąd podczas wysyłania powiadomienia na Discord: {e}")
    return False

# ============================================================
# SKANER OLX
# ============================================================

async def scan_olx(page):
    found = []
    # Poprawna struktura URL OLX wykluczająca błąd 404
    url = f"https://www.olx.pl/d/oferty/q-{quote(SEARCH_TEXT)}/?search%5Border%5D=created_at:desc"

    try:
        await page.goto(url, wait_until="commit", timeout=PLAYWRIGHT_TIMEOUT)
        await asyncio.sleep(2)
        
        cookie_btn = page.locator("#onetrust-accept-btn-handler")
        if await cookie_btn.is_visible():
            await cookie_btn.click()
    except Exception as e:
        log.warning(f"⚠️ OLX lądowanie/ciasteczka: {e}")

    cards = page.locator('[data-cy="l-card"], [data-testid="l-card"]')
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

            title_elem = card.locator('h6, h4, [data-testid="ad-title"]').first
            title = await title_elem.inner_text() if await title_elem.count() > 0 else "Ogłoszenie OLX"

            price_elem = card.locator('[data-testid="ad-price"]').first
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

    log.info(f"OLX: odnaleziono {len(found)} poprawnych ofert")
    return found

# ============================================================
# SKANER VINTED
# ============================================================

async def scan_vinted(page):
    found = []
    url = f"https://www.vinted.pl/catalog?search_text={quote(SEARCH_TEXT)}&order=newest_first"

    try:
        await page.goto(url, wait_until="commit", timeout=PLAYWRIGHT_TIMEOUT)
        await asyncio.sleep(2)

        cookie_btn = page.locator('#onetrust-accept-btn-handler')
        if await cookie_btn.is_visible():
            await cookie_btn.click()
    except Exception as e:
        log.warning(f"⚠️ Vinted lądowanie/ciasteczka: {e}")

    items = page.locator('[data-testid="grid-item"]')
    item_count = await items.count()

    for i in range(min(item_count, MAX_RESULTS)):
        try:
            item = items.nth(i)
            link_elem = item.locator('a[href*="/items/"]').first
            
            if await link_elem.count() == 0:
                continue

            href = await link_elem.get_attribute("href")
            if not href:
                continue

            full_url = urljoin("https://www.vinted.pl", href).split("?")[0]

            title = await link_elem.get_attribute("title")
            if not title:
                raw_text = await item.inner_text()
                title = raw_text.split("\n")[0] if raw_text else "Ogłoszenie Vinted"

            price_elem = item.locator('[data-testid*="price"]').first
            price = await price_elem.inner_text() if await price_elem.count() > 0 else "Brak ceny"

            img_elem = item.locator("img").first
            image = ""
            if await img_elem.count() > 0:
                image = await img_elem.get_attribute("src") or await img_elem.get_attribute("data-src") or ""

            found.append({
                "source": "Vinted",
                "url": full_url,
                "title": title.strip().replace("\n", " "),
                "price": price.strip().replace("\n", " "),
                "image": image
            })
        except Exception:
            continue

    log.info(f"Vinted: odnaleziono {len(found)} poprawnych ofert")
    return found

# ============================================================
# GŁÓWNA PĘTLA BOTA
# ============================================================

async def run_bot():
    if not get_webhook():
        log.error("❌ BŁĄD: DISCORD_WEBHOOK nie jest ustawiony w Environment Variables w Renderze!")
        return

    log.info("🚀 Uruchamianie iPhone Bot (OLX + Vinted)...")

    known_urls = set()
    first_scan = True

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
            viewport={"width": 1280, "height": 720},
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        olx_page = await context.new_page()
        vinted_page = await context.new_page()

        while True:
            scan_start = time.monotonic()
            log.info("🔎 Rozpoczynam skanowanie OLX oraz Vinted...")

            results = await asyncio.gather(
                scan_olx(olx_page),
                scan_vinted(vinted_page),
                return_exceptions=True
            )

            all_offers = []
            for res in results:
                if isinstance(res, list):
                    all_offers.extend(res)
                else:
                    log.error(f"❌ Wyjątek podczas wykonywania skanu: {res}")

            new_count = 0
            for offer in all_offers:
                url = offer["url"]
                if url in known_urls:
                    continue

                known_urls.add(url)

                # Pierwszy skan ignorujemy, aby nie wysłać kilkudziesięciu starych ofert naraz
                if not first_scan:
                    new_count += 1
                    log.info(f"🆕 Nowa oferta! [{offer['source']}] {offer['title']} - {offer['price']}")
                    await send_discord(
                        title=offer["title"],
                        price=offer["price"],
                        url=url,
                        image=offer["image"],
                        source=offer["source"]
                    )
                    await asyncio.sleep(0.5)

            if first_scan:
                log.info(f"🟢 Pierwszy skan zakończony powodzeniem. Zapisano {len(known_urls)} istniejących ofert do pamięci.")
                first_scan = False
            else:
                log.info(f"📦 Zakończono skan. Wysłąno nowych powiadomień: {new_count}")

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
