import os
import re
import asyncio
import logging
from urllib.parse import urljoin
from threading import Thread

import requests
from flask import Flask
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
SCAN_INTERVAL = 15

TARGET_MODELS = [
    "iphone 11",
    "iphone 12",
    "iphone 13",
    "iphone 14",
    "iphone 15",
    "iphone 16",
    "iphone 17",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")

app = Flask(__name__)


@app.route("/")
def home():
    return "iPhone Flip Bot działa", 200


def start_web():
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


Thread(
    target=start_web,
    daemon=True
).start()


def normalize(text):
    return re.sub(
        r"\s+",
        " ",
        (text or "").lower()
    ).strip()


def is_target_iphone(text):
    text = normalize(text)

    return any(
        model in text
        for model in TARGET_MODELS
    )


def extract_price(text):
    text = (text or "").replace("\xa0", " ")

    match = re.search(
        r"\b\d[\d\s.,]*\s*(?:zł|pln)\b",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(0).strip()

    match = re.search(
        r"\b\d{2,5}(?:[,.]\d{1,2})?\b",
        text
    )

    if match:
        return match.group(0) + " zł"

    return "Cena niepodana"


def make_id(source, url):
    return (
        source
        + ":"
        + url.split("?")[0].rstrip("/")
    )


def send_discord(
    title,
    price,
    url,
    source,
    image_url=None
):
    if not DISCORD_WEBHOOK_URL:
        log.error(
            "❌ Brak DISCORD_WEBHOOK_URL"
        )
        return False

    embed = {
        "title": f"📱 {title[:240]}",
        "url": url,
        "description": (
            f"🔥 **NOWE OGŁOSZENIE — {source}**\n\n"
            f"💰 **Cena:** {price}"
        ),
        "fields": [
            {
                "name": "🌐 Portal",
                "value": source,
                "inline": True
            },
            {
                "name": "💰 Cena",
                "value": price,
                "inline": True
            }
        ],
        "footer": {
            "text": "iPhone Flip Bot"
        }
    }

    if image_url and image_url.startswith(
        ("http://", "https://")
    ):
        embed["image"] = {
            "url": image_url
        }

    payload = {
        "username": "📱 iPhone Flip Bot",
        "embeds": [embed]
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=15
        )

        if response.status_code in (200, 204):
            log.info(
                "✅ Discord: wiadomość wysłana"
            )
            return True

        log.error(
            "❌ Discord HTTP %s: %s",
            response.status_code,
            response.text[:300]
        )

    except Exception as error:
        log.error(
            "❌ Discord error: %s",
            error
        )

    return False


def send_test():
    log.info(
        "📨 Wysyłam wiadomość testową na Discord..."
    )

    send_discord(
        "🟢 BOT URUCHOMIONY — TEST",
        "TEST",
        "https://www.olx.pl/",
        "SYSTEM"
    )


async def scan_olx(page):
    results = []

    url = (
        "https://www.olx.pl/elektronika/"
        "telefony/smartfony/"
        "?q=iphone"
        "&search%5Border%5D=created_at%3Adesc"
    )

    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(2500)

        cards = page.locator(
            '[data-cy="l-card"]'
        )

        count = await cards.count()

        log.info(
            "OLX: znaleziono %s kart",
            count
        )

        for index in range(
            min(count, 50)
        ):
            try:
                card = cards.nth(index)

                text = await card.inner_text()

                if not is_target_iphone(text):
                    continue

                link = card.locator(
                    "a"
                ).first

                if not await link.count():
                    continue

                href = await link.get_attribute(
                    "href"
                )

                if not href:
                    continue

                item_url = urljoin(
                    "https://www.olx.pl",
                    href
                )

                title = ""

                for selector in [
                    "h6",
                    "h4",
                    '[data-cy="ad-card-title"]'
                ]:
                    element = card.locator(
                        selector
                    ).first

                    if await element.count():
                        candidate = (
                            await element.inner_text()
                        ).strip()

                        if candidate:
                            title = candidate
                            break

                if not title:
                    for line in text.splitlines():
                        line = line.strip()

                        if is_target_iphone(line):
                            title = line
                            break

                if not title:
                    title = "iPhone"

                image_url = None

                image = card.locator(
                    "img"
                ).first

                if await image.count():
                    image_url = await image.get_attribute(
                        "src"
                    )

                    if not image_url:
                        image_url = await image.get_attribute(
                            "data-src"
                        )

                results.append({
                    "id": make_id(
                        "OLX",
                        item_url
                    ),
                    "title": title,
                    "price": extract_price(text),
                    "url": item_url,
                    "source": "OLX",
                    "image": image_url
                })

            except Exception:
                continue

    except PlaywrightTimeoutError:
        log.warning(
            "⚠️ OLX: timeout"
        )

    except Exception as error:
        log.error(
            "❌ OLX: %s",
            error
        )

    return results


async def scan_vinted(page):
    results = []

    url = (
        "https://www.vinted.pl/catalog"
        "?search_text=iphone"
        "&order=newest_first"
    )

    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(3000)

        links = page.locator(
            'a[href*="/items/"]'
        )

        count = await links.count()

        log.info(
            "Vinted: znaleziono %s linków",
            count
        )

        already_seen = set()

        for index in range(
            min(count, 60)
        ):
            try:
                link = links.nth(index)

                href = await link.get_attribute(
                    "href"
                )

                if not href:
                    continue

                item_url = urljoin(
                    "https://www.vinted.pl",
                    href
                )

                if item_url in already_seen:
                    continue

                already_seen.add(item_url)

                card = link

                for _ in range(4):
                    parent = card.locator("..")

                    if await parent.count():
                        card = parent

                text = await card.inner_text()

                if not is_target_iphone(text):
                    continue

                lines = [
                    line.strip()
                    for line in text.splitlines()
                    if line.strip()
                ]

                title = ""

                for line in lines:
                    if is_target_iphone(line):
                        title = line
                        break

                if not title:
                    title = "iPhone"

                image_url = None

                image = link.locator(
                    "img"
                ).first

                if await image.count():
                    image_url = await image.get_attribute(
                        "src"
                    )

                    if not image_url:
                        image_url = await image.get_attribute(
                            "data-src"
                        )

                results.append({
                    "id": make_id(
                        "Vinted",
                        item_url
                    ),
                    "title": title,
                    "price": extract_price(text),
                    "url": item_url,
                    "source": "Vinted",
                    "image": image_url
                })

            except Exception:
                continue

    except PlaywrightTimeoutError:
        log.warning(
            "⚠️ Vinted: timeout"
        )

    except Exception as error:
        log.error(
            "❌ Vinted: %s",
            error
        )

    return results


async def scan_all(browser):

    context_olx = await browser.new_context(
        locale="pl-PL",
        viewport={
            "width": 1366,
            "height": 900
        }
    )

    context_vinted = await browser.new_context(
        locale="pl-PL",
        viewport={
            "width": 1366,
            "height": 900
        }
    )

    page_olx = await context_olx.new_page()
    page_vinted = await context_vinted.new_page()

    try:
        log.info(
            "🔎 OLX + VINTED — skan równoczesny"
        )

        olx_task = asyncio.create_task(
            scan_olx(page_olx)
        )

        vinted_task = asyncio.create_task(
            scan_vinted(page_vinted)
        )

        olx_results, vinted_results = (
            await asyncio.gather(
                olx_task,
                vinted_task,
                return_exceptions=True
            )
        )

        if isinstance(
            olx_results,
            Exception
        ):
            log.error(
                "❌ OLX task: %s",
                olx_results
            )
            olx_results = []

        if isinstance(
            vinted_results,
            Exception
        ):
            log.error(
                "❌ Vinted task: %s",
                vinted_results
            )
            vinted_results = []

        combined = {}

        for offer in (
            olx_results + vinted_results
        ):
            combined[
                offer["id"]
            ] = offer

        return list(
            combined.values()
        )

    finally:
        await context_olx.close()
        await context_vinted.close()


async def run_bot():

    if not DISCORD_WEBHOOK_URL:
        log.error(
            "❌ NIE MA DISCORD_WEBHOOK_URL"
        )
        return

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
        "Oba portale równocześnie co %s sekund",
        SCAN_INTERVAL
    )

    log.info(
        "======================================"
    )

    await asyncio.to_thread(
        send_test
    )

    async with async_playwright() as playwright:

        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        seen = set()

        first_scan = True

        try:

            while True:

                start = (
                    asyncio.get_running_loop().time()
                )

                try:

                    offers = await scan_all(
                        browser
                    )

                    log.info(
                        "📦 Znaleziono: %s",
                        len(offers)
                    )

                    if first_scan:

                        for offer in offers:
                            seen.add(
                                offer["id"]
                            )

                        first_scan = False

                        log.info(
                            "🟢 Pierwszy skan — "
                            "istniejące oferty zapisane."
                        )

                        log.info(
                            "📭 Nie wysyłam starych ofert."
                        )

                    else:

                        new_offers = [
                            offer
                            for offer in offers
                            if offer["id"]
                            not in seen
                        ]

                        log.info(
                            "🆕 Nowych ofert: %s",
                            len(new_offers)
                        )

                        for offer in new_offers:

                            seen.add(
                                offer["id"]
                            )

                            log.info(
                                "📱 NOWA %s: %s | %s",
                                offer["source"],
                                offer["title"],
                                offer["price"]
                            )

                            await asyncio.to_thread(
                                send_discord,
                                offer["title"],
                                offer["price"],
                                offer["url"],
                                offer["source"],
                                offer["image"]
                            )

                except Exception as error:

                    log.exception(
                        "❌ Błąd skanu: %s",
                        error
                    )

                elapsed = (
                    asyncio.get_running_loop().time()
                    - start
                )

                wait = max(
                    1,
                    SCAN_INTERVAL - elapsed
                )

                log.info(
                    "⏱️ Następny skan za %.1f sekund",
                    wait
                )

                await asyncio.sleep(
                    wait
                )

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run_bot())
