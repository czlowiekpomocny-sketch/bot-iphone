python
import os
import asyncio
import logging
import threading
import time
from urllib.parse import quote

import requests
from flask import Flask


# ============================================================
# KONFIGURACJA
# ============================================================

SCAN_INTERVAL = 30
SEARCH_TEXT = "iphone"
MAX_RESULTS = 40

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


# ============================================================
# LOGOWANIE
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("iphone-bot")


# ============================================================
# FLASK / RENDER KEEP-ALIVE
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "iPhone bot działa."


def start_web_server():
    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


# ============================================================
# DISCORD
# ============================================================

def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK")

    if not webhook:
        return None

    return webhook.strip()


async def send_discord(
    title,
    price,
    url,
    image="",
    source="",
):
    webhook = get_webhook()

    if not webhook:
        log.error("❌ Brak DISCORD_WEBHOOK w Render Environment Variables.")
        return False

    color = 0x5865F2 if source == "OLX" else 0x09B1BA

    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
        "url": url,
        "color": color,
        "description": (
            f"💰 **Cena:** {price or 'Brak ceny'}\n"
            f"🌐 **Źródło:** {source}"
        ),
        "footer": {
            "text": "iPhone Flip Bot"
        },
    }

    if image and image.startswith("http"):
        embed["thumbnail"] = {
            "url": image
        }

    payload = {
        "embeds": [embed]
    }

    def post():
        return requests.post(
            webhook,
            json=payload,
            timeout=15,
        )

    try:
        response = await asyncio.to_thread(post)

        if 200 <= response.status_code < 300:
            log.info(
                "📩 Discord: wysłano [%s] %s",
                source,
                (title or "")[:50],
            )
            return True

        log.error(
            "❌ Discord HTTP %s: %s",
            response.status_code,
            response.text[:300],
        )

    except Exception as exc:
        log.error(
            "❌ Błąd Discord: %s",
            exc,
        )

    return False


# ============================================================
# WSPÓLNE HEADERS
# ============================================================

def get_headers(referer):
    return {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        "Referer": referer,
        "Connection": "keep-alive",
    }


# ============================================================
# VINTED
# ============================================================

def fetch_vinted():
    offers = []

    api_url = (
        "https://www.vinted.pl/api/v2/catalog/items"
        f"?search_text={quote(SEARCH_TEXT)}"
        "&order=newest_first"
        f"&per_page={MAX_RESULTS}"
        "&page=1"
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        "Referer": (
            "https://www.vinted.pl/catalog"
            "?search_text=iphone&order=newest_first"
        ),
    }

    session = requests.Session()

    try:
        log.info("🟣 Vinted: pobieram najnowsze oferty...")

        # Najpierw odwiedzamy stronę główną,
        # żeby dostać podstawowe cookies.
        try:
            session.get(
                "https://www.vinted.pl/",
                headers=headers,
                timeout=15,
            )
        except Exception as exc:
            log.warning(
                "⚠️ Vinted strona główna: %s",
                exc,
            )

        response = session.get(
            api_url,
            headers=headers,
            timeout=20,
        )

        log.info(
            "Vinted HTTP: %s",
            response.status_code,
        )

        if response.status_code != 200:
            log.warning(
                "⚠️ Vinted nie zwrócił 200. "
                "HTTP=%s",
                response.status_code,
            )
            return offers

        try:
            data = response.json()
        except Exception as exc:
            log.warning(
                "⚠️ Vinted nie zwrócił JSON: %s",
                exc,
            )
            return offers

        items = data.get("items", [])

        log.info(
            "Vinted: API zwróciło %s elementów",
            len(items),
        )

        for item in items:
            try:
                item_id = item.get("id")

                title = (
                    item.get("title")
                    or "iPhone - Vinted"
                ).strip()

                price = (
                    item.get("price")
                    or item.get("total_item_price")
                    or "Brak ceny"
                )

                currency = (
                    item.get("currency")
                    or "PLN"
                )

                item_url = item.get("url")

                if not item_url and item_id:
                    item_url = (
                        f"https://www.vinted.pl/items/{item_id}"
                    )

                if not item_url:
                    continue

                image = ""

                photos = item.get("photos") or []

                if photos:
                    first_photo = photos[0]

                    if isinstance(first_photo, dict):
                        image = (
                            first_photo.get("url")
                            or first_photo.get("full_size_url")
                            or ""
                        )

                offers.append(
                    {
                        "source": "Vinted",
                        "id": str(item_id or item_url),
                        "url": item_url.split("?")[0],
                        "title": title,
                        "price": f"{price} {currency}",
                        "image": image,
                    }
                )

            except Exception as exc:
                log.warning(
                    "⚠️ Błąd parsowania oferty Vinted: %s",
                    exc,
                )

    except requests.RequestException as exc:
        log.warning(
            "⚠️ Vinted request error: %s",
            exc,
        )

    except Exception as exc:
        log.exception(
            "⚠️ Vinted nieoczekiwany błąd: %s",
            exc,
        )

    log.info(
        "🟣 Vinted: znaleziono %s poprawnych ofert",
        len(offers),
    )

    return offers


# ============================================================
# OLX
# ============================================================

def fetch_olx():
    offers = []

    api_url = (
        "https://www.olx.pl/api/v1/offers/"
        f"?offset=0"
        f"&limit={MAX_RESULTS}"
        f"&query={quote(SEARCH_TEXT)}"
        "&sort_by=created_at%3Adesc"
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        "Referer": (
            "https://www.olx.pl/"
            f"oferty/q-{quote(SEARCH_TEXT)}/"
        ),
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        log.info("🔵 OLX: pobieram najnowsze oferty...")

        response = requests.get(
            api_url,
            headers=headers,
            timeout=20,
        )

        log.info(
            "OLX HTTP: %s",
            response.status_code,
        )

        if response.status_code != 200:
            log.warning(
                "⚠️ OLX nie zwrócił 200. HTTP=%s",
                response.status_code,
            )
            return offers

        try:
            data = response.json()
        except Exception as exc:
            log.warning(
                "⚠️ OLX nie zwrócił JSON: %s",
                exc,
            )
            return offers

        items = data.get("data", [])

        log.info(
            "OLX: API zwróciło %s elementów",
            len(items),
        )

        for item in items:
            try:
                item_id = item.get("id")

                title = (
                    item.get("title")
                    or "iPhone - OLX"
                ).strip()

                item_url = item.get("url")

                if not item_url and item_id:
                    item_url = (
                        f"https://www.olx.pl/d/oferta/{item_id}/"
                    )

                if not item_url:
                    continue

                price = "Brak ceny"

                for param in item.get("params", []):
                    if param.get("key") == "price":
                        value = param.get("value")

                        if isinstance(value, dict):
                            price = (
                                value.get("label")
                                or value.get("value")
                                or "Brak ceny"
                            )
                        elif value:
                            price = str(value)

                        break

                image = ""

                photos = item.get("photos") or []

                if photos:
                    first_photo = photos[0]

                    if isinstance(first_photo, dict):
                        image = (
                            first_photo.get("link")
                            or first_photo.get("url")
                            or ""
                        )

                        image = (
                            image
                            .replace("{width}", "600")
                            .replace("{height}", "460")
                        )

                offers.append(
                    {
                        "source": "OLX",
                        "id": str(item_id or item_url),
                        "url": item_url.split("#")[0],
                        "title": title,
                        "price": str(price),
                        "image": image,
                    }
                )

            except Exception as exc:
                log.warning(
                    "⚠️ Błąd parsowania oferty OLX: %s",
                    exc,
                )

    except requests.RequestException as exc:
        log.warning(
            "⚠️ OLX request error: %s",
            exc,
        )

    except Exception as exc:
        log.exception(
            "⚠️ OLX nieoczekiwany błąd: %s",
            exc,
        )

    log.info(
        "🔵 OLX: znaleziono %s poprawnych ofert",
        len(offers),
    )

    return offers


# ============================================================
# USUWANIE DUPLIKATÓW
# ============================================================

def unique_offers(offers):
    result = []
    seen = set()

    for offer in offers:
        key = (
            offer.get("url")
            or offer.get("id")
            or (
                offer.get("source"),
                offer.get("title"),
                offer.get("price"),
            )
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(offer)

    return result


# ============================================================
# GŁÓWNA PĘTLA
# ============================================================

async def run_bot():

    webhook = get_webhook()

    if not webhook:
        log.error(
            "❌ BRAK DISCORD_WEBHOOK!"
        )
        return

    log.info("=" * 60)
    log.info("📱 IPHONE FLIP BOT")
    log.info("🔎 OLX + VINTED")
    log.info("🔎 WYSZUKIWANIE: %s", SEARCH_TEXT)
    log.info("📱 MODELE: iPhone 11–17 przez wspólne wyszukiwanie")
    log.info("⏱️ SKAN CO %s SEKUND", SCAN_INTERVAL)
    log.info("🚫 PROXY: WYŁĄCZONE")
    log.info("=" * 60)

    known_urls = set()

    first_scan = True

    while True:

        scan_start = time.monotonic()

        log.info("-" * 60)
        log.info("🔎 ROZPOCZYNAM WSPÓLNY SKAN")

        # OLX i Vinted jednocześnie.
        olx_task = asyncio.to_thread(fetch_olx)
        vinted_task = asyncio.to_thread(fetch_vinted)

        olx_offers, vinted_offers = await asyncio.gather(
            olx_task,
            vinted_task,
        )

        all_offers = unique_offers(
            olx_offers + vinted_offers
        )

        log.info(
            "📦 ŁĄCZNIE OFERT: %s",
            len(all_offers),
        )

        new_offers = []

        for offer in all_offers:

            url = offer.get("url")

            if not url:
                continue

            if url in known_urls:
                continue

            known_urls.add(url)

            new_offers.append(offer)

        if first_scan:

            log.info(
                "🟢 PIERWSZY SKAN: zapisuję %s istniejących ofert.",
                len(new_offers),
            )

            log.info(
                "🟢 Istniejące oferty NIE zostaną wysłane na Discord."
            )

            first_scan = False

        else:

            log.info(
                "🆕 NOWYCH OFERT: %s",
                len(new_offers),
            )

            for offer in new_offers:

                await send_discord(
                    title=offer["title"],
                    price=offer["price"],
                    url=offer["url"],
                    image=offer.get("image", ""),
                    source=offer["source"],
                )

                # Mała przerwa między wiadomościami Discord.
                await asyncio.sleep(0.5)

        elapsed = time.monotonic() - scan_start

        sleep_time = max(
            1.0,
            SCAN_INTERVAL - elapsed,
        )

        log.info(
            "⏱️ Skan trwał %.1fs.",
            elapsed,
        )

        log.info(
            "💤 Następny skan za %.1fs.",
            sleep_time,
        )

        await asyncio.sleep(sleep_time)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True,
    )

    web_thread.start()

    asyncio.run(
        run_bot()
    )
