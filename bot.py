import os
import re
import asyncio
import logging
from urllib.parse import urljoin

import requests
from flask import Flask
from threading import Thread
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
SCAN_INTERVAL = 15

TARGET_MODELS = [
"iphone 11", "iphone 12", "iphone 13",
"iphone 14", "iphone 15", "iphone 16", "iphone 17"
]

FLIP_KEYWORDS = [
"uszkodz", "zbity", "zbita", "pęknię", "peknię",
"do naprawy", "naprawy", "na części", "na czesci",
"bateria", "wyświetlacz", "wyswietlacz", "ekran",
"face id", "nie działa", "nie dziala",
"uszkodzona", "uszkodzony", "tył", "tyl",
"klapa", "aparaty", "dotyk", "okazja", "tanio"
]

logging.basicConfig(
level=logging.INFO,
format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")

app = Flask(**name**)

@app.route("/")
def home():
return "📱 iPhone Flip Bot działa!"

def run_web_server():
port = int(os.getenv("PORT", "10000"))
app.run(
host="0.0.0.0",
port=port,
debug=False,
use_reloader=False
)

Thread(
target=run_web_server,
daemon=True
).start()

def send_discord_embed(
title,
price,
url,
source,
image_url=None,
reason=""
):
if not DISCORD_WEBHOOK_URL:
log.error("❌ BRAK DISCORD_WEBHOOK_URL!")
return False

```
embed = {
    "title": f"📱 {title[:240]}",
    "url": url,
    "description": (
        f"**🔥 NOWE OGŁOSZENIE — {source}**\n\n"
        f"💰 **Cena:** {price}\n"
        f"🔎 **Powód:** {reason}"
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
        "text": "iPhone Flip Bot • skan co 15 sekund"
    }
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
    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json=payload,
        timeout=15
    )

    if response.status_code in (200, 204):
        log.info("✅ DISCORD: wiadomość wysłana")
        return True

    log.error(
        "❌ DISCORD HTTP %s: %s",
        response.status_code,
        response.text[:500]
    )
    return False

except Exception as e:
    log.error("❌ Błąd Discord: %s", e)
    return False
```

def send_startup_test():
log.info("📨 Wysyłam testową wiadomość na Discord...")

```
send_discord_embed(
    title="🟢 BOT URUCHOMIONY — TEST",
    price="TEST",
    url="https://www.olx.pl/",
    source="SYSTEM",
    reason=(
        "Jeżeli widzisz tę wiadomość, "
        "webhook Discorda działa poprawnie."
    )
)
```

def normalize(text):
return re.sub(
r"\s+",
" ",
(text or "").lower()
).strip()

def detect_model(title):
text = normalize(title)

```
for model in TARGET_MODELS:
    if model in text:
        return model

return None
```

def is_target(title):
return detect_model(title) is not None

def get_reason(title):
text = normalize(title)

```
matched = [
    word
    for word in FLIP_KEYWORDS
    if word in text
]

if matched:
    return "Słowa: " + ", ".join(matched[:6])

return "iPhone 11–17"
```

def clean_price(text):
if not text:
return "Cena niepodana"

```
text = text.replace("\xa0", " ")

match = re.search(
    r"(\d[\d\s.,]*)\s*(zł|pln)",
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

async def scan_olx(page):
results = []

```
url = (
    "https://www.olx.pl/elektronika/"
    "telefony/smartfony/"
    "?q=iphone&search%5Border%5D=created_at%3Adesc"
)

try:
    await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=30000
    )

    await page.wait_for_timeout(2500)

    cards = page.locator('[data-cy="l-card"]')
    count = await cards.count()

    log.info("OLX: znaleziono %s kart", count)

    for i in range(min(count, 40)):
        try:
            card = cards.nth(i)
            title = ""

            for selector in [
                "h6",
                "h4",
                '[data-cy="ad-card-title"]',
                "a"
            ]:
                try:
                    element = card.locator(selector).first

                    if await element.count():
                        text = (
                            await element.inner_text()
                        ).strip()

                        if text:
                            title = text
                            break
                except Exception:
                    pass

            if not title or not is_target(title):
                continue

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

            price = "Cena niepodana"

            try:
                price_element = card.locator(
                    '[data-testid="ad-price"]'
                ).first

                if await price_element.count():
                    price = clean_price(
                        await price_element.inner_text()
                    )
            except Exception:
                pass

            image_url = None

            try:
                image = card.locator("img").first

                if await image.count():
                    image_url = await image.get_attribute("src")

                    if not image_url:
                        image_url = await image.get_attribute(
                            "data-src"
                        )
            except Exception:
                pass

            results.append({
                "id": make_id("OLX", item_url),
                "title": title,
                "price": price,
                "url": item_url,
                "source": "OLX",
                "image": image_url,
                "reason": get_reason(title)
            })

        except Exception:
            continue

except PlaywrightTimeoutError:
    log.warning("⚠️ OLX: timeout")

except Exception as e:
    log.error("❌ OLX: %s", e)

return results
```

async def scan_vinted(page):
results = []

```
url = (
    "https://www.vinted.pl/catalog?"
    "search_text=iphone&order=newest_first"
)

try:
    await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=30000
    )

    await page.wait_for_timeout(3000)

    links = page.locator('a[href*="/items/"]')
    count = await links.count()

    log.info("Vinted: znaleziono %s linków", count)

    seen_urls = set()

    for i in range(min(count, 50)):
        try:
            link = links.nth(i)

            href = await link.get_attribute("href")

            if not href:
                continue

            item_url = urljoin(
                "https://www.vinted.pl",
                href
            )

            if item_url in seen_urls:
                continue

            seen_urls.add(item_url)

            card = link

            for _ in range(4):
                try:
                    parent = card.locator("..")

                    if await parent.count():
                        card = parent
                except Exception:
                    break

            text = await card.inner_text()

            if not text:
                text = await link.inner_text()

            lines = [
                x.strip()
                for x in text.splitlines()
                if x.strip()
            ]

            title = ""

            for line in lines:
                if detect_model(line):
                    title = line
                    break

            if not title:
                try:
                    aria = await link.get_attribute(
                        "aria-label"
                    )

                    if aria and detect_model(aria):
                        title = aria
                except Exception:
                    pass

            if not title or not is_target(title):
                continue

            price = clean_price(text)
            image_url = None

            try:
                image = link.locator("img").first

                if await image.count():
                    image_url = await image.get_attribute("src")

                    if not image_url:
                        image_url = await image.get_attribute(
                            "data-src"
                        )
            except Exception:
                pass

            results.append({
                "id": make_id("Vinted", item_url),
                "title": title,
                "price": price,
                "url": item_url,
                "source": "Vinted",
                "image": image_url,
                "reason": get_reason(title)
            })

        except Exception:
            continue

except PlaywrightTimeoutError:
    log.warning("⚠️ Vinted: timeout")

except Exception as e:
    log.error("❌ Vinted: %s", e)

return results
```

async def scan_both(browser):
context_olx = await browser.new_context(
locale="pl-PL",
viewport={"width": 1366, "height": 900}
)

```
context_vinted = await browser.new_context(
    locale="pl-PL",
    viewport={"width": 1366, "height": 900}
)

page_olx = await context_olx.new_page()
page_vinted = await context_vinted.new_page()

try:
    log.info("🚀 Start OLX + Vinted RÓWNOCZEŚNIE")

    olx_task = asyncio.create_task(
        scan_olx(page_olx)
    )

    vinted_task = asyncio.create_task(
        scan_vinted(page_vinted)
    )

    olx_results, vinted_results = await asyncio.gather(
        olx_task,
        vinted_task,
        return_exceptions=True
    )

    if isinstance(olx_results, Exception):
        log.error(
            "❌ Błąd zadania OLX: %s",
            olx_results
        )
        olx_results = []

    if isinstance(vinted_results, Exception):
        log.error(
            "❌ Błąd zadania Vinted: %s",
            vinted_results
        )
        vinted_results = []

    return olx_results + vinted_results

finally:
    await context_olx.close()
    await context_vinted.close()
```

async def run_bot():

```
if not DISCORD_WEBHOOK_URL:
    log.error("❌ Brak DISCORD_WEBHOOK_URL!")
    log.error(
        "Render → Environment → DISCORD_WEBHOOK_URL"
    )
    return

log.info("======================================")
log.info("📱 IPHONE FLIP BOT")
log.info("OLX + VINTED")
log.info(
    "Równocześnie co %s sekund",
    SCAN_INTERVAL
)
log.info("======================================")

await asyncio.to_thread(
    send_startup_test
)

async with async_playwright() as p:

    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-zygote"
        ]
    )

    seen_ids = set()
    first_scan = True

    try:

        while True:

            cycle_start = (
                asyncio.get_running_loop().time()
            )

            log.info("")
            log.info(
                "🔎 NOWY SKAN — OLX + VINTED"
            )

            try:

                offers = await scan_both(browser)

                unique = {}

                for offer in offers:
                    unique[offer["id"]] = offer

                offers = list(unique.values())

                log.info(
                    "📦 Pasujących ofert: %s",
                    len(offers)
                )

                if first_scan:

                    for offer in offers:
                        seen_ids.add(offer["id"])

                    log.info(
                        "🟢 Pierwszy skan — "
                        "zapisano istniejące oferty."
                    )

                    log.info(
                        "📭 Nie wysyłam istniejących ofert."
                    )

                    first_scan = False

                else:

                    new_offers = [
                        offer
                        for offer in offers
                        if offer["id"] not in seen_ids
                    ]

                    log.info(
                        "🆕 Nowych ofert: %s",
                        len(new_offers)
                    )

                    for offer in new_offers:

                        seen_ids.add(
                            offer["id"]
                        )

                        log.info(
                            "📱 NOWA: %s | %s",
                            offer["source"],
                            offer["title"]
                        )

                        await asyncio.to_thread(
                            send_discord_embed,
                            offer["title"],
                            offer["price"],
                            offer["url"],
                            offer["source"],
                            offer["image"],
                            offer["reason"]
                        )

            except Exception as e:

                log.exception(
                    "❌ Błąd skanowania: %s",
                    e
                )

            elapsed = (
                asyncio.get_running_loop().time()
                - cycle_start
            )

            wait_time = max(
                0,
                SCAN_INTERVAL - elapsed
            )

            log.info(
                "⏱️ Następny skan za %.1f sekund",
                wait_time
            )

            await asyncio.sleep(
                wait_time
            )

    finally:
        await browser.close()
```

if **name** == "**main**":

```
try:
    asyncio.run(run_bot())

except KeyboardInterrupt:
    log.info("🛑 Bot zatrzymany.")

except Exception as e:
    log.exception(
        "💥 Krytyczny błąd: %s",
        e
    )
```
