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
# KONFIGURACJA FILTRÓW (EDYTUJ WEDŁUG UZNANIA)
# ============================================================

SCAN_INTERVAL = 30          # Czas między skanami (w sekundach)
SEARCH_TEXT = "iphone"      # Szukana fraza
MAX_RESULTS = 30            # Liczba pobieranych ogłoszeń na skan

# Minimalna cena w PLN (odrzuca etui, szkła, akcesoria)
MIN_PRICE = 150.0  

# Czarna lista – odrzuca ogłoszenia zawierające poniższe słowa
EXCLUDE_KEYWORDS = [
    "etui", "case", "szkło", "szklo", "obudowa", "ładowarka", "ladowarka",
    "kabel", "pudełko", "pudelko", "box", "folia", "pokrowiec", "uchwyt",
    "szybka", "bateria", "adapter", "zaslepka", "zaślepka", "pasek", "smycz",
    "głośnik", "glosnik", "airpods", "watch", "magsafe", "pancerna", "szkiełko"
]

# ============================================================
# LOGOWANIE & FLASK (KEEP-ALIVE DLA RENDERA)
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("iphone-bot")

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot działa 24/7."

def start_web_server():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ============================================================
# LOGIKA FILTROWANIA I PRZETWARZANIA DANYCH
# ============================================================

def extract_price(price_input):
    """Wyciąga kwotę jako liczbę float z dowolnego formatu tekstu/liczby."""
    if isinstance(price_input, (int, float)):
        return float(price_input)
    clean_str = re.sub(r"[^\d.,]", "", str(price_input)).replace(",", ".")
    try:
        return float(clean_str)
    except ValueError:
        return 0.0

def is_valid_phone(title, price_val):
    """Weryfikuje czy oferta dotyczy telefonu iPhone 11-17, odrzucając akcesoria."""
    title_lower = title.lower()

    # 1. Sprawdzenie czarnej listy (etui, akcesoria)
    if any(kw in title_lower for kw in EXCLUDE_KEYWORDS):
        return False

    # 2. Sprawdzenie minimalnej ceny
    if price_val < MIN_PRICE:
        return False

    # 3. Wyłapywanie modeli iPhone 11 do 17 (np. "iphone 11", "iphone12", "iPhone 15 Pro Max")
    if not re.search(r"iphone\s*(1[1-7])", title_lower):
        return False

    return True

# ============================================================
# DISCORD WEBHOOK
# ============================================================

def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK")
    return webhook.strip() if webhook else None

async def send_discord(title, price, url, image="", source=""):
    webhook = get_webhook()
    if not webhook:
        log.error("❌ Brak ustawionego DISCORD_WEBHOOK!")
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
        def _post():
            resp = requests.post(webhook, json={"embeds": [embed]}, timeout=10)
            return resp.status_code

        status = await asyncio.to_thread(_post)
        if 200 <= status < 300:
            log.info(f"🚀 DISCORD: wysłano [{source}] {title[:35]}")
            return True
        log.error(f"❌ Discord Kod: {status}")
    except Exception as e:
        log.error(f"❌ Błąd wysyłania do Discorda: {e}")
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
        else:
            log.warning(f"⚠️ Vinted HTTP {resp.status_code}")
    except Exception as e:
        log.warning(f"⚠️ Vinted Błąd: {e}")

    return found

def _fetch_olx():
    found = []
    url = f"https://www.olx.pl/api/v1/offers/?offset=0&limit={MAX_RESULTS}&query={quote(SEARCH_TEXT)}&sort_by=created_at:desc"
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
            log.warning(f"⚠️ OLX HTTP {resp.status_code} (Cloudflare blokuje IP Rendera)")
    except Exception as e:
        log.warning(f"⚠️ OLX Błąd: {e}")

    return found

# ============================================================
# PĘTLA GŁÓWNA
# ============================================================

async def run_bot():
    if not get_webhook():
        log.error("❌ BRAK DISCORD_WEBHOOK W USTAWIENIACH RENDERA!")
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

            # Podczas pierwszego skanu tylko zapamiętujemy stare oferty – powiadomienia idą dopiero na nowe
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
            log.info(f"🟢 PIERWSZY SKAN ZAKOŃCZONY: Zapamiętano {len(known_ids)} obecnych ofert (nie wysłano ich).")
            first_scan = False
        else:
            log.info(f"🚨 WYSŁANO NOWYCH OFERT: {new_count}")

        elapsed = time.monotonic() - scan_start
        sleep_time = max(0.0, SCAN_INTERVAL - elapsed)
        log.info(f"⏱️ Skan trwał {elapsed:.1f}s. Następny za {sleep_time:.1f}s.")
        await asyncio.sleep(sleep_time)

# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    asyncio.run(run_bot())
