import requests
import time

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1542666756592631958/XxxJ432XkJzNPYQ_JGR14dRUi1sfLXHAVjKqlKkQJNNEpKeEHofnIYAebE5st4JNfXby"

seen_ids = set()
session = requests.Session()
first_run = True

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pl-PL,pl;q=0.9"
}

# Słowa do wykluczenia akcesoriów i śmieci
BLACK_LIST = [
    'etui', 'case', 'pokrowiec', 'szkło', 'szklo', 'szybka', 'pudełko', 'pudelko',
    'box', 'kabel', 'ładowarka', 'ladowarka', 'słuchawki', 'sluchawki', 'folia',
    'obudowa', 'pasek', 'smycz', 'klapka', 'uchwyt', 'zabezpieczające'
]

def is_valid_iphone(title, price_val):
    # Odrzucamy akcesoria poniżej 120 PLN (żaden działający iPhone/uszkodzony tyle nie kosztuje)
    if price_val < 120:
        return False
    
    title_lower = title.lower()
    for word in BLACK_LIST:
        if word in title_lower:
            return False
    return True

def send_to_discord(portal, title, price_str, link, image_url=""):
    embed = {
        "title": f"📱 {title[:250]}",
        "url": link,
        "color": 3066993,
        "fields": [
            {"name": "💰 Cena", "value": price_str, "inline": True},
            {"name": "🌐 Portal", "value": portal, "inline": True}
        ],
        "footer": {"text": "Weryfikacja: Tylko telefony iPhone"}
    }
    if image_url:
        embed["thumbnail"] = {"url": image_url}

    payload = {"embeds": [embed]}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"Błąd Discord: {e}")

def check_olx():
    url = "https://www.olx.pl/api/v1/offers/?query=iphone&sort_by=created_at:desc"
    try:
        res = session.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json().get("data", [])
            for item in data:
                item_id = f"olx_{item['id']}"
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    title = item.get("title", "iPhone")
                    link = item.get("url", "")
                    price_val = 0
                    price_str = "Brak ceny"
                    if item.get("params"):
                        for p in item["params"]:
                            if p.get("key") == "price":
                                val = p.get("value", {}).get("value")
                                if val:
                                    price_val = float(val)
                                    price_str = f"{price_val} PLN"
                    
                    # Pobieranie miniatury zdjęcia
                    img_url = ""
                    photos = item.get("photos", [])
                    if photos:
                        img_url = photos[0].get("link", "").replace("{width}", "400").replace("{height}", "400")

                    if not first_run and is_valid_iphone(title, price_val):
                        send_to_discord("OLX", title, price_str, link, img_url)
    except Exception as e:
        print(f"Błąd OLX: {e}")

def check_vinted():
    try:
        session.get("https://www.vinted.pl", headers=HEADERS, timeout=10)
        url = "https://www.vinted.pl/api/v2/catalog/items?search_text=iphone&order=newest_first"
        res = session.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            items = res.json().get("items", [])
            for item in items:
                item_id = f"vinted_{item['id']}"
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    title = item.get("title", "iPhone")
                    
                    price_val = float(item.get("price", {}).get("amount", 0))
                    price_str = f"{price_val} PLN"
                    
                    # Poprawka podwójnego adresu URL
                    raw_url = item.get("url", "")
                    link = raw_url if raw_url.startswith("http") else f"https://www.vinted.pl{raw_url}"
                    
                    # Zdjęcie
                    img_url = item.get("photo", {}).get("url", "")
                    
                    if not first_run and is_valid_iphone(title, price_val):
                        send_to_discord("VINTED", title, price_str, link, img_url)
    except Exception as e:
        print(f"Błąd Vinted: {e}")

def check_allegro():
    url = "https://allegrolokalnie.pl/api/v1/offers?phrase=iphone&sort=-created_at"
    try:
        res = session.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            offers = res.json().get("offers", [])
            for item in offers:
                item_id = f"allegro_{item.get('id')}"
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    title = item.get("title", "iPhone")
                    
                    price_val = float(item.get("price", {}).get("amount", 0))
                    price_str = f"{price_val} PLN"
                    
                    link = f"https://allegrolokalnie.pl/oferta/{item.get('slug')}"
                    img_url = item.get("primaryImage", {}).get("url", "")

                    if not first_run and is_valid_iphone(title, price_val):
                        send_to_discord("ALLEGRO LOKALNIE", title, price_str, link, img_url)
    except Exception as e:
        print(f"Błąd Allegro: {e}")

# Inicjalizacja: Zapisanie obecnych ogłoszeń bez wysyłania spamu
check_olx()
check_vinted()
check_allegro()
first_run = False
print("Filtry ustalone! Aktywne powiadomienia kartowe tylko dla telefonów iPhone.")

while True:
    check_olx()
    check_vinted()
    check_allegro()
    time.sleep(15)
