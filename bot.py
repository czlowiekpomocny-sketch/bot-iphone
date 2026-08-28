import os
import time
import json
import re
import logging
import threading
from datetime import datetime, timezone

import requests
from flask import Flask


# =========================
# CONFIG
# =========================

WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

INTERVAL = 15
SEEN_FILE = "seen.json"

OLX_URL = "https://www.olx.pl/api/v1/offers/"
VINTED_URL = "https://www.vinted.pl/api/v2/catalog/items"

MAX_PRICE = {
    11: 700,
    12: 900,
    13: 1200,
    14: 1500,
    15: 1800,
    16: 2300,
    17: 2800,
}

GOOD_WORDS = [
    "uszkodz",
    "zbity",
    "zbita",
    "pęknię",
    "pekniet",
    "ekran",
    "wyświetlacz",
    "wyswietlacz",
    "bateria",
    "kondycja",
    "face id",
    "do naprawy",
    "na części",
    "na czesci",
    "nie działa",
    "nie dziala",
    "nie włącza",
    "nie wlacza",
    "tył",
    "tyl",
    "klapa",
    "back glass",
    "aparat",
    "dotyk",
    "okazja",
    "tanio",
]

BAD_WORDS = [
    "etui",
    "case",
    "szkło",
    "szklo",
    "folia",
    "kabel",
    "ładowarka",
    "ladowarka",
    "uchwyt",
    "pokrowiec",
    "obudowa",
]


# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")


# =========================
# RENDER SERVER
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "📱 iPhone Flip Bot działa!"


@app.route("/health")
def health():
    return {"status": "ok"}


def start_server():
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


# =========================
# HTTP SESSION
# =========================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
})


# =========================
# SEEN OFFERS
# =========================

def load_seen():

    try:
        with open(
            SEEN_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            return set(json.load(f))

    except Exception:
        return set()


def save_seen(seen):

    try:
        with open(
            SEEN_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                list(seen)[-30000:],
                f
            )

    except Exception as e:
        log.warning(
            "Nie można zapisać seen.json: %s",
            e
        )


# =========================
# PRICE
# =========================

def parse_price(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)

    text = (
        text
        .replace("\xa0", " ")
        .replace("zł", "")
        .replace("PLN", "")
        .strip()
    )

    text = text.replace(" ", "")
    text = text.replace(",", ".")

    match = re.search(
        r"\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    try:
        return float(match.group(0))
    except Exception:
        return None


# =========================
# IPHONE MODEL
# =========================

def get_model(text):

    text = str(text).lower()

    for model in range(11, 18):

        if re.search(
            rf"\biphone\s*{model}\b",
            text
        ):
            return model

    return None


# =========================
# FILTER
# =========================

def analyze(title, description, price):

    text = (
        str(title)
        + " "
        + str(description)
    ).lower()

    model = get_model(text)

    if model is None:
        return None

    for bad in BAD_WORDS:

        if bad in text:
            return None

    limit = MAX_PRICE[model]

    if price is not None and price > limit:
        return None

    matched = [
        word
        for word in GOOD_WORDS
        if word in text
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


# =========================
# DISCORD
# =========================

def send_discord(
    title,
    description,
    price,
    url,
    source,
    result,
    image_url=None,
    location=""
):

    if not WEBHOOK:
        log.error(
            "Brak DISCORD_WEBHOOK_URL!"
        )
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

    if score >= 7:
        color = 0x2ECC71
    elif score >= 5:
        color = 0xF1C40F
    else:
        color = 0x3498DB

    reason = (
        ", ".join(matched[:7])
        if matched
        else "iPhone w limicie cenowym"
    )

    fields = [
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
    ]

    if location:
        fields.append({
            "name": "📍 Lokalizacja",
            "value": location[:1024],
            "inline": True
        })

    embed = {
        "title": f"🔥 NOWA OKAZJA — iPhone {model}",
        "description": (
            f"**{title[:250]}**\n\n"
            "🚨 **Oferta do sprawdzenia!**"
        ),
        "url": url,
        "color": color,
        "fields": fields,
        "footer": {
            "text": "📱 iPhone Flip Bot • OLX + Vinted"
        },
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat()
    }

    if image_url:
        embed["image"] = {
            "url": image_url
        }

    payload = {
        "username": "📱 iPhone Flip Bot",
        "embeds": [embed]
    }

    try:

        r = session.post(
            WEBHOOK,
            json=payload,
            timeout=10
        )

        if r.status_code in (200, 204):

            log.info(
                "DISCORD ✓ %s | %s | %s",
                source,
                title,
                price_text
            )

        else:

            log.warning(
                "Discord HTTP %s: %s",
                r.status_code,
                r.text[:300]
            )

    except Exception as e:

        log.warning(
            "Discord: %s",
            e
        )


# =========================
# OLX
# =========================

def check_olx(seen):

    try:

        params = {
            "offset": 0,
            "limit": 40,
            "query": "iphone",
        }

        r = session.get(
            OLX_URL,
            params=params,
            timeout=15
        )

        if r.status_code != 200:

            log.warning(
                "OLX HTTP %s",
                r.status_code
            )

            return

        data = r.json()

        offers = data.get(
            "data",
            []
        )

        log.info(
            "OLX → %s ofert",
            len(offers)
        )

        for offer in offers:

            item_id = str(
                offer.get(
                    "id",
                    ""
                )
            )

            if not item_id:
                continue

            key = "olx:" + item_id

            if key in seen:
                continue

            title = str(
                offer.get(
                    "title",
                    ""
                )
            )

            description = str(
                offer.get(
                    "description",
                    ""
                )
            )

            url = (
                offer.get("url")
                or offer.get("web_url")
                or ""
            )

            price_data = offer.get(
                "price"
            )

            if isinstance(
                price_data,
                dict
            ):
                price = parse_price(
                    price_data.get("value")
                )
            else:
                price = parse_price(
                    price_data
                )

            result = analyze(
                title,
                description,
                price
            )

            seen.add(key)

            if not result:
                continue

            image_url = None

            photos = offer.get(
                "photos",
                []
            )

            if photos:

                first = photos[0]

                if isinstance(
                    first,
                    dict
                ):
                    image_url = (
                        first.get("link")
                        or first.get("url")
                    )

                elif isinstance(
                    first,
                    str
                ):
                    image_url = first

            location = ""

            location_data = offer.get(
                "location"
            )

            if isinstance(
                location_data,
                dict
            ):

                city = location_data.get(
                    "city"
                )

                if isinstance(
                    city,
                    dict
                ):
                    city = city.get(
                        "name"
                    )

                if city:
                    location = str(city)

            send_discord(
                title,
                description,
                price,
                url,
                "OLX",
                result,
                image_url,
                location
            )

    except Exception as e:

        log.warning(
            "OLX ERROR: %s",
            e
        )


# =========================
# VINTED
# =========================

def check_vinted(seen):

    try:

        params = {
            "search_text": "iphone",
            "order": "newest_first",
            "page": 1,
            "per_page": 96
        }

        r = session.get(
            VINTED_URL,
            params=params,
            timeout=15
        )

        if r.status_code != 200:

            log.warning(
                "Vinted HTTP %s",
                r.status_code
            )

            return

        data = r.json()

        items = data.get(
            "items",
            []
        )

        log.info(
            "Vinted → %s ofert",
            len(items)
        )

        for item in items:

            item_id = str(
                item.get(
                    "id",
                    ""
                )
            )

            if not item_id:
                continue

            key = "vinted:" + item_id

            if key in seen:
                continue

            title = str(
                item.get(
                    "title",
                    ""
                )
            )

            description = str(
                item.get(
                    "description",
                    ""
                )
            )

            url = str(
                item.get(
                    "url",
                    ""
                )
            )

            price = parse_price(
                item.get("price")
            )

            result = analyze(
                title,
                description,
                price
            )

            seen.add(key)

            if not result:
                continue

            image_url = None

            photo = item.get(
                "photo"
            )

            if isinstance(
                photo,
                dict
            ):

                image_url = (
                    photo.get("url")
                    or photo.get("full_size_url")
                )

            elif isinstance(
                photo,
                str
            ):

                image_url = photo

            if not image_url:

                photos = item.get(
                    "photos",
                    []
                )

                if photos:

                    first = photos[0]

                    if isinstance(
                        first,
                        dict
                    ):

                        image_url = (
                            first.get("url")
                            or first.get(
                                "full_size_url"
                            )
                        )

            location = str(
                item.get(
                    "city",
                    ""
                )
                or ""
            )

            send_discord(
                title,
                description,
                price,
                url,
                "Vinted",
                result,
                image_url,
                location
            )

    except Exception as e:

        log.warning(
            "VINTED ERROR: %s",
            e
        )


# =========================
# MAIN
# =========================

def main():

    if not WEBHOOK:

        raise RuntimeError(
            "Brak DISCORD_WEBHOOK_URL "
            "w Render → Environment."
        )

    seen = load_seen()

    log.info(
        "📱 IPHONE FLIP BOT URUCHOMIONY"
    )

    log.info(
        "🔎 OLX + VINTED"
    )

    log.info(
        "⏱ Sprawdzanie co %s sekund",
        INTERVAL
    )

    log.info(
        "💾 Zapamiętanych ofert: %s",
        len(seen)
    )

    while True:

        start = time.time()

        try:
            check_olx(seen)
        except Exception:
            log.exception(
                "Błąd OLX"
            )

        try:
            check_vinted(seen)
        except Exception:
            log.exception(
                "Błąd Vinted"
            )

        save_seen(seen)

        elapsed = time.time() - start

        wait = max(
            1,
            INTERVAL - int(elapsed)
        )

        log.info(
            "✅ Skan zakończony → "
            "następny za %s s",
            wait
        )

        time.sleep(wait)


# =========================
# START
# =========================

if __name__ == "__main__":

    threading.Thread(
        target=start_server,
        daemon=True
    ).start()

    main()
