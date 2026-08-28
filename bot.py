import os
import asyncio
import logging
import threading
import time
from urllib.parse import quote, urljoin

import aiohttp
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
# FLASK (Keep-Alive dla Render / Heroku)
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "iPhone Flip Bot działa."

def start_web_server():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ============================================================
# DISCORD (Asynchroniczny)
# ============================================================

def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK")
    return webhook.strip() if webhook else None

async def send_discord(session, title, price, url, image="", source=""):
    webhook = get_webhook()
    if not webhook:
        log.error("❌ Brak DISCORD_WEBHOOK.")
        return False

    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
        "url": url,
        "color": 5814783 if source == "OLX" else 65490,
        "description": f"💰 **Cena:** {price or 'Brak ceny'}\n🌐 **Źródło:** {source}",
        "footer": {"text": "iPhone Flip Bot"}
    }

    if image and image.startswith("http"):
        embed["thumbnail"] = {"url": image}

    try:
        async with session.post(webhook, json={"embeds": [embed]}, timeout=10) as resp:
            if 200 <= resp.status < 300:
                log.info(f"✅ Discord [{source}]: wysłano -> {(title or 'Ogłoszenie')[:50]}")
                return True
            log.error(f"❌ Discord HTTP {resp.status}")
    except Exception as e:
        log.error(f"❌ Błąd wysyłania Discord: {e}")
    return False

# ============================================================
# SKANER OLX
# ============================================================

async def scan_olx(page):
    found = []
    url = f"https://www.olx.pl/d/elektronika/telefony/telefony-komorkowe/q-{quote(SEARCH_TEXT)}/?search%5Border%5D=created_at:desc"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT)
        cookie_btn = page.locator("#onetrust-accept-btn-handler")
        if await cookie_btn.is_visible():
            await cookie_btn.click()
    except Exception as e:
        log.warning(f"⚠️ OLX goto/cookie: {e}")

    await asyncio.sleep(2)

    cards = page.locator('[data-cy="l-card"], [data-testid="l-card"]')
    card_count = await cards.count()
    log.info(f"OLX: odnaleziono {card_count} kart")

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

    return found

# ============================================================
# SKANER VINTED
# ============================================================

async def scan_vinted(page):
    found = []
    url = f"https://www.vinted.pl/catalog?search_text={quote(SEARCH_TEXT)}&order=newest_first"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT)
        cookie_btn = page.locator('#onetrust-accept-btn-handler')
        if await cookie_btn.is_visible():
            await cookie_btn.click()
    except Exception as e:
        log.warning(f"⚠️ Vinted goto/cookie: {e}")

    await asyncio.sleep(2)

    items = page.locator('[data-testid="grid-item"]')
    item_count = await items.count()
    log.info(f"Vinted: odnaleziono {item_count} kart")

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
                "title": title.strip(),
                "price": price.strip(),
                "image": image
            })
        except Exception:
            continue

    return found

# ============================================================
# GŁÓWNA PĘTLA BOT-A
# ============================================================

async def run_bot():
    if not get_webhook():
        log.error("❌ DISCORD_WEBHOOK nie został skonfigurowany w zmiennych środowiskowych.")
        return

    log.info("🚀 Uruchamianie iPhone Flip Bot (OLX + Vinted)...")

    known_urls = set()
    first_scan = True

    async with async_playwright() as p, aiohttp.ClientSession() as http_session:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
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
            log.info("🔎 Rozpoczynam skanowanie serwisów...")

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
                    log.error(f"❌ Błąd podczas skanowania: {res}")

            new_count = 0
            for offer in all_offers:
                url = offer["url"]
                if url in known_urls:
                    continue

                known_urls.add(url)

                if not first_scan:
                    new_count += 1
                    log.info(f"🆕 [{offer['source']}] {offer['title']} - {offer['price']}")
                    await send_discord(
                        http_session,
                        title=offer["title"],
                        price=offer["price"],
                        url=url,
                        image=offer["image"],
                        source=offer["source"]
                    )
                    await asyncio.sleep(0.5)

            if first_scan:
                log.info(f"🟢 Pierwszy skan zakończony. Zapisano {len(known_urls)} istniejących ofert.")
                first_scan = False
            else:
                log.info(f"📦 Zakończono skan. Nowych ofert: {new_count}")

            elapsed = time.monotonic() - scan_start
            sleep_time = max(0.0, SCAN_INTERVAL - elapsed)
            log.info(f"⏱️ Czas skanowania: {elapsed:.1f}s. Czekam {sleep_time:.1f}s...")
            await asyncio.sleep(sleep_time)

# ============================================================
# PUNKT WEJŚCIA PROGRAMU
# ============================================================

if __name__ == "__main__":
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    asyncio.run(run_bot())
