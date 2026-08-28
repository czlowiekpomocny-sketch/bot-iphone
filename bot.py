    import os
import time
import requests
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import re

# --- 1. SERWER HTTP DLA RENDERA (24/7) ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot flip-iphone dziala 24/7!")

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_http_server, daemon=True).start()

# --- 2. KONFIGURACJA DISCORDA ---
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1542666756592631958/XxxJ432XkJzNPYQ_JGR14dRUi1sfLXHAVjKqlKkQJNNEpKeEHofnIYAebE5st4JNfXby"

def send_discord_message(title, price, url, source, reason):
    data = {
        "content": f"📱 **[FLIP OKAZJA] iPhone na {source}!**\n"
                   f"**Tytuł:** {title}\n"
                   f"**Cena:** {price}\n"
                   f"**Powód wyłapania:** {reason}\n"
                   f"**Link:** {url}"
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
    except Exception as e:
        print(f"Błąd wysyłania na Discord: {e}")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

# --- 3. LOGIKA FILTROWANIA DLA FLIPERA ---
# Modele od 11 do 17 (w tym Pro, Pro Max, Plus, mini)
TARGET_MODELS = [
    "iphone 11", "iphone 12", "iphone 13", "iphone 14", 
    "iphone 15", "iphone 16", "iphone 17"
]

# Słowa kluczowe sugerujące naprawę/dobry flip
FLIP_KEYWORDS = [
    "uszkodzony", "uszkodzona", "uszkodzone", "zbita", "zbitka", "pęknięty", "pęknięta",
    "do naprawy", "na części", "bateria", "kondycja", "face id", "ekran", "wyświetlacz",
    "klapa", "tył", "aparaty", "dotyk", "nie działa", "niedziała", "odnawiany", "okazja", "tanio"
]

def is_good_flip_candidate(title):
    title_lower = title.lower()
    
    # Check 1: Czy to iPhone od 11 do 17?
    has_model = any(model in title_lower for model in TARGET_MODELS)
    if not has_model:
        return False, ""
    
    # Check 2: Czy ma słowa kluczowe uszkodzenia/naprawy/okazji?
    matched_words = [word for word in FLIP_KEYWORDS if word in title_lower]
    if matched_words:
        return True, f"Słowa kluczowe: {', '.join(matched_words)}"
    
    # Jeśli model jest z serii 11-17, ale nie ma słów kluczowych – i tak przepuszczamy (może to być tania okazja)
    return True, "Wydłubany model iPhone 11-17"

# --- 4. PARSERY PORTALI ---

def check_olx(seen_ids):
    url = "https://www.olx.pl/elektronika/telefony/szukaj/?q=iphone&search%[order]=created_at:desc"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        cards = soup.find_all('div', data_cy='l-card')

        for card in cards[:8]:
            link_tag = card.find('a')
            if not link_tag:
                continue
            item_url = link_tag.get('href')
            if not item_url.startswith('http'):
                item_url = "https://www.olx.pl" + item_url
            
            item_id = item_url.split('/')[-1]
            if item_id not in seen_ids:
                seen_ids.add(item_id)
                title = card.find('h6')
                title_str = title.text.strip() if title else ""
                
                is_ok, reason = is_good_flip_candidate(title_str)
                if is_ok:
                    price = card.find('p', data_testid='ad-price')
                    price_str = price.text.strip() if price else "Nie podano"
                    send_discord_message(title_str, price_str, item_url, "OLX", reason)
    except Exception as e:
        print(f"Błąd OLX: {e}")

def check_vinted(seen_ids):
    url = "https://www.vinted.pl/api/v2/catalog/items?search_text=iphone&order=newest_first"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            items = data.get('items', [])
            for item in items[:8]:
                item_id = str(item.get('id'))
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    title_str = item.get('title', '')
                    
                    is_ok, reason = is_good_flip_candidate(title_str)
                    if is_ok:
                        price = f"{item.get('price', {}).get('amount', 'Nie podano')} PLN"
                        item_url = item.get('url', '')
                        send_discord_message(title_str, price, item_url, "Vinted", reason)
    except Exception as e:
        print(f"Błąd Vinted: {e}")

def check_allegro(seen_ids):
    url = "https://allegro.pl/kategoria/telefony-i-akcesoria-4254?string=iphone&order=n"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article')

        for art in articles[:8]:
            link_tag = art.find('a')
            if not link_tag:
                continue
            item_url = link_tag.get('href')
            if item_url and not item_url.startswith('http'):
                item_url = "https://allegro.pl" + item_url
                
            item_id = item_url.split('?')[0].split('-')[-1]
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                title = art.find('h2')
                title_str = title.text.strip() if title else ""
                
                is_ok, reason = is_good_flip_candidate(title_str)
                if is_ok:
                    send_discord_message(title_str, "Sprawdź cenę w linku", item_url, "Allegro", reason)
    except Exception as e:
        print(f"Błąd Allegro: {e}")

# --- 5. GŁÓWNA PĘTLA ---
def main():
    print("Bot do flippowania iPhone 11-17 uruchomiony.")
    seen_ids = set()

    while True:
        try:
            print("Skanowanie OLX, Vinted, Allegro pod kątem okazjonalnych iPhone'ów...")
            check_olx(seen_ids)
            check_vinted(seen_ids)
            check_allegro(seen_ids)
            time.sleep(15)
        except Exception as e:
            print(f"Błąd pętli: {e}")
            time.sleep(15)

if __name__ == "__main__":
    main()


