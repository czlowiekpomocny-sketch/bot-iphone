import os
import re
import json
import time
import logging
import threading
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask


# ============================================================
# USTAWIENIA
# ============================================================

# Wklej tutaj WEBHOOK DISCORDA.
# Później najlepiej przenieść go do Render → Environment.
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1542666756592631958/XxxJ432XkJzNPYQ_JGR14dRUi1sfLXHAVjKqlKkQJNNEpKeEHofnIYAebE5st4JNfXby"
)

CHECK_INTERVAL = 15
MAX_ITEMS_PER_SITE = 30


# Maksymalna cena, przy której bot zainteresuje się ofertą.
# Nie są to ceny sprzedaży — tylko orientacyjny limit zakupu.
MAX_PRICE = {
    11: 650,
    12: 850,
    13: 1100,
    14: 1400,
    15: 1750,
    16: 2200,
    17: 2700,
}


# ============================================================
# SŁOWA KLUCZOWE
# ============================================================

GOOD_WORDS = [
    "uszkodzony",
    "uszkodzona",
    "uszkodzone",
    "zbity",
    "zbita",
    "zbite",
    "pęknięty",
    "pęknięta",
    "pęknięte",
    "ekran",
    "wyświetlacz",
    "wyswietlacz",
    "bateria",
    "kondycja baterii",
    "face id",
    "do naprawy",
    "na części",
    "na czesci",
    "nie działa",
    "nie dziala",
    "nie włącza się",
    "nie wlacza sie",
    "tył",
    "tyl",
    "klapa",
    "back glass",
    "aparat",
    "aparaty",
    "dotyk",
    "okazja",
    "tanio",
    "pilnie",
]


# Akcesoria, których nie chcemy.
BAD_WORDS = [
    "etui",
    "case",
    "szkło",
    "szklo",
    "folia",
    "uchwyt",
    "kabel",
    "ładowarka",
    "ladowarka",
    "adapter",
    "słuchawki",
    "sluchawki",
    "obudowa",
    "pokrowiec",
    "zamiennik",
    "atrapa",
]


# ============================================================
# LOGI
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-flip-bot")


# ============================================================
# SERWER DLA RENDERA
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "📱 iPhone Flip Bot działa!"


@app.route("/health")
def health():
    return {"status": "ok"}


def run_web_server():
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


# ============================================================
# REQUESTS
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
})


def get_page(url):

    try:

        response = session.get(
            url,
            timeout=12
        )

        if response.status_code != 200:

            log.warning(
                "HTTP %s → %s",
                response.status_code,
                url
            )

            return None

        return response

    except requests.RequestException as error:

        log.warning(
            "Błąd połączenia: %s",
            error
        )

        return None


# ============================================================
# ZAPIS WIDZIANYCH OGŁOSZEŃ
# ============================================================

SEEN_FILE = Path("seen.json")


def load_seen():

    try:

        if SEEN_FILE.exists():

            with open(
                SEEN_FILE,
                "r",
                encoding="utf-8"
            ) as file:

                data = json.load(file)

                if isinstance(data, list):
                    return set(data)

    except Exception as error:

        log.warning(
            "Błąd odczytu seen.json: %s",
            error
        )

    return set()


def save_seen(seen):

    try:

        # Maksymalnie 20 000 ostatnich ID.
        data = list(seen)[-20000:]

        with open(
            SEEN_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False
            )

    except Exception as error:

        log.warning(
            "Błąd zapisu seen.json: %s",
            error
        )


# ============================================================
# CENA
# ============================================================

def parse_price(value):

    if value is None:
        return None

    text = str(value)

    text = (
        text
        .replace("\xa0", " ")
        .replace("zł", "")
        .replace("PLN", "")
    )

    # 1 299 → 1299
    text = re.sub(
        r"(\d)\s+(\d)",
        r"\1\2",
        text
    )

    match = re.search(
        r"\d+(?:[,.]\d{1,2})?",
        text
    )

    if not match:
        return None

    try:

        return float(
            match.group(0).replace(",", ".")
        )

    except ValueError:

        return None


# ============================================================
# MODEL IPHONE
# ============================================================

def get_model(title):

    title_lower = title.lower()

    for model in range(11, 18):

        pattern = rf"\biphone\s*{model}\b"

        if re.search(
            pattern,
            title_lower
        ):

            return model

    return None


# ============================================================
# OCENA OFERTY
# ============================================================

def analyze_offer(title, price):

    title_lower = title.lower()

    model = get_model(title)

    if model is None:
        return None

    # Nie interesują nas akcesoria.
    for bad_word in BAD_WORDS:

        if bad_word in title_lower:
            return None

    limit = MAX_PRICE[model]

    # Jeżeli cena jest znana i przekracza limit,
    # ignorujemy ofertę.
    if price is not None and price > limit:
        return None

    matched_words = [
        word
        for word in GOOD_WORDS
        if word in title_lower
    ]

    score = 1

    # Cena atrakcyjna względem limitu.
    if price is not None:

        if price <= limit * 0.75:
            score += 2

        if price <= limit * 0.60:
            score += 2

    # Uszkodzenia / naprawa.
    if matched_words:

        score += min(
            len(matched_words),
            4
        )

    if matched_words:

        reason = ", ".join(
            matched_words[:6]
        )

    else:

        reason = (
            "cena poniżej ustawionego limitu"
        )

    return {
        "model": model,
        "limit": limit,
        "score": score,
        "reason": reason,
    }


# ============================================================
# DISCORD
# ============================================================

def send_discord(
    title,
    price,
    url,
    source,
    analysis
):

    if not DISCORD_WEBHOOK_URL:

        log.error(
            "Brak DISCORD_WEBHOOK_URL!"
        )

        return

    model = analysis["model"]
    limit = analysis["limit"]
    score = analysis["score"]
    reason = analysis["reason"]

    if price is None:

        price_text = "Nie podano"

    else:

        price_text = f"{price:.2f} zł"

    # Kolor embeda.
    if score >= 7:

        color = 0x00FF66

    elif score >= 5:

        color = 0xFFCC00

    else:

        color = 0x3498DB

    embed = {
        "title": f"📱 NOWA OKAZJA — iPhone {model}",

        "description": (
            f"**{title}**\n\n"
            "🔥 **Oferta spełnia ustawione kryteria.**"
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
            },

        ],

        "footer": {
            "text": (
                "iPhone Flip Bot • "
                "sprawdź ofertę i negocjuj"
            )
        }
    }

    payload = {
        "username": "📱 iPhone Flip Bot",
        "embeds": [embed]
    }

    try:

        response = session.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10
        )

        if response.status_code in (200, 204):

            log.info(
                "Discord ✓ %s | %s | %s zł",
                source,
                title,
                price
            )

        else:

            log.warning(
                "Discord HTTP %s: %s",
                response.status_code,
                response.text[:300]
            )

    except requests.RequestException as error:

        log.warning(
            "Discord error: %s",
            error
        )


# ============================================================
# OLX
# ============================================================

def check_olx(seen):

    url = (
        "https://www.olx.pl/elektronika/telefony/"
        "?q=iphone"
        "&search%5Border%5D=created_at:desc"
    )

    response = get_page(url)

    if not response:
        return

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    cards = soup.select(
        '[data-cy="l-card"],'
        '[data-testid="l-card"]'
    )

    log.info(
        "OLX → znaleziono %s ofert",
        len(cards)
    )

    for card in cards[:MAX_ITEMS_PER_SITE]:

        link = card.find(
            "a",
            href=True
        )

        if not link:
            continue

        item_url = urljoin(
            "https://www.olx.pl",
            link["href"]
        )

        item_id = (
            item_url
            .split("?")[0]
            .rstrip("/")
            .split("/")[-1]
        )

        if not item_id:
            continue

        if item_id in seen:
            continue

        title_element = (
            card.find("h6")
            or card.find("h5")
            or card.find("h4")
            or card.find("h3")
        )

        title = (
            title_element.get_text(
                " ",
                strip=True
            )
            if title_element
            else ""
        )

        if not title:
            continue

        price_element = (
            card.select_one(
                '[data-testid="ad-price"]'
            )
            or card.select_one(
                '[data-cy="ad-price"]'
            )
        )

        price = parse_price(
            price_element.get_text(
                " ",
                strip=True
            )
            if price_element
            else None
        )

        seen.add(item_id)

        analysis = analyze_offer(
            title,
            price
        )

        if analysis:

            send_discord(
                title,
                price,
                item_url,
                "OLX",
                analysis
            )


# ============================================================
# VINTED
# ============================================================

def check_vinted(seen):

    url = (
        "https://www.vinted.pl/api/v2/catalog/items"
        "?search_text=iphone"
        "&order=newest_first"
        "&per_page=30"
    )

    response = get_page(url)

    if not response:
        return

    try:

        data = response.json()

    except ValueError:

        log.warning(
            "Vinted nie zwrócił JSON."
        )

        return

    items = data.get(
        "items",
        []
    )

    log.info(
        "Vinted → znaleziono %s ofert",
        len(items)
    )

    for item in items[:MAX_ITEMS_PER_SITE]:

        item_id = str(
            item.get(
                "id",
                ""
            )
        )

        if not item_id:
            continue

        if item_id in seen:
            continue

        title = item.get(
            "title",
            ""
        )

        price_data = item.get(
            "price",
            {}
        )

        price = parse_price(
            price_data.get(
                "amount"
            )
        )

        item_url = item.get(
            "url",
            ""
        )

        if item_url:

            item_url = urljoin(
                "https://www.vinted.pl",
                item_url
            )

        seen.add(item_id)

        analysis = analyze_offer(
            title,
            price
        )

        if analysis:

            send_discord(
                title,
                price,
                item_url,
                "Vinted",
                analysis
            )


# ============================================================
# ALLEGRO
# ============================================================

def check_allegro(seen):

    url = (
        "https://allegro.pl/listing"
        "?string=iphone"
        "&order=n"
    )

    response = get_page(url)

    if not response:
        return

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    articles = soup.find_all(
        "article"
    )

    log.info(
        "Allegro → znaleziono %s elementów",
        len(articles)
    )

    for article in articles[:MAX_ITEMS_PER_SITE]:

        link = article.find(
            "a",
            href=True
        )

        if not link:
            continue

        item_url = urljoin(
            "https://allegro.pl",
            link["href"]
        )

        clean_url = item_url.split("?")[0]

        item_id = (
            clean_url
            .rstrip("/")
            .split("/")[-1]
        )

        if not item_id:
            continue

        if item_id in seen:
            continue

        title_element = (
            article.find("h2")
            or article.find("h3")
        )

        title = (
            title_element.get_text(
                " ",
                strip=True
            )
            if title_element
            else ""
        )

        if not title:
            continue

        article_text = article.get_text(
            " ",
            strip=True
        )

        price_match = re.search(
            r"\d[\d\s,.]*\s*(?:zł|PLN)",
            article_text
        )

        price = parse_price(
            price_match.group(0)
            if price_match
            else None
        )

        seen.add(item_id)

        analysis = analyze_offer(
            title,
            price
        )

        if analysis:

            send_discord(
                title,
                price,
                clean_url,
                "Allegro",
                analysis
            )


# ============================================================
# GŁÓWNA PĘTLA
# ============================================================

def main():

    if (
        not DISCORD_WEBHOOK_URL
        or DISCORD_WEBHOOK_URL
        == "WKLEJ_TUTAJ_SWÓJ_WEBHOOK"
    ):

        raise RuntimeError(
            "Wklej webhook Discorda do "
            "DISCORD_WEBHOOK_URL."
        )

    seen = load_seen()

    log.info(
        "======================================"
    )

    log.info(
        "📱 IPHONE FLIP BOT START"
    )

    log.info(
        "⏱ Odświeżanie: %s sekund",
        CHECK_INTERVAL
    )

    log.info(
        "📦 Zapamiętanych ofert: %s",
        len(seen)
    )

    log.info(
        "======================================"
    )

    while True:

        started = time.time()

        # OLX
        try:

            check_olx(seen)

        except Exception:

            log.exception(
                "Błąd OLX"
            )

        # Vinted
        try:

            check_vinted(seen)

        except Exception:

            log.exception(
                "Błąd Vinted"
            )

        # Allegro
        try:

            check_allegro(seen)

        except Exception:

            log.exception(
                "Błąd Allegro"
            )

        save_seen(seen)

        elapsed = time.time() - started

        wait = max(
            1,
            CHECK_INTERVAL - int(elapsed)
        )

        log.info(
            "Skan zakończony w %.1fs. "
            "Następny za %ss.",
            elapsed,
            wait
        )

        time.sleep(wait)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    main()
