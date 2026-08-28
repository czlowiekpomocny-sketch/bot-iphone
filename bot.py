import os
import asyncio
import logging
import threading
import time
from urllib.parse import quote

import requests
from flask import Flask
from playwright.async_api import async_playwright


SCAN_INTERVAL = 15

SEARCHES = ["iphone"]

MAX_RESULTS = 30

PLAYWRIGHT_TIMEOUT = 10000


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


def get_webhook():
    webhook = os.environ.get("DISCORD_WEBHOOK")

    if webhook:
        webhook = webhook.strip()

    return webhook


def send_discord(title, price, url, image, source):
    webhook = get_webhook()

    if not webhook:
        log.error("Brak DISCORD_WEBHOOK")
        return

    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
        "url": url,
        "description": (
            f"💰 **Cena:** {price or 'Brak ceny'}\n"
            f"🌐 **Źródło:** {source}"
        ),
        "footer": {
            "text": "iPhone Flip Bot"
        }
    }

    if image and image.startswith("http"):
        embed["thumbnail"] = {"url": image}

    try:
        response = requests.post(
            webhook,
            json={"embeds": [embed]},
            timeout=10
        )

        if 200 <= response.status_code < 300:
            log.info(
                f"✅ Discord [{source}] -> {title[:50]}"
            )
        else:
            log.error(
                f"Discord HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

    except Exception as e:
        log.error(f"Discord error: {e}")


def send_test_message():
    webhook = get_webhook()

    if not webhook:
        log.error("Brak DISCORD_WEBHOOK")
        return

    payload = {
        "embeds": [
            {
                "title": "🟢 iPhone Flip Bot — TEST",
                "description": (
                    "Bot działa.\n"
                    "Rozpoczynam skanowanie OLX + Vinted."
                ),
                "color": 3066993
            }
        ]
    }

    try:
        response = requests.post(
            webhook,
            json=payload,
            timeout=10
        )

        if 200 <= response.status_code < 300:
            log.info("✅ Discord: wiadomość testowa wysłana")
        else:
            log.error(
                f"❌ Discord test HTTP {response.status_code}"
            )

    except Exception as e:
        log.error(f"❌ Discord test error: {e}")


async def scan_olx(page):
    results = []

    url = (
        "https://www.olx.pl/d/elektronika/telefony/"
        "telefony-komorkowe/q-iphone/"
        "?search%5Border%5D=created_at:desc"
    )

    log.info("OLX: sprawdzam iphone")

    try:
        await page.goto(
            url,
            wait_until="commit",
            timeout=PLAYWRIGHT_TIMEOUT
        )

        await page.wait_for_timeout(2000)

        cards = page.locator('[data-cy="l-card"]')

        total = await cards.count()

        log.info(f"OLX: parser widzi {total} kart")

        for i in range(min(total, MAX_RESULTS)):
            try:
                card = cards.nth(i)

                link = card.locator("a").first
                href = await link.get_attribute("href")

                if not href:
                    continue

                if "/d/oferta/" not in href:
                    continue

                if href.startswith("/"):
                    href = "https://www.olx.pl" + href

                href = href.split("?")[0]

                title_el = card.locator("h6, h4").first

                if await title_el.count():
                    title = (await title_el.inner_text()).strip()
                else:
                    title = "iPhone - OLX"

                price_el = card.locator(
                    '[data-testid="ad-price"]'
                )

                if await price_el.count():
                    price = (await price_el.inner_text()).strip()
                else:
                    price = "Brak ceny"

                img = card.locator("img").first

                if await img.count():
                    image = await img.get_attribute("src")
                else:
                    image = ""

                results.append({
                    "source": "OLX",
                    "url": href,
                    "title": title,
                    "price": price,
                    "image": image or ""
                })

            except Exception as e:
                log.debug(f"OLX karta: {e}")

    except Exception as e:
        log.error(f"❌ OLX error: {e}")

    log.info(
        f"OLX: znaleziono {len(results)} poprawnych ofert"
    )

    return results


async def scan_vinted(page):
    results = []

    url = (
        "https://www.vinted.pl/catalog"
        "?search_text=iphone"
        "&order=newest_first"
    )

    log.info("Vinted: sprawdzam iphone")

    try:
        await page.goto(
            url,
            wait_until="commit",
            timeout=PLAYWRIGHT_TIMEOUT
        )

        await page.wait_for_timeout(3000)

        items = page.locator(
            '[data-testid="grid-item"]'
        )

        total = await items.count()

        log.info(f"Vinted: parser widzi {total} kart")

        for i in range(min(total, MAX_RESULTS)):
            try:
                item = items.nth(i)

                link = item.locator("a").first

                href = await link.get_attribute("href")

                if not href:
                    continue

                if "/items/" not in href:
                    continue

                if href.startswith("/"):
                    href = "https://www.vinted.pl" + href

                href = href.split("?")[0]

                title = await link.get_attribute("title")

                if not title:
                    try:
                        text = await item.inner_text()
                        title = text.split("\n")[0]
                    except Exception:
                        title = "iPhone - Vinted"

                price_el = item.locator(
                    '[data-testid*="price"]'
                )

                if await price_el.count():
                    price = (await price_el.inner_text()).strip()
                else:
                    price = "Brak ceny"

                img = item.locator("img").first

                if await img.count():
                    image = await img.get_attribute("src")
                else:
                    image = ""

                results.append({
                    "source": "Vinted",
                    "url": href,
                    "title": title.strip(),
                    "price": price,
                    "image": image or ""
                })

            except Exception as e:
                log.debug(f"Vinted karta: {e}")

    except Exception as e:
        log.error(f"❌ Vinted error: {e}")

    log.info(
        f"Vinted: znaleziono {len(results)} poprawnych ofert"
    )

    return results


async def scan_both(olx_page, vinted_page):
    log.info("🔎 OLX + VINTED — SKAN RÓWNOCZESNY")

    olx_task = asyncio.create_task(
        scan_olx(olx_page)
    )

    vinted_task = asyncio.create_task(
        scan_vinted(vinted_page)
    )

    olx_results, vinted_results = await asyncio.gather(
        olx_task,
        vinted_task
    )

    return olx_results + vinted_results


async def run_bot():
    if not get_webhook():
        log.error("❌ Brak DISCORD_WEBHOOK")
        return

    log.info("======================================")
    log.info("📱 IPHONE FLIP BOT")
    log.info("OLX + VINTED")
    log.info("🔎 WSPÓLNE WYSZUKIWANIE: IPHONE")
    log.info("⏱️ SKAN CO 15 SEKUND")
    log.info("======================================")

    send_test_message()

    known = set()

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
                "width": 1280,
                "height": 720
            },
            locale="pl-PL",
            timezone_id="Europe/Warsaw"
        )

        olx_page = await context.new_page()
        vinted_page = await context.new_page()

        first_scan = True

        while True:
            started = time.monotonic()

            log.info("🔎 ROZPOCZYNAM WSPÓLNY SKAN")

            try:
                offers = await scan_both(
                    olx_page,
                    vinted_page
                )

                log.info(
                    f"📦 Łącznie ofert: {len(offers)}"
                )

                new_count = 0

                if first_scan:
                    for offer in offers:
                        if offer.get("url"):
                            known.add(offer["url"])

                    first_scan = False

                    log.info(
                        f"🟢 Baza początkowa: {len(known)} ofert"
                    )

                else:
                    for offer in offers:
                        url = offer.get("url")

                        if not url or url in known:
                            continue

                        known.add(url)

                        send_discord(
                            title=offer.get("title"),
                            price=offer.get("price"),
                            url=url,
                            image=offer.get("image"),
                            source=offer.get("source")
                        )

                        new_count += 1

                        await asyncio.sleep(0.5)

                log.info(
                    f"🆕 Nowych ofert: {new_count}"
                )

            except Exception as e:
                log.exception(
                    f"❌ Błąd wspólnego skanu: {e}"
                )

            elapsed = time.monotonic() - started

            wait = max(
                0,
                SCAN_INTERVAL - elapsed
            )

            log.info(
                f"⏱️ Następny skan za {wait:.1f}s"
            )

            await asyncio.sleep(wait)


if __name__ == "__main__":
    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    asyncio.run(run_bot())
