import os
import re
import json
import time
import asyncio
import logging
from pathlib import Path
from flask import Flask
from threading import Thread
from playwright.async_api import async_playwright

# =========================================================
# KONFIGURACJA
# =========================================================

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

CHECK_INTERVAL = 15

SEEN_FILE = Path("seen.json")

OLX_SEARCH = "https://www.olx.pl/elektronika/telefony/smartfony-telefony-komorkowe/iphone/"
VINTED_SEARCH = "https://www.vinted.pl/catalog?search_text=iphone&order=newest_first"

MODELS = range(11, 18)

MAX_PRICE = {
    11: 700,
    12: 900,
    13: 1200,
    14: 1500,
    15: 1800,
    16: 2300,
    17: 2800,
}

KEYWORDS = [
    "uszkodz",
    "zbity",
    "zbita",
    "pęknię",
    "pekniet",
    "bateria",
    "kondycja",
    "face id",
    "ekran",
    "wyświetlacz",
    "wyswietlacz",
    "do naprawy",
    "na części",
    "na czesci",
    "nie działa",
    "nie dziala",
    "tył",
    "tyl",
    "klapa",
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
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "📱 iPhone Flip Bot działa"


@app.route("/health")
def health():
    return "OK"


def start_server():
    port = int(os.getenv("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


# =========================================================
# PAMIĘĆ OFERT
# =========================================================

def load_seen():

    try:
        if not SEEN_FILE.exists():
            return set()

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

        # maksymalnie 50 000 ofert
        data = list(seen)[-50000:]

        with open(
            SEEN_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                data,
                f,
                ensure_ascii=False
            )

    except Exception as e:
        log.warning(
            "Nie można zapisać seen.json: %s",
            e
        )


# =========================================================
# FILTRY
# =========================================================

def get_model(text):

    text = text.lower()

    for model in MODELS:

        if re.search(
            rf"\biphone\s*{model}\b",
            text
        ):
            return model

    return None


def get_price(text):

    if not text:
        return None

    # np. 1 299 zł / 1299,99 zł
    matches = re.findall(
        r"(\d[\d\s]*(?:[,.]\d{1,2})?)\s*(?:zł|PLN)",
        text,
        flags=re.I
    )

    if not matches:
        return None

    value = matches[0]

    value = value.replace(
        " ",
        ""
    )

    value = value.replace(
        ",",
        "."
    )

    try:
        return float(value)
    except Exception:
        return None


def analyze(title, description, price):

    text = (
        str(title)
        + " "
        + str(description)
    ).lower()

    model = get_model(text)

    if model is None:
        return None

    # Odrzucamy akcesoria
    for bad in BAD_WORDS:
        if bad in text:
            return None

    limit = MAX_PRICE[model]

    # Nie wysyłamy drogich ofert
    if price is not None:
        if price > limit:
            return None

    matched = [
        word
        for word in KEYWORDS
        if word in text
    ]

    score = 1

    if matched:
        score += min(
            len(matched),
            5
        )

    if price is not None:

        if price <= limit * 0.75:
            score += 2

        if price <= limit * 0.60:
            score += 1

    return {
        "model": model,
        "price": price,
        "limit": limit,
        "score": score,
        "matched": matched
    }


# =========================================================
# DISCORD
# =========================================================

async def send_discord(
    title,
    price,
    url,
    source,
    result,
    image=None
):

    if not DISCORD_WEBHOOK:
        log.error(
            "BRAK DISCORD_WEBHOOK_URL"
        )
        return

    model = result["model"]
    score = result["score"]
    limit = result["limit"]
    matched = result["matched"]

    if price is None:
        price_text = "Brak ceny"
    else:
        price_text = f"{price:.0f} zł"

    if score >= 7:
        color = 0x2ECC71
    elif score >= 5:
        color = 0xF1C40F
    else:
        color = 0x3498DB

    reason = (
        ", ".join(matched[:8])
        if matched
        else "niska cena / iPhone"
    )

    embed = {
        "title": f"🔥 NOWY iPhone {model}",
        "description": (
            f"**{title[:250]}**\n\n"
            "💰 **Sprawdź i negocjuj!**"
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
            "text": "📱 iPhone Flip Bot • nowe ogłoszenie"
        }
    }

    if image:
        embed["image"] = {
            "url": image
        }

    payload = {
        "username": "📱 iPhone Flip Bot",
        "embeds": [embed]
    }

    import requests

    try:

        response = requests.post(
            DISCORD_WEBHOOK,
            json=payload,
            timeout=15
        )

        if response.status_code in (200, 204):

            log.info(
                "📩 DISCORD → %s | %s | %s",
                source,
                title,
                price_text
            )

        else:

            log.warning(
                "Discord HTTP %s: %s",
                response.status_code,
                response.text[:300]
            )

    except Exception as e:

        log.warning(
            "Discord error: %s",
            e
        )


# =========================================================
# WYCIĄGANIE OFERT Z OLX
# =========================================================

async def scan_olx(page):

    offers = []

    try:

        await page.goto(
            OLX_SEARCH,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(4000)

        # linki do ogłoszeń
        links = await page.locator(
            'a[href*="/d/oferta/"]'
        ).all()

        log.info(
            "OLX: znaleziono %s linków",
            len(links)
        )

        used = set()

        for link in links[:100]:

            try:

                href = await link.get_attribute(
                    "href"
                )

                if not href:
                    continue

                if href.startswith("/"):
                    href = "https://www.olx.pl" + href

                # ID z URL
                match = re.search(
                    r"-ID([A-Za-z0-9]+)\.html",
                    href
                )

                if match:
                    item_id = match.group(1)
                else:
                    item_id = href

                if item_id in used:
                    continue

                used.add(item_id)

                text = await link.inner_text()

                if not text.strip():
                    continue

                offers.append({
                    "id": "olx:" + item_id,
                    "title": text.strip(),
                    "url": href,
                    "image": None,
                    "source": "OLX"
                })

            except Exception:
                continue

    except Exception as e:

        log.warning(
            "OLX ERROR: %s",
            e
        )

    return offers


# =========================================================
# WYCIĄGANIE OFERT Z VINTED
# =========================================================

async def scan_vinted(page):

    offers = []

    try:

        await page.goto(
            VINTED_SEARCH,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(5000)

        links = await page.locator(
            'a[href*="/items/"]'
        ).all()

        log.info(
            "Vinted: znaleziono %s linków",
            len(links)
        )

        used = set()

        for link in links[:100]:

            try:

                href = await link.get_attribute(
                    "href"
                )

                if not href:
                    continue

                if href.startswith("/"):
                    href = "https://www.vinted.pl" + href

                match = re.search(
                    r"/items/(\d+)",
                    href
                )

                if match:
                    item_id = match.group(1)
                else:
                    item_id = href

                if item_id in used:
                    continue

                used.add(item_id)

                text = await link.inner_text()

                if not text.strip():
                    continue

                image = None

                img = link.locator(
                    "img"
                ).first

                if await img.count():

                    image = await img.get_attribute(
                        "src"
                    )

                offers.append({
                    "id": "vinted:" + item_id,
                    "title": text.strip(),
                    "url": href,
                    "image": image,
                    "source": "Vinted"
                })

            except Exception:
                continue

    except Exception as e:

        log.warning(
            "VINTED ERROR: %s",
            e
        )

    return offers


# =========================================================
# GŁÓWNY SKAN
# =========================================================

async def run_bot():

    if not DISCORD_WEBHOOK:

        raise RuntimeError(
            "Dodaj DISCORD_WEBHOOK_URL "
            "w Render → Environment"
        )

    seen = load_seen()

    log.info(
        "======================================"
    )

    log.info(
        "📱 IPHONE FLIP BOT"
    )

    log.info(
        "OLX + VINTED"
    )

    log.info(
        "Co %s sekund",
        CHECK_INTERVAL
    )

    log.info(
        "Zapamiętanych ofert: %s",
        len(seen)
    )

    log.info(
        "======================================"
    )

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        context = await browser.new_context(
            viewport={
                "width": 1366,
                "height": 900
            },
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/139.0 Safari/537.36"
            )
        )

        page = await context.new_page()

        first_scan = len(seen) == 0

        while True:

            started = time.time()

            log.info(
                "🔎 NOWY SKAN"
            )

            # -------------------------
            # OLX
            # -------------------------

            olx_offers = await scan_olx(
                page
            )

            # -------------------------
            # VINTED
            # -------------------------

            vinted_offers = await scan_vinted(
                page
            )

            all_offers = (
                olx_offers
                + vinted_offers
            )

            log.info(
                "Znaleziono łącznie: %s",
                len(all_offers)
            )

            new_count = 0

            for offer in all_offers:

                item_id = offer["id"]

                if item_id in seen:
                    continue

                # ------------------------------------------------
                # PIERWSZY SKAN:
                # zapamiętujemy istniejące oferty,
                # ale NIE spamujemy nimi Discorda.
                # ------------------------------------------------

                if first_scan:

                    seen.add(item_id)
                    continue

                title = offer["title"]

                price = get_price(
                    title
                )

                result = analyze(
                    title,
                    "",
                    price
                )

                seen.add(item_id)

                if not result:
                    continue

                await send_discord(
                    title=title,
                    price=price,
                    url=offer["url"],
                    source=offer["source"],
                    result=result,
                    image=offer["image"]
                )

                new_count += 1

            if first_scan:

                first_scan = False

                log.info(
                    "🟢 Pierwszy skan — "
                    "istniejące oferty zapisane. "
                    "Nie wysyłam ich."
                )

            save_seen(
                seen
            )

            elapsed = time.time() - started

            wait = max(
                2,
                CHECK_INTERVAL - int(elapsed)
            )

            log.info(
                "✅ Skan: %s nowych | "
                "następny za %s sekund",
                new_count,
                wait
            )

            await asyncio.sleep(
                wait
            )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    Thread(
        target=start_server,
        daemon=True
    ).start()

    asyncio.run(
        run_bot()
    )
