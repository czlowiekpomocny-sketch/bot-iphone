import os
import asyncio
import logging
import threading
import time
import re
from urllib.parse import quote

from flask import Flask
import requests

# ============================================================
# KONFIGURACJA FILTRÓW
# ============================================================

SCAN_INTERVAL = 30          # Czas między skanami (sekundy)
SEARCH_TEXT = "iphone"      # Szukana fraza
MAX_RESULTS = 30            # Liczba pobieranych ogłoszeń

# Minimalna cena w PLN (odrzuca akcesoria, case'y, etui)
MIN_PRICE = 150.0  

# Czarna lista słów – jeśli tytuł zawiera któreś ze słów, ogłoszenie jest odrzucane
EXCLUDE_KEYWORDS = [
    "etui", "case", "szkło", "szklo", "obudowa", "ładowarka", "ladowarka",
    "kabel", "pudełko", "pudelko", "box", "folia", "pokrowiec", "uchwyt",
    "szybka", "bateria", "adapter", "zaslepka", "zaślepka", "pasek", "smycz"
]

# Wolne akceptowane modele (możesz edytować)
MODEL_KEYWORDS = ["iphone 11", "iphone 12", "iphone 13", "iphone 14", "iphone 15", "iphone 16", "iphone 17"]

# ============================================================
# LOGOWANIE & FLASK
# ============================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("iphone-bot")

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot działa 24/7."

def start_web_server():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ============================================================
# POMOCNIKI FILTROWANIA
# ============================================================

def extract_price(price_input):
    """Wyciąga kwotę jako liczbę z dowolnego ciągu znaków/typu."""
    if isinstance(price_input, (int, float)):
        return float(price_input)
    clean_str = re.sub(r"[^\d.,]", "", str(price_input)).replace(",", ".")
    try:
        return float(clean_str)
    except ValueError:
        return 0.0

def is_valid_phone(title, price_val):
    """Sprawdza, czy oferta to prawdziwy telefon, a nie akcesorium."""
    title_lower = title.lower()

    # 1. Sprawdzanie czarnej listy
    if any(kw in title_lower for kw in EXCLUDE_KEYWORDS):
        return False

    # 2. Sprawdzanie minimalnej ceny
    if price_val < MIN_PRICE:
        return False

    # 3. Sprawdzanie czy tytuł zawiera dopasowanie do modelu
    if not any(m in title_lower for m in MODEL_KEYWORDS):
        return False

    return True

# ============================================================
# DISCORD
# ============================================================

def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK")
    return webhook.strip() if webhook else None

async def send_discord(title, price, url, image="", source=""):
    webhook = get_webhook()
    if not webhook:
        return False

    color = 23295 if source == "OLX" else 38550
    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
        "url": url,
        "color": color,
        "description": f"💰 **Cena:** {price}\n🌐 **Źródło:** {source}",
        "footer": {"text": "iPhone Notifier Bot"}
    }
    if image and image.startswith("http"):
        embed["thumbnail"] = {"url": image}

    try:
        status = await asyncio.to_thread(lambda: requests.post(webhook, json={"embeds": [embed]}, timeout=10).status_code)
        if 200 <= status < 300:
            log.info(f"🚀 DISCORD: wysłano [{source}] {title[:30]}")
            return True
    except Exception as e:
        log.error(f"❌ Błąd Discord: {e}")
    return False

# ============================================================
# SKANERY (VINTED + OLX)
# ============================================================

def _fetch_vinted():
    found = []
    url = f"https://www.vinted.pl/api/v2/catalog/items?search_text={quote(SEARCH_TEXT)}&order=newest_first&per_page={MAX_RESULTS}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9"
    }

    try:
        session = requests.Session()
        session.get("https://www.vinted.pl", headers=headers, timeout=10)
        resp = session.get(url, headers=headers, timeout=10)

        if resp.status_code == 200:
            items = resp.json().get("items", [])
            for item in items:
                item_id = str(item.get("id"))
                title = item.get("title") or "iPhone"
                raw_price = item.get("price") or item.get("total_item_price") or 0
                price_num = extract_price(raw_price)

                if not is_valid_phone(title, price_num):
                    continue

                photos = item.get("photos", [])
                image = photos[0].get("url", "") if photos else ""
                clean_url = f"https://www.vinted.pl/items/{item_id}"

                found.append({
                    "id": f"vinted_{item_id}",
                    "source": "Vinted",
                    "url": clean_url,
                    "title": title.strip(),
                    "price": f"{price_num:.0f} PLN",
                    "image": image
                })
    except Exception as e:
        log.warning(f"⚠️ Vinted błąd: {e}")

    return found

def _fetch_olx():
    found = []
    url = f"https://www.olx.pl/api/v1/offers/?offset=0&limit={MAX_RESULTS}&query={quote(SEARCH_TEXT)}&sort_by=created_at:desc"
    
    # Nagłówki udające przeglądarkę pod Cloudflare OLX
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.olx.pl/",
        "Origin": "https://www.olx.pl"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            items = resp.json().get("data", [])
            for item in items:
                item_id = str(item.get("id"))
                title = item.get("title", "iPhone")

                price_num = 0.0
                for p in item.get("params", []):
                    if p.get("key") == "price":
                        price_num = extract_price(p.get("value", {}).get("value", 0))
                        break

                if not is_valid_phone(title, price_num):
                    continue

                item_url = item.get("url", "").split("#")[0]
                photos = item.get("photos", [])
                image = photos[0].get("link", "").replace("{width}", "600").replace("{height}", "460") if photos else ""

                found.append({
                    "id": f"olx_{item_id}",
                    "source": "OLX",
                    "url": item_url,
                    "title": title.strip(),
                    "price": f"{price_num:.0f} PLN" if price_num > 0 else "Brak ceny",
                    "image": image
                })
        else:
            log.warning(f"⚠️ OLX HTTP {resp.status_code}")
    except Exception as e:
        log.warning(f"⚠️ OLX błąd: {e}")

    return found

# ============================================================
# PĘTLA GŁÓWNA
# ============================================================

async def run_bot():
    if not get_webhook():
        log.error("❌ Brak DISCORD_WEBHOOK w enviroment variables!")
        return

    known_ids = set()
    first_scan = True

    while True:
        scan_start = time.monotonic()
        log.info("🔎 Skanowanie OLX + Vinted...")

        vinted_offers = await asyncio.to_thread(_fetch_vinted)
        olx_offers = await asyncio.to_thread(_fetch_olx)

        all_offers = olx_offers + vinted_offers
        new_count = 0

        for offer in all_offers:
            offer_id = offer["id"]
            if offer_id in known_ids:
                continue

            known_ids.add(offer_id)

            if not first_scan:
                new_count += 1
                await send_discord(
                    title=offer["title"],
                    price=offer["price"],
                    url=offer["url"],
                    image=offer["image"],
                    source=offer["source"]
                )
                await asyncio.sleep(0.3)

        if first_scan:
            log.info(f"🟢 PIERWSZY SKAN: zapamiętano {len(known_ids)} unikalnych telefonów.")
            first_scan = False
        else:
            log.info(f"🚨 NOWYCH OFERT: {new_count}")

        elapsed = time.monotonic() - scan_start
        sleep_time = max(0.0, SCAN_INTERVAL - elapsed)
        await asyncio.sleep(sleep_time)

if __name__ == "__main__":
    threading.Thread(target=start_web_server, daemon=True).start()
    asyncio.run(run_bot())
