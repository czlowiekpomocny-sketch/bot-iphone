import os
import asyncio
import logging
import threading
import time
import re
from urllib.parse import quote

import requests
from flask import Flask
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ============================================================

# KONFIGURACJA

# ============================================================

SCAN_INTERVAL = 15

SEARCH_TEXT = "iphone"

MAX_RESULTS = 50

PAGE_TIMEOUT = 15000

ALLOWED_MODELS = [
"iphone 11",
"iphone 12",
"iphone 13",
"iphone 14",
"iphone 15",
"iphone 16",
"iphone 17",
]

# ============================================================

# LOGOWANIE

# ============================================================

logging.basicConfig(
level=logging.INFO,
format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")

# ============================================================

# FLASK

# ============================================================

app = Flask(**name**)

@app.route("/")
def home():
return "iPhone Flip Bot działa."

def start_web_server():
port = int(os.environ.get("PORT", "10000"))

```
app.run(
    host="0.0.0.0",
    port=port,
    debug=False,
    use_reloader=False
)
```

# ============================================================

# DISCORD

# ============================================================

def get_webhook():
webhook = os.environ.get("DISCORD_WEBHOOK")

```
if webhook:
    webhook = webhook.strip()

return webhook
```

def send_discord(title, price, url, image="", source=""):
webhook = get_webhook()

```
if not webhook:
    log.error("❌ Brak DISCORD_WEBHOOK.")
    return False

embed = {
    "title": (title or "Nowe ogłoszenie")[:256],
    "url": url,
    "color": 5814783 if source == "OLX" else 65490,
    "description": (
        f"💰 **Cena:** {price or 'Brak ceny'}\n"
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

try:
    response = requests.post(
        webhook,
        json={"embeds": [embed]},
        timeout=10
    )

    if 200 <= response.status_code < 300:
        log.info(
            f"✅ Discord [{source}]: wysłano -> "
            f"{(title or 'Ogłoszenie')[:60]}"
        )
        return True

    log.error(
        f"❌ Discord HTTP {response.status_code}: "
        f"{response.text[:300]}"
    )

except Exception as e:
    log.error(f"❌ Discord error: {e}")

return False
```

def send_test_message():
webhook = get_webhook()

```
if not webhook:
    log.error(
        "❌ DISCORD_WEBHOOK nie jest ustawiony."
    )
    return False

payload = {
    "embeds": [
        {
            "title": "🟢 iPhone Flip Bot — TEST",
            "description": (
                "Bot uruchomił się poprawnie.\n\n"
                "Monitoring OLX + Vinted jest aktywny."
            ),
            "color": 3066993,
            "footer": {
                "text": "iPhone Flip Bot"
            }
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
        log.info(
            "✅ Discord: wiadomość testowa wysłana"
        )
        return True

    log.error(
        f"❌ Discord test HTTP {response.status_code}: "
        f"{response.text[:300]}"
    )

except Exception as e:
    log.error(
        f"❌ Discord test error: {e}"
    )

return False
```

# ============================================================

# FILTR IPHONE 11–17

# ============================================================

def is_allowed_iphone(title):
if not title:
return False

```
text = title.lower()

text = re.sub(
    r"[\-_/,.:;()\[\]]",
    " ",
    text
)

text = re.sub(
    r"\s+",
    " ",
    text
).strip()

for model in ALLOWED_MODELS:
    pattern = r"\b" + re.escape(model) + r"\b"

    if re.search(pattern, text):
        return True

return False
```

# ============================================================

# OLX

# ============================================================

async def scan_olx(page):
found = []

```
url = (
    "https://www.olx.pl/d/elektronika/telefony/"
    "telefony-komorkowe/"
    f"q-{quote(SEARCH_TEXT)}/"
    "?search%5Border%5D=created_at:desc"
)

log.info("OLX: sprawdzam najnowsze oferty iPhone")

try:
    await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=PAGE_TIMEOUT
    )

    await page.wait_for_timeout(2000)

except PlaywrightTimeoutError:
    log.warning(
        "⚠️ OLX: timeout podczas ładowania strony."
    )

except Exception as e:
    log.warning(
        f"⚠️ OLX: błąd ładowania: {e}"
    )

# --------------------------------------------------------
# Próba znalezienia kart różnymi selektorami
# --------------------------------------------------------

selectors = [
    '[data-cy="l-card"]',
    'div[data-testid="l-card"]',
    'article',
    'a[href*="/d/oferta/"]'
]

cards = []

for selector in selectors:
    try:
        count = await page.locator(selector).count()

        if count > 0:
            cards = await page.locator(selector).all()
            log.info(
                f"OLX: znaleziono elementy przez "
                f"{selector}: {count}"
            )
            break

    except Exception:
        continue

if not cards:
    log.warning(
        "⚠️ OLX: nie znaleziono kart ogłoszeń."
    )

    return found

seen = set()

for card in cards:

    if len(found) >= MAX_RESULTS:
        break

    try:
        link = card.locator(
            'a[href*="/d/oferta/"]'
        ).first

        if await link.count() == 0:
            continue

        href = await link.get_attribute("href")

        if not href:
            continue

        if href.startswith("/"):
            full_url = (
                "https://www.olx.pl" + href
            )
        else:
            full_url = href

        full_url = full_url.split("?")[0]

        if full_url in seen:
            continue

        seen.add(full_url)

        title = ""

        title_selectors = [
            "h6",
            "h4",
            '[data-testid="ad-title"]',
            "p"
        ]

        for title_selector in title_selectors:

            try:
                element = card.locator(
                    title_selector
                ).first

                if await element.count() > 0:
                    text = await element.inner_text()

                    if text and text.strip():
                        title = text.strip()
                        break

            except Exception:
                continue

        if not title:
            try:
                title = await link.get_attribute(
                    "title"
                ) or ""
            except Exception:
                title = ""

        if not title:
            title = "Ogłoszenie OLX"

        if not is_allowed_iphone(title):
            continue

        price = "Brak ceny"

        price_selectors = [
            '[data-testid="ad-price"]',
            '[data-cy="ad-price"]'
        ]

        for price_selector in price_selectors:

            try:
                element = card.locator(
                    price_selector
                ).first

                if await element.count() > 0:
                    text = await element.inner_text()

                    if text:
                        price = text.strip()
                        break

            except Exception:
                continue

        image = ""

        try:
            img = card.locator("img").first

            if await img.count() > 0:
                image = (
                    await img.get_attribute("src")
                    or ""
                )

        except Exception:
            pass

        found.append(
            {
                "source": "OLX",
                "url": full_url,
                "title": title,
                "price": price,
                "image": image
            }
        )

    except Exception:
        continue

log.info(
    f"🟢 OLX: znaleziono {len(found)} "
    f"pasujących ofert"
)

return found
```

# ============================================================

# VINTED

# ============================================================

async def scan_vinted(page):
found = []

```
url = (
    "https://www.vinted.pl/catalog"
    f"?search_text={quote(SEARCH_TEXT)}"
    "&order=newest_first"
)

log.info(
    "Vinted: sprawdzam najnowsze oferty iPhone"
)

try:
    await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=PAGE_TIMEOUT
    )

    await page.wait_for_timeout(2500)

except PlaywrightTimeoutError:
    log.warning(
        "⚠️ Vinted: timeout podczas ładowania."
    )

except Exception as e:
    log.warning(
        f"⚠️ Vinted: błąd ładowania: {e}"
    )

selectors = [
    '[data-testid="grid-item"]',
    'a[href*="/items/"]'
]

items = []

for selector in selectors:

    try:
        count = await page.locator(
            selector
        ).count()

        if count > 0:
            items = await page.locator(
                selector
            ).all()

            log.info(
                f"Vinted: znaleziono elementy przez "
                f"{selector}: {count}"
            )

            break

    except Exception:
        continue

if not items:
    log.warning(
        "⚠️ Vinted: nie znaleziono ofert."
    )

    return found

seen = set()

for item in items:

    if len(found) >= MAX_RESULTS:
        break

    try:

        if await item.evaluate(
            "(el) => el.tagName.toLowerCase()"
        ) == "a":

            link = item

        else:

            link = item.locator(
                'a[href*="/items/"]'
            ).first

        if await link.count() == 0:
            continue

        href = await link.get_attribute(
            "href"
        )

        if not href or "/items/" not in href:
            continue

        if href.startswith("/"):
            full_url = (
                "https://www.vinted.pl" + href
            )
        else:
            full_url = href

        full_url = full_url.split("?")[0]

        if full_url in seen:
            continue

        seen.add(full_url)

        title = ""

        try:
            title = (
                await link.get_attribute("title")
                or ""
            )
        except Exception:
            pass

        if not title:

            try:
                title = await item.inner_text()
            except Exception:
                title = ""

        if not title:
            title = "Ogłoszenie Vinted"

        title = title.strip()

        if not is_allowed_iphone(title):
            continue

        price = "Brak ceny"

        try:
            price_element = item.locator(
                '[data-testid*="price"]'
            ).first

            if await price_element.count() > 0:
                text = await price_element.inner_text()

                if text:
                    price = text.strip()

        except Exception:
            pass

        image = ""

        try:
            img = item.locator(
                "img"
            ).first

            if await img.count() > 0:
                image = (
                    await img.get_attribute(
                        "src"
                    )
                    or ""
                )

        except Exception:
            pass

        found.append(
            {
                "source": "Vinted",
                "url": full_url,
                "title": title.split("\n")[0].strip(),
                "price": price,
                "image": image
            }
        )

    except Exception:
        continue

log.info(
    f"🟢 Vinted: znaleziono {len(found)} "
    f"pasujących ofert"
)

return found
```

# ============================================================

# WSPÓLNY SKAN

# ============================================================

async def scan_both(olx_page, vinted_page):

```
log.info(
    "🔎 OLX + VINTED — SKAN RÓWNOCZESNY"
)

olx_task = asyncio.create_task(
    scan_olx(olx_page)
)

vinted_task = asyncio.create_task(
    scan_vinted(vinted_page)
)

results = await asyncio.gather(
    olx_task,
    vinted_task,
    return_exceptions=True
)

olx_results = []
vinted_results = []

if isinstance(results[0], Exception):

    log.error(
        f"❌ OLX — błąd skanowania: "
        f"{results[0]}"
    )

else:

    olx_results = results[0]

if isinstance(results[1], Exception):

    log.error(
        f"❌ Vinted — błąd skanowania: "
        f"{results[1]}"
    )

else:

    vinted_results = results[1]

return olx_results + vinted_results
```

# ============================================================

# GŁÓWNY BOT

# ============================================================

async def run_bot():

```
webhook = get_webhook()

if not webhook:

    log.error(
        "❌ Brak DISCORD_WEBHOOK."
    )

    return

log.info(
    "======================================"
)

log.info(
    "📱 IPHONE FLIP BOT"
)

log.info(
    "🔎 OLX + VINTED"
)

log.info(
    "📱 Wyszukiwanie: iphone"
)

log.info(
    "📱 Modele: iPhone 11–17"
)

log.info(
    "⏱️ Wspólny skan co 15 sekund"
)

log.info(
    "======================================"
)

send_test_message()

known = set()

first_scan = True

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
        timezone_id="Europe/Warsaw",
        user_agent=(
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        )
    )

    olx_page = await context.new_page()

    vinted_page = await context.new_page()

    olx_page.set_default_timeout(
        PAGE_TIMEOUT
    )

    vinted_page.set_default_timeout(
        PAGE_TIMEOUT
    )

    while True:

        cycle_start = time.monotonic()

        log.info(
            "🔎 ROZPOCZYNAM WSPÓLNY SKAN "
            "OLX + VINTED"
        )

        try:

            all_results = await scan_both(
                olx_page,
                vinted_page
            )

            log.info(
                f"📦 Łącznie znaleziono: "
                f"{len(all_results)}"
            )

            new_count = 0

            if first_scan:

                for offer in all_results:

                    offer_url = offer.get(
                        "url"
                    )

                    if offer_url:
                        known.add(
                            offer_url
                        )

                first_scan = False

                log.info(
                    f"🟢 Pierwszy skan: "
                    f"zapisano {len(known)} ofert."
                )

            else:

                for offer in all_results:

                    offer_url = offer.get(
                        "url"
                    )

                    if not offer_url:
                        continue

                    if offer_url in known:
                        continue

                    known.add(
                        offer_url
                    )

                    new_count += 1

                    send_discord(
                        title=offer.get(
                            "title",
                            "Nowe ogłoszenie"
                        ),
                        price=offer.get(
                            "price",
                            "Brak ceny"
                        ),
                        url=offer_url,
                        image=offer.get(
                            "image",
                            ""
                        ),
                        source=offer.get(
                            "source",
                            ""
                        )
                    )

                    await asyncio.sleep(
                        0.5
                    )

            log.info(
                f"🆕 Nowych ofert: "
                f"{new_count}"
            )

        except Exception as e:

            log.exception(
                f"❌ Błąd wspólnego skanu: {e}"
            )

        elapsed = (
            time.monotonic()
            - cycle_start
        )

        wait_time = max(
            0,
            SCAN_INTERVAL - elapsed
        )

        log.info(
            f"⏱️ Następny skan za "
            f"{wait_time:.1f} sekund"
        )

        await asyncio.sleep(
            wait_time
        )
```

# ============================================================

# START

# ============================================================

if **name** == "**main**":

```
web_thread = threading.Thread(
    target=start_web_server,
    daemon=True
)

web_thread.start()

asyncio.run(
    run_bot()
)
```
