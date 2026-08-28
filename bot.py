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

app = Flask(**name**)

@app.route("/")
def home():
return "iPhone Flip Bot działa", 200

def start_web():
port = int(os.getenv("PORT", "10000"))

```
app.run(
    host="0.0.0.0",
    port=port,
    debug=False,
    use_reloader=False
)
```

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

```
return any(
    model in text
    for model in TARGET_MODELS
)
```

def extract_price(text):
text = (text or "").replace("\xa0", " ")

```
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
```

def make_id(source, url):
return source + ":" + url.split("?")[0].rstrip("/")

def send_discord(
title,
price,
url,
source,
image_url=None
):
if not DISCORD_WEBHOOK_URL:
log.error("❌ Brak DISCORD_WEBHOOK_URL")
return False

```
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

try:
    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json={
            "username": "📱 iPhone Flip Bot",
            "embeds": [embed]
        },
        timeout=15
    )

    if response.status_code in (200, 204):
        log.info("✅ Discord: wiadomość wysłana")
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
```

def send_test():
log.info("📨 Wysyłam wiadomość testową na Discord...")

```
send_discord(
    "🟢 BOT URUCHOMIONY — TEST",
    "TEST",
    "https://www.olx.pl/",
    "SYSTEM"
)
```

async def scan_olx(page):
results = []

```
url = (
    "https://www.olx.pl/"
    "elektronika/telefony/smartfony/"
    "?q=iphone"
    "&search%5Border%5D=created_at%3Adesc"
)

try:
    log.info("🔎 OLX: otwieram wyszukiwanie")

    await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=30000
    )

    await page.wait_for_timeout(3000)

    selectors = [
        '[data-cy="l-card"]',
        'div[data-testid="listing-grid"] > div',
        'div[data-cy="ad-card"]',
        'a[href*="/d/oferta/"]'
    ]

    cards = None
    count = 0

    for selector in selectors:
        locator = page.locator(selector)

        try:
            current_count = await locator.count()

            if current_count > count:
                cards = locator
                count = current_count

        except Exception:
            continue

    log.info(
        "OLX: znaleziono %s elementów",
        count
    )

    if not cards or count == 0:
        log.warning(
            "⚠️ OLX: nie znaleziono kart/listingów"
        )
        return results

    processed = set()

    for index in range(min(count, 80)):

        try:
            card = cards.nth(index)

            text = await card.inner_text()

            if not is_target_iphone(text):
                continue

            link = card.locator(
                'a[href*="/d/oferta/"]'
            ).first

            if not await link.count():
                link = card.locator("a").first

            if not await link.count():
                continue

            href = await link.get_attribute("href")

            if not href:
                continue

            item_url = urljoin(
                "https://www.olx.pl",
                href
            )

            item_id = make_id(
                "OLX",
                item_url
            )

            if item_id in processed:
                continue

            processed.add(item_id)

            title = ""

            for selector in [
                "h6",
                "h4",
                '[data-cy="ad-card-title"]',
                '[data-testid="ad-title"]'
            ]:

                try:
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

                except Exception:
                    pass

            if not title:
                for line in text.splitlines():

                    line = line.strip()

                    if is_target_iphone(line):
                        title = line
                        break

            if not title:
                title = "iPhone"

            image_url = None

            try:
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

            except Exception:
                pass

            results.append({
                "id": item_id,
                "title": title,
                "price": extract_price(text),
                "url": item_url,
                "source": "OLX",
                "image": image_url
            })

        except Exception as error:
            log.debug(
                "OLX element error: %s",
                error
            )
            continue

except PlaywrightTimeoutError:
    log.warning("⚠️ OLX: timeout")

except Exception as error:
    log.error(
        "❌ OLX error: %s",
        error
    )

log.info(
    "OLX: pasujących iPhone: %s",
    len(results)
)

return results
```

async def scan_vinted(page):
results = []

```
url = (
    "https://www.vinted.pl/catalog"
    "?search_text=iphone"
    "&order=newest_first"
)

try:
    log.info("🔎 Vinted: otwieram wyszukiwanie")

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

    processed = set()

    for index in range(min(count, 80)):

        try:
            link = links.nth(index)

            href = await link.get_attribute("href")

            if not href:
                continue

            item_url = urljoin(
                "https://www.vinted.pl",
                href
            )

            item_id = make_id(
                "Vinted",
                item_url
            )

            if item_id in processed:
                continue

            processed.add(item_id)

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

            try:

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

            except Exception:
                pass

            results.append({
                "id": item_id,
                "title": title,
                "price": extract_price(text),
                "url": item_url,
                "source": "Vinted",
                "image": image_url
            })

        except Exception as error:

            log.debug(
                "Vinted element error: %s",
                error
            )

            continue

except PlaywrightTimeoutError:
    log.warning("⚠️ Vinted: timeout")

except Exception as error:
    log.error(
        "❌ Vinted error: %s",
        error
    )

log.info(
    "Vinted: pasujących iPhone: %s",
    len(results)
)

return results
```

async def olx_loop(browser, seen):

```
context = await browser.new_context(
    locale="pl-PL",
    viewport={
        "width": 1366,
        "height": 900
    }
)

page = await context.new_page()

first_scan = True

try:

    while True:

        started = (
            asyncio.get_running_loop().time()
        )

        log.info("🔵 OLX — START SKANU")

        try:

            offers = await scan_olx(page)

            if first_scan:

                for offer in offers:
                    seen.add(offer["id"])

                first_scan = False

                log.info(
                    "🟢 OLX — pierwszy skan, "
                    "oferty zapisane bez wysyłania"
                )

            else:

                new_offers = [
                    offer
                    for offer in offers
                    if offer["id"] not in seen
                ]

                log.info(
                    "🆕 OLX — nowych ofert: %s",
                    len(new_offers)
                )

                for offer in new_offers:

                    seen.add(offer["id"])

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
                "❌ OLX loop: %s",
                error
            )

        elapsed = (
            asyncio.get_running_loop().time()
            - started
        )

        wait = max(
            1,
            SCAN_INTERVAL - elapsed
        )

        log.info(
            "⏱️ OLX — następny skan za %.1f s",
            wait
        )

        await asyncio.sleep(wait)

finally:
    await context.close()
```

async def vinted_loop(browser, seen):

```
context = await browser.new_context(
    locale="pl-PL",
    viewport={
        "width": 1366,
        "height": 900
    }
)

page = await context.new_page()

first_scan = True

try:

    while True:

        started = (
            asyncio.get_running_loop().time()
        )

        log.info("🟣 VINTED — START SKANU")

        try:

            offers = await scan_vinted(page)

            if first_scan:

                for offer in offers:
                    seen.add(offer["id"])

                first_scan = False

                log.info(
                    "🟢 VINTED — pierwszy skan, "
                    "oferty zapisane bez wysyłania"
                )

            else:

                new_offers = [
                    offer
                    for offer in offers
                    if offer["id"] not in seen
                ]

                log.info(
                    "🆕 VINTED — nowych ofert: %s",
                    len(new_offers)
                )

                for offer in new_offers:

                    seen.add(offer["id"])

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
                "❌ Vinted loop: %s",
                error
            )

        elapsed = (
            asyncio.get_running_loop().time()
            - started
        )

        wait = max(
            1,
            SCAN_INTERVAL - elapsed
        )

        log.info(
            "⏱️ VINTED — następny skan za %.1f s",
            wait
        )

        await asyncio.sleep(wait)

finally:
    await context.close()
```

async def run_bot():

```
if not DISCORD_WEBHOOK_URL:

    log.error(
        "❌ Brak zmiennej DISCORD_WEBHOOK_URL"
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
    "OLX i Vinted niezależnie co %s sekund",
    SCAN_INTERVAL
)

log.info(
    "======================================"
)

await asyncio.to_thread(
    send_test
)

seen_olx = set()
seen_vinted = set()

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

    try:

        await asyncio.gather(
            olx_loop(
                browser,
                seen_olx
            ),
            vinted_loop(
                browser,
                seen_vinted
            )
        )

    finally:

        await browser.close()
```

if **name** == "**main**":
asyncio.run(run_bot())
