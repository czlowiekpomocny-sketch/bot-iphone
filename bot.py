import os
import time
import json
import logging
import re
import threading
import requests
import feedparser

from flask import Flask
from urllib.parse import quote

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
OLX_SEARCH_URL = os.getenv(
    "OLX_SEARCH_URL",
    "https://www.olx.pl/elektronika/telefony/q-iphone/"
)

INTERVAL = 15

MAX_PRICE = {
    11: 650,
    12: 850,
    13: 1100,
    14: 1400,
    15: 1750,
    16: 2200,
    17: 2700
}

KEYWORDS = [
    "uszkodz", "zbity", "zbita", "pęknię", "pekniet",
    "ekran", "wyświetlacz", "wyswietlacz", "bateria",
    "kondycja", "face id", "do naprawy", "na części",
    "na czesci", "nie działa", "nie dziala", "nie włącza",
    "nie wlacza", "tył", "tyl", "klapa", "back glass",
    "aparat", "dotyk", "okazja", "tanio"
]

BAD_WORDS = [
    "etui", "case", "szkło", "szklo", "folia", "kabel",
    "ładowarka", "ladowarka", "uchwyt", "pokrowiec",
    "obudowa", "szkło hartowane"
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")

app = Flask(__name__)

@app.route("/")
def home():
    return "📱 iPhone Flip Bot działa!"

@app.route("/health")
def health():
    return {"status": "ok"}

def web_server():
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000"))
    )

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9"
})

SEEN_FILE = "seen.json"

def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_seen(seen):
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(
                list(seen)[-20000:],
                f,
                ensure_ascii=False
            )
    except Exception as e:
        log.warning("seen.json: %s", e)

def parse_price(text):
    if not text:
        return None

    text = str(text)
    text = text.replace("\xa0", " ")
    text = text.replace("zł", "")
    text = text.replace("PLN", "")
    text = text.replace(" ", "")

    match = re.search(r"\d+(?:[,.]\d+)?", text)

    if not match:
        return None

    try:
        return float(
            match.group(0).replace(",", ".")
        )
    except Exception:
        return None

def get_model(title):
    title = title.lower()

    for model in range(11, 18):
        if re.search(
            rf"\biphone\s*{model}\b",
            title
        ):
            return model

    return None

def analyze(title, price):

    title_lower = title.lower()

    model = get_model(title)

    if not model:
        return None

    for bad in BAD_WORDS:
        if bad in title_lower:
            return None

    limit = MAX_PRICE[model]

    if price is not None and price > limit:
        return None

    matched = [
        word for word in KEYWORDS
        if word in title_lower
    ]

    score = 1

    if matched:
        score += min(len(matched), 5)

    if price is not None:
        if price <= limit * 0.75:
            score += 2

        if price <= limit * 0.60:
            score += 1

    return {
        "model": model,
        "limit": limit,
        "score": score,
        "matched": matched
    }

def discord(title, price, url, source, result):

    if not DISCORD_WEBHOOK_URL:
        log.error("Brak DISCORD_WEBHOOK_URL")
        return

    model = result["model"]
    limit = result["limit"]
    score = result["score"]
    matched = result["matched"]

    price_text = (
        f"{price:.0f} zł"
        if price is not None
        else "Nie podano"
    )

    color = (
        0x00FF66 if score >= 7
        else 0xFFCC00 if score >= 5
        else 0x3498DB
    )

    reason = (
        ", ".join(matched[:6])
        if matched
        else "cena poniżej limitu"
    )

    payload = {
        "username": "📱 iPhone Flip Bot",
        "embeds": [{
            "title": f"🔥 NOWY iPhone {model}",
            "description": (
                f"**{title}**\n\n"
                "🚨 **Możliwa okazja do flipowania**"
            ),
            "url": url,
            "color": color,
            "fields": [
                {
                    "name": "💰 Cena",
                    "value": f"**{price_text}**",
                    "inline": True
                },
                {
                    "name": "🎯 Limit",
                    "value": f"{limit} zł",
                    "inline": True
                },
                {
                    "name": "⭐ Ocena",
                    "value": f"**{score}/9**",
                    "inline": True
                },
                {
                    "name": "🔧 Wykryto",
                    "value": reason,
                    "inline": False
                },
                {
                    "name": "🌐 Portal",
                    "value": source,
                    "inline": True
                }
            ],
            "footer": {
                "text": "iPhone Flip Bot • sprawdź i negocjuj"
            }
        }]
    }

    try:
        r = session.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10
        )

        if r.status_code in (200, 204):
            log.info(
                "DISCORD ✓ %s | %s | %s",
                source,
                title,
                price
            )
        else:
            log.warning(
                "Discord HTTP %s",
                r.status_code
            )

    except Exception as e:
        log.warning("Discord: %s", e)

def check_olx(seen):

    try:

        rss_url = (
            "https://www.tedeelock.com/"
            "?url=" +
            quote(
                OLX_SEARCH_URL,
                safe=""
            )
        )

        r = session.get(
            rss_url,
            timeout=15
        )

        if r.status_code != 200:
            log.warning(
                "OLX RSS HTTP %s",
                r.status_code
            )
            return

        feed = feedparser.parse(
            r.content
        )

        log.info(
            "OLX → %s wyników",
            len(feed.entries)
        )

        for entry in feed.entries[:30]:

            item_id = (
                entry.get("id")
                or entry.get("link")
                or entry.get("title")
            )

            if item_id in seen:
                continue

            title = entry.get(
                "title",
                ""
            ).strip()

            url = entry.get(
                "link",
                ""
            )

            text = (
                title + " " +
                entry.get(
                    "summary",
                    ""
                )
            )

            price = parse_price(text)

            result = analyze(
                title,
                price
            )

            seen.add(item_id)

            if result:
                discord(
                    title,
                    price,
                    url,
                    "OLX",
                    result
                )

    except Exception as e:
        log.warning(
            "OLX: %s",
            e
        )

def check_vinted(seen):

    try:

        url = (
            "https://www.vinted.pl/"
            "catalog?search_text=iphone"
        )

        r = session.get(
            url,
            timeout=15
        )

        if r.status_code != 200:
            log.warning(
                "Vinted HTTP %s",
                r.status_code
            )
            return

        soup = __import__(
            "bs4"
        ).BeautifulSoup(
            r.text,
            "html.parser"
        )

        links = soup.find_all(
            "a",
            href=True
        )

        log.info(
            "Vinted → %s linków",
            len(links)
        )

        for link in links[:100]:

            title = link.get_text(
                " ",
                strip=True
            )

            href = link.get(
                "href",
                ""
            )

            if "iphone" not in title.lower():
                continue

            item_id = href

            if not item_id or item_id in seen:
                continue

            price = parse_price(
                title
            )

            result = analyze(
                title,
                price
            )

            seen.add(item_id)

            if result:

                full_url = (
                    "https://www.vinted.pl"
                    + href
                    if href.startswith("/")
                    else href
                )

                discord(
                    title,
                    price,
                    full_url,
                    "Vinted",
                    result
                )

    except Exception as e:
        log.warning(
            "Vinted: %s",
            e
        )

def main():

    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError(
            "Brak DISCORD_WEBHOOK_URL "
            "w Render Environment."
        )

    seen = load_seen()

    log.info(
        "📱 IPHONE FLIP BOT START"
    )

    log.info(
        "⏱ Sprawdzanie co %s sekund",
        INTERVAL
    )

    while True:

        start = time.time()

        check_olx(seen)
        check_vinted(seen)

        save_seen(seen)

        elapsed = time.time() - start

        wait = max(
            1,
            INTERVAL - int(elapsed)
        )

        log.info(
            "Skan zakończony → następny za %s s",
            wait
        )

        time.sleep(wait)

if __name__ == "__main__":

    threading.Thread(
        target=web_server,
        daemon=True
    ).start()

    main()
