import os
import time
import requests
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# --- 1. SERWER HTTP DLA RENDERA (Zapobiega wyłączeniu) ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot dziala 24/7!")

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_http_server, daemon=True).start()

# --- 2. KONFIGURACJA DISCORDA ---
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1542666756592631958/XxxJ432XkJzNPYQ_JGR14dRUi1sfLXHAVjKqlKkQJNNEpKeEHofnIYAebE5st4JNfXby"

def send_discord_message(title, price, url, source):
    data = {
        "content": f"🔥 **Nowa okazja na {source}!**\n**Tytuł:** {title}\n**Cena:** {price}\n**Link:** {url}"
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
    except Exception as e:
        print(f"Błąd wysyłania na Discord: {e}")

# --- 3. SKANOWANIE PORTALI ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

def check_olx(seen_ids):
    # Przykładowy link do wyszukiwania OLX (np. iPhone)
    url = "https://www.olx.pl/elektronika/telefony/szukaj/?search%[order]=created_at:desc"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        cards = soup.find_all('div', data_cy='l-card')

        for card in cards[:5]:
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
                title_str = title.text.strip() if title else "Brak tytułu"
                
                price = card.find('p', data_testid='ad-price')
                price_str = price.text.strip() if price else "Nie podano"
                
                send_discord_message(title_str, price_str, item_url, "OLX")
    except Exception as e:
        print(f"Błąd podczas pobierania OLX: {e}")

# --- 4. GŁÓWNA PĘTLA BOTA ---
def main():
    print("Bot zostal poprawnie uruchomiony w chmurze 24/7.")
    seen_ids = set()

    # Wysłanie testowej wiadomości po starcie
    send_discord_message("Bot uruchomiony!", "0", "https://render.com", "System")

    while True:
        try:
            print("Skanowanie ofert co 15 sekund...")
            check_olx(seen_ids)
            time.sleep(15)
        except Exception as e:
            print(f"Błąd w głównej pętli: {e}")
            time.sleep(15)

if __name__ == "__main__":
    main()

