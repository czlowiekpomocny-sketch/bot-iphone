import os
import asyncio
import logging
import threading
import time
import json
from urllib.parse import quote

from flask import Flask
import requests

# ============================================================
# KONFIGURACJA
# ============================================================

SCAN_INTERVAL = 30          # Czas między skanami (sekundy)
SEARCH_TEXT = "iphone"      # Szukana fraza
MAX_RESULTS = 20            # Liczba ogłoszeń

# Dane Proxy z Webshare
PROXY_URL = "http://pwbtcrfb:2rurdf9s0172@p.webshare.io:80"

PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL
}

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
    return "Bot działa 24/7."

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
        log.error("❌ BRAK DISCORD_WEBHOOK w ustawieniach!")
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

    payload = {"embeds": [embed]}

    try:
        def _post():
            resp = requests.post(webhook, json=payload, timeout=10)
            return resp.status_code

        status = await asyncio.to_thread(_post)
        if 200 <= status < 300:
            log.info(f"🚀 [DISCORD SENT] [{source}] {title[:30]}")
            return True
        log.error(f"❌ Discord odpowiedział kodem: {status}")
    except Exception as e:
        log.error(f"❌ Błąd wysyłania powiadomienia na Discord: {e}")
    return False

# ============================================================
# SKANER VINTED
# ============================================================

def _fetch_vinted():
    found = []
    url = f"https://www.vinted.pl/api/v2/catalog/items?search_text={quote(SEARCH_TEXT)}&order=newest_first&per_page={MAX_RESULTS}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9"
    }

    try:
        session = requests.Session()
        session.proxies.update(PROXIES)

        # Pobieramy najpierw ciastko sesyjne z Vinted
        session.get("https://www.vinted.pl", headers=headers, timeout=10)

        # Właściwe zapytanie o przedmioty
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            for item in items:
                title = item.get("title") or "Oferta Vinted"
                price_val = item.get("price") or item.get("total_item_price") or "Brak"
                currency = item.get("currency") or "PLN"

                item_url = item.get("url") or f"https://www.vinted.pl/items/{item.get('id')}"
                photos = item.get("photos", [])
                image = photos[0].get("url", "") if photos else ""

                found.append({
                    "source": "Vinted",
                    "url": item_url.split("?")[0],
                    "title": title.strip(),
                    "price": f"{price_val} {currency}",
                    "image": image
                })
        else:
            log.warning(f"⚠️ Vinted zwrócił kod HTTP: {resp.status_code}")
    except Exception as e:
        log.warning(f"⚠️ Vinted API błąd: {e}")

    return found

# ============================================================
# SKANER OLX
# ============================================================

def _fetch_olx():
    found = []
    url = f"https://www.olx.pl/api/v1/offers/?offset=0&limit={MAX_RESULTS}&query={quote(SEARCH_TEXT)}&sort_by=created_at:desc"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    try:
        resp = requests.get(url, headers=headers, proxies=PROXIES, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", [])
            for item in items:
                title = item.get("title", "Oferta OLX")
                item_url = item.get("url")

                price = "Brak ceny"
                for p in item.get("params", []):
                    if p.get("key") == "price":
                        price = p.get("value", {}).get("label", "Brak ceny")
                        break

                photos = item.get("photos", [])
                image = photos[0].get("link", "").replace("{width}", "600").replace("{height}", "460") if photos else ""

                if item_url:
                    found.append({
                        "source": "OLX",
                        "url": item_url.split("#")[0],
                        "title": title.strip(),
                        "price": price,
                        "image": image
                    })
        else:
            log.warning(f"⚠️ OLX zwrócił kod HTTP: {resp.status_code}")
    except Exception as e:
        log.warning(f"⚠️ OLX API błąd: {e}")

    return found

# ============================================================
# PĘTLA GŁÓWNA
# ============================================================

async def run_bot():
    if not get_webhook():
        log.error("❌ BŁĄD: Brak DISCORD_WEBHOOK w ustawieniach Rendera!")
        return

    log.info("🚀 Uruchamianie bota (requests + Webshare Proxy)...")

    known_urls = set()
    first_scan = True

    while True:
        scan_start = time.monotonic()
        log.info("--------------------------------------------------")
        log.info("🔄 Skanowanie w toku...")

        vinted_offers = await asyncio.to_thread(_fetch_vinted)
        olx_offers = await asyncio.to_thread(_fetch_olx)

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
                await asyncio.sleep(0.3)

        if first_scan:
            log.info(f"🟢 Skan wstępny gotowy! OLX: {len(olx_offers)} | Vinted: {len(vinted_offers)}")
            log.info("Czekam na nowe oferty...")
            first_scan = False
        else:
            log.info(f"📦 Wysłąno nowych powiadomień: {new_count}")

        elapsed = time.monotonic() - scan_start
        sleep_time = max(0.0, SCAN_INTERVAL - elapsed)
        log.info(f"⏱️ Czas skanowania: {elapsed:.1f}s. Następne za {sleep_time:.1f}s.")
        await asyncio.sleep(sleep_time)

# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    asyncio.run(run_bot())
