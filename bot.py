import os
import asyncio
import logging
import threading
import time
from urllib.parse import quote

import requests
from flask import Flask

SCAN_INTERVAL = 30
SEARCH_TEXT = "iphone"
MAX_RESULTS = 40
MODEL_MIN = 11
MODEL_MAX = 17

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")

app = Flask(__name__)


@app.route("/")
def home():
    return "iPhone Flip Bot działa."


def start_web_server():
    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


# ============================================================
# DISCORD
# ============================================================

def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK", "")
    return webhook.strip()


def send_discord(title, price, url, image="", source=""):
    webhook = get_webhook()

    if not webhook:
        log.error("BRAK DISCORD_WEBHOOK w Render.")
        return False

    if source == "OLX":
        color = 0x00AEEF
    elif source == "Vinted":
        color = 0x6F00FF
    else:
        color = 0x808080

    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
        "url": url,
        "color": color,
        "description": (
            f"💰 **Cena:** {price or 'Brak'}\n"
            f"🌐 **Źródło:** {source}"
        ),
        "footer": {
            "text": "iPhone Flip Bot"
        }
    }

    if image and image.startswith("http"):
        embed["thumbnail"] = {
            "url": image
        }

    payload = {
        "embeds": [embed]
    }

    try:
        response = requests.post(
            webhook,
            json=payload,
            timeout=15
        )

        if 200 <= response.status_code < 300:
            log.info(
                "DISCORD: wysłano [%s] %s",
                source,
                title[:80]
            )
            return True

        log.error(
            "Discord HTTP %s: %s",
            response.status_code,
            response.text[:300]
        )

    except Exception as e:
        log.error(
            "Discord błąd: %s",
            e
        )

    return False


# ============================================================
# FILTR IPHONE 11-17
# ============================================================

def is_target_iphone(title):
    if not title:
        return False

    text = title.lower()

    text = text.replace("–", "-")
    text = text.replace("—", "-")

    for model in range(MODEL_MIN, MODEL_MAX + 1):

        if f"iphone {model}" in text:
            return True

        if f"iphone{model}" in text:
            return True

    return False


# ============================================================
# VINTED
# ============================================================

def fetch_vinted():

    found = []

    api_url = (
        "https://www.vinted.pl/api/v2/catalog/items"
        f"?search_text={quote(SEARCH_TEXT)}"
        "&order=newest_first"
        f"&per_page={MAX_RESULTS}"
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        "Referer": "https://www.vinted.pl/"
    }

    try:

        session = requests.Session()

        session.get(
            "https://www.vinted.pl/",
            headers=headers,
            timeout=15
        )

        response = session.get(
            api_url,
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:

            log.warning(
                "Vinted HTTP %s",
                response.status_code
            )

            return found

        data = response.json()

        items = data.get("items", [])

        log.info(
            "Vinted: API zwróciło %s elementów",
            len(items)
        )

        for item in items:

            title = (
                item.get("title")
                or "Oferta Vinted"
            ).strip()

            if not is_target_iphone(title):
                continue

            item_id = item.get("id")

            item_url = item.get("url")

            if not item_url and item_id:
                item_url = (
                    f"https://www.vinted.pl/items/{item_id}"
                )

            if not item_url:
                continue

            price = item.get("price")

            price_text = "Brak ceny"

            if isinstance(price, dict):

                amount = (
                    price.get("amount")
                    or price.get("value")
                )

                currency = (
                    price.get("currency_code")
                    or price.get("currency")
                    or "PLN"
                )

                if amount is not None:
                    price_text = (
                        f"{amount} {currency}"
                    )

            elif price:

                currency = (
                    item.get("currency")
                    or "PLN"
                )

                price_text = (
                    f"{price} {currency}"
                )

            photos = item.get("photos") or []

            image = ""

            if photos and isinstance(
                photos[0],
                dict
            ):

                image = (
                    photos[0].get("url")
                    or photos[0].get("full_size_url")
                    or ""
                )

            found.append(
                {
                    "source": "Vinted",
                    "url": item_url.split("?")[0],
                    "title": title,
                    "price": price_text,
                    "image": image
                }
            )

    except Exception as e:

        log.warning(
            "Vinted błąd: %s",
            e
        )

    log.info(
        "Vinted: znaleziono %s iPhone 11-17",
        len(found)
    )

    return found


# ============================================================
# OLX
# ============================================================

def fetch_olx():

    found = []

    api_url = (
        "https://www.olx.pl/api/v1/offers/"
        f"?offset=0"
        f"&limit={MAX_RESULTS}"
        f"&query={quote(SEARCH_TEXT)}"
        "&sort_by=created_at:desc"
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        "Referer": "https://www.olx.pl/"
    }

    try:

        response = requests.get(
            api_url,
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:

            log.warning(
                "OLX HTTP %s",
                response.status_code
            )

            return found

        data = response.json()

        items = data.get("data", [])

        log.info(
            "OLX: API zwróciło %s elementów",
            len(items)
        )

        for item in items:

            title = (
                item.get("title")
                or "Oferta OLX"
            ).strip()

            if not is_target_iphone(title):
                continue

            item_url = item.get("url")

            if not item_url:
                continue

            price = "Brak ceny"

            for param in item.get(
                "params",
                []
            ) or []:

                if param.get("key") == "price":

                    value = (
                        param.get("value")
                        or {}
                    )

                    if isinstance(
                        value,
                        dict
                    ):

                        price = (
                            value.get("label")
                            or value.get("value")
                            or price
                        )

                    else:

                        price = str(value)

                    break

            photos = item.get(
                "photos"
            ) or []

            image = ""

            if photos and isinstance(
                photos[0],
                dict
            ):

                image = (
                    photos[0].get("link")
                    or ""
                )

                image = image.replace(
                    "{width}",
                    "600"
                )

                image = image.replace(
                    "{height}",
                    "460"
                )

            found.append(
                {
                    "source": "OLX",
                    "url": item_url.split("#")[0],
                    "title": title,
                    "price": price,
                    "image": image
                }
            )

    except Exception as e:

        log.warning(
            "OLX błąd: %s",
            e
        )

    log.info(
        "OLX: znaleziono %s iPhone 11-17",
        len(found)
    )

    return found


# ============================================================
# JEDEN SKAN
# ============================================================

async def scan_once():

    log.info(
        "=============================================="
    )

    log.info(
        "🔎 ROZPOCZYNAM SKAN OLX + VINTED"
    )

    log.info(
        "🔎 Szukam: %s",
        SEARCH_TEXT
    )

    olx_task = asyncio.to_thread(
        fetch_olx
    )

    vinted_task = asyncio.to_thread(
        fetch_vinted
    )

    olx_offers, vinted_offers = await asyncio.gather(
        olx_task,
        vinted_task
    )

    unique = {}

    for offer in olx_offers + vinted_offers:

        url = offer.get("url")

        if url:
            unique[url] = offer

    offers = list(
        unique.values()
    )

    log.info(
        "📦 ŁĄCZNIE: %s | OLX: %s | Vinted: %s",
        len(offers),
        len(olx_offers),
        len(vinted_offers)
    )

    return offers


# ============================================================
# GŁÓWNA PĘTLA
# ============================================================

async def run_bot():

    webhook = get_webhook()

    if not webhook:

        log.error(
            "BRAK DISCORD_WEBHOOK."
        )

        log.error(
            "Render -> Environment -> DISCORD_WEBHOOK"
        )

        return

    log.info(
        "=============================================="
    )

    log.info(
        "📱 IPHONE FLIP BOT"
    )

    log.info(
        "🔎 WSPÓLNE WYSZUKIWANIE: IPHONE"
    )

    log.info(
        "📱 MODELE: IPHONE 11-17"
    )

    log.info(
        "⏱️ SKAN CO %s SEKUND",
        SCAN_INTERVAL
    )

    log.info(
        "🚫 BEZ PROXY"
    )

    log.info(
        "=============================================="
    )

    # Jedna wiadomość testowa na uruchomienie procesu.
    send_discord(
        title="🤖 Bot uruchomiony",
        price="—",
        url="https://www.olx.pl/",
        source="SYSTEM"
    )

    known_urls = set()

    first_scan = True

    while True:

        scan_started = time.monotonic()

        try:

            offers = await scan_once()

            new_offers = []

            for offer in offers:

                url = offer["url"]

                if url in known_urls:
                    continue

                known_urls.add(url)

                if not first_scan:
                    new_offers.append(
                        offer
                    )

            if first_scan:

                first_scan = False

                log.info(
                    "🟢 PIERWSZY SKAN: zapamiętano %s ofert.",
                    len(known_urls)
                )

                log.info(
                    "🟢 Istniejące oferty NIE zostaną wysłane."
                )

            else:

                log.info(
                    "🚨 NOWYCH OFERT: %s",
                    len(new_offers)
                )

                for offer in new_offers:

                    send_discord(
                        title=offer["title"],
                        price=offer["price"],
                        url=offer["url"],
                        image=offer["image"],
                        source=offer["source"]
                    )

                    await asyncio.sleep(
                        0.5
                    )

        except Exception as e:

            log.exception(
                "❌ Błąd głównej pętli: %s",
                e
            )

        elapsed = (
            time.monotonic()
            - scan_started
        )

        sleep_time = max(
            0.0,
            SCAN_INTERVAL - elapsed
        )

        log.info(
            "⏱️ Skan trwał %.1fs. Następny skan za %.1fs.",
            elapsed,
            sleep_time
        )

        await asyncio.sleep(
            sleep_time
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    asyncio.run(
        run_bot()
    )
