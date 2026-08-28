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

SCAN_INTERVAL = 20          # Czas przerwy między skanami (sekundy)
SEARCH_TEXT = "iphone"      # Wyszukiwana fraza
MAX_RESULTS = 40            # Maksymalna liczba ogłoszeń na skan
PLAYWRIGHT_TIMEOUT = 25000  # Czas oczekiwania (ms)

# ============================================================
# LOGOWANIE
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("iphone-bot")

# ============================================================
# FLASK (Keep-Alive dla Rendera)
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "iPhone Bot (OLX + Vinted Playwright-API) działa."

def start_web_server():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ============================================================
# DISCORD (Wysyłanie powiadomień)
# ============================================================

def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK")
    return webhook.strip() if webhook else None

async def send_discord(title, price, url, image="", source=""):
    webhook = get_webhook()
    if not webhook:
        log.error("❌ Brak DISCORD_WEBHOOK w zmiennych środowiskowych.")
        return False

    color = 23295 if source == "OLX" else 38550

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
        log.error(f"❌ Discord HTTP {status}")
    except Exception as e:
        log.error(f"❌ Błąd wysyłania powiadomienia na Discord: {e}")
    return False

# ============================================================
# SKANER OLX (Playwright DOM)
# ============================================================

async def scan_olx(page):
    found = []
    url = f"https://www.olx.pl/d/oferty/q-{quote(SEARCH_TEXT)}/?search%5Border%5D=created_at:desc"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT)
        await asyncio.sleep(1.5)
        
        cookie_btn = page.locator("#onetrust-accept-btn-handler")
        if await cookie_btn.is_visible():
            await cookie_btn.click()
    except Exception as e:
        log.warning(f"⚠️ OLX lądowanie: {e}")

    try:
        await page.evaluate("window.scrollBy(0, 400)")
        await asyncio.sleep(0.5)
    except Exception:
        pass

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
            title = await title_elem.inner_text() if await title_elem.count() > 0 else "Ogłoszenie OLX"

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

    log.info(f"OLX: odnaleziono {len(found)} poprawnych ofert")
    return found

# ============================================================
# SKANER VINTED (Playwright Fetch - Zweryfikowana Sesja)
# ============================================================

async def init_vinted_session(page):
    """Jednorazowe pobranie ciasteczek sesyjnych dla Vinted"""
    try:
        log.info("Inicjalizacja sesji Vinted...")
        await page.goto("https://www.vinted.pl", wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT)
        await asyncio.sleep(2)
        cookie_btn = page.locator('#onetrust-accept-btn-handler')
        if await cookie_btn.is_visible():
            await cookie_btn.click()
    except Exception as e:
        log.warning(f"⚠️ Inicjalizacja Vinted: {e}")

async def scan_vinted(page):
    found = []
    api_url = f"https://www.vinted.pl/api/v2/catalog/items?search_text={quote(SEARCH_TEXT)}&order=newest_first&per_page={MAX_RESULTS}"

    try:
        # Wykonujemy strzał do API WNTĄTRZ sesji przeglądarki (omija 403 Forbidden)
        response_data = await page.evaluate(f"""
            async () => {{
                try {{
                    const res = await fetch("{api_url}", {{
                        headers: {{
                            "Accept": "application/json, text/plain, */*"
                        }}
                    }});
                    if (!res.ok) return {{ error: res.status }};
                    return await res.json();
                }} catch (e) {{
                    return {{ error: e.toString() }};
                }}
            }}
        """)

        if "error" in response_data:
            log.warning(f"⚠️ Vinted API odpowiedział błędem: {response_data['error']}")
            return []

        items = response_data.get("items", [])
        for item in items:
            title = item.get("title") or "Ogłoszenie Vinted"
            price_val = item.get("price") or item.get("total_item_price") or "Brak ceny"
            currency = item.get("currency") or "PLN"
            price_str = f"{price_val} {currency}"

            url = item.get("url")
            if not url:
                item_id = item.get("id")
                url = f"https://www.vinted.pl/items/{item_id}"

            photos = item.get("photos", [])
            image = photos[0].get("url", "") if photos else ""

            found.append({
                "source": "Vinted",
                "url": url.split("?")[0],
                "title": title.strip().replace("\n", " "),
                "price": price_str,
                "image": image
            })

    except Exception as e:
        log.warning(f"⚠️ Vinted skanowanie: {e}")

    log.info(f"Vinted: odnaleziono {len(found)} poprawnych ofert")
    return found

# ============================================================
# GŁÓWNA PĘTLA BOTA
# ============================================================

async def run_bot():
    if not get_webhook():
        log.error("❌ BŁĄD: DISCORD_WEBHOOK nie jest ustawiony w Environment Variables na Renderze!")
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
            viewport={"width": 1366, "height": 768},
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        olx_page = await context.new_page()
        vinted_page = await context.new_page()

        # Inicjalizacja ciasteczek dla Vinted przed pierwszą pętlą
        await init_vinted_session(vinted_page)

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
                    log.error(f"❌ Błąd skanowania: {res}")

            new_count = 0
            for offer in all_offers:
                url = offer["url"]
                if url in known_urls:
                    continue

                known_urls.add(url)

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
                log.info(f"🟢 Pierwszy skan zakończony. Zapisano {len(known_urls)} istniejących ofert.")
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
