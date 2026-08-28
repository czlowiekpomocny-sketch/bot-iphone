import os
import asyncio
import logging
import random
import threading
import time
from urllib.parse import quote

import requests
from flask import Flask
from playwright.async_api import async_playwright

# ============================================================

# KONFIGURACJA

# ============================================================

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# Wspólny interwał skanowania

SCAN_INTERVAL = 15

SEARCHES = [
"iphone 11",
"iphone 12",
"iphone 13",
"iphone 14",
"iphone 15"
]

MAX_RESULTS_PER_SEARCH = 15

# ============================================================

# LOGOWANIE I FLASK

# ============================================================

logging.basicConfig(
level=logging.INFO,
format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("iphone-bot")

app = Flask(**name**)

@app.route("/")
def home():
return "iPhone Flip Bot działa."

def start_web_server():
port = int(os.environ.get("PORT", 10000))
app.run(
host="0.0.0.0",
port=port,
debug=False,
use_reloader=False
)

# ============================================================

# DISCORD

# ============================================================

def send_discord(title, price, url, image=None, source=""):
webhook = os.getenv("DISCORD_WEBHOOK")

```
if not webhook:
    log.error("❌ Brak DISCORD_WEBHOOK w zmiennych środowiskowych.")
    return False

embed = {
    "title": title[:256] if title else "Nowe ogłoszenie",
    "url": url,
    "color": 5814783 if source == "OLX" else 65490,
    "description": (
        f"💰 **Cena:** {price or 'Brak informacji'}\n"
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
            f"✅ Discord [{source}]: wysłano -> {title[:30]}"
        )
        return True

    log.error(
        f"❌ Discord HTTP {response.status_code}: "
        f"{response.text[:200]}"
    )

except Exception as e:
    log.error(f"❌ Discord error: {e}")

return False
```

# ============================================================

# OLX

# ============================================================

async def scan_olx(page):
found = []

```
for search in SEARCHES:
    try:
        url = (
            "https://www.olx.pl/d/elektronika/telefony/"
            f"telefony-komorkowe/q-{quote(search)}/"
            "?search%5Border%5D=created_at:desc"
        )

        log.info(f"OLX: Skanuję '{search}'")

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(
            random.randint(1000, 2000)
        )

        cards = await page.locator(
            '[data-cy="l-card"]'
        ).all()

        count = 0

        for card in cards:
            try:
                link_elem = card.locator("a").first

                href = await link_elem.get_attribute("href")

                if not href or "/d/oferta/" not in href:
                    continue

                if href.startswith("/"):
                    full_url = "https://www.olx.pl" + href
                else:
                    full_url = href.split("?")[0]

                title_elem = card.locator("h6, h4").first

                title = (
                    await title_elem.inner_text()
                    if await title_elem.count() > 0
                    else "Ogłoszenie OLX"
                )

                price_elem = card.locator(
                    '[data-testid="ad-price"]'
                )

                price = (
                    await price_elem.inner_text()
                    if await price_elem.count() > 0
                    else "Brak ceny"
                )

                img_elem = card.locator("img").first

                image = (
                    await img_elem.get_attribute("src")
                    if await img_elem.count() > 0
                    else ""
                )

                found.append({
                    "source": "OLX",
                    "url": full_url,
                    "title": title.strip(),
                    "price": price.strip(),
                    "image": image
                })

                count += 1

                if count >= MAX_RESULTS_PER_SEARCH:
                    break

            except Exception:
                continue

        log.info(
            f"OLX '{search}': Znaleziono {count} ofert"
        )

    except Exception as e:
        log.warning(
            f"⚠️ OLX '{search}' błąd: {e}"
        )

log.info(
    f"OLX: znaleziono łącznie {len(found)} ofert"
)

return found
```

# ============================================================

# VINTED

# ============================================================

async def scan_vinted(page):
found = []

```
for search in SEARCHES:
    try:
        url = (
            "https://www.vinted.pl/catalog"
            f"?search_text={quote(search)}"
            "&order=newest_first"
        )

        log.info(f"Vinted: Skanuję '{search}'")

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        await page.wait_for_timeout(
            random.randint(1000, 2000)
        )

        items = await page.locator(
            '[data-testid="grid-item"]'
        ).all()

        count = 0

        for item in items:
            try:
                link_elem = item.locator("a").first

                href = await link_elem.get_attribute("href")

                if not href or "/items/" not in href:
                    continue

                if href.startswith("/"):
                    full_url = (
                        "https://www.vinted.pl" + href
                    )
                else:
                    full_url = href.split("?")[0]

                title = await link_elem.get_attribute(
                    "title"
                )

                if not title:
                    title = await item.inner_text()

                price_elem = item.locator(
                    '[data-testid*="price"]'
                )

                price = (
                    await price_elem.inner_text()
                    if await price_elem.count() > 0
                    else "Brak ceny"
                )

                img_elem = item.locator("img").first

                image = (
                    await img_elem.get_attribute("src")
                    if await img_elem.count() > 0
                    else ""
                )

                found.append({
                    "source": "Vinted",
                    "url": full_url,
                    "title": (
                        title.split("\n")[0].strip()
                        if title
                        else "Ogłoszenie Vinted"
                    ),
                    "price": price.strip(),
                    "image": image
                })

                count += 1

                if count >= MAX_RESULTS_PER_SEARCH:
                    break

            except Exception:
                continue

        log.info(
            f"Vinted '{search}': Znaleziono {count} ofert"
        )

    except Exception as e:
        log.warning(
            f"⚠️ Vinted '{search}' błąd: {e}"
        )

log.info(
    f"Vinted: znaleziono łącznie {len(found)} ofert"
)

return found
```

# ============================================================

# WSPÓLNY SKAN OLX + VINTED

# ============================================================

async def scan_both(olx_page, vinted_page):
log.info(
"🔎 OLX + VINTED — WSPÓLNY SKAN"
)

```
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

olx_results = (
    results[0]
    if not isinstance(results[0], Exception)
    else []
)

vinted_results = (
    results[1]
    if not isinstance(results[1], Exception)
    else []
)

if isinstance(results[0], Exception):
    log.error(
        f"❌ Błąd skanowania OLX: {results[0]}"
    )

if isinstance(results[1], Exception):
    log.error(
        f"❌ Błąd skanowania Vinted: {results[1]}"
    )

return olx_results + vinted_results
```

# ============================================================

# GŁÓWNA PĘTLA

# ============================================================

async def run_bot():

```
webhook = os.getenv("DISCORD_WEBHOOK")

if not webhook:
    log.error(
        "❌ DISCORD_WEBHOOK nie jest dostępny "
        "dla procesu bota."
    )
    log.error(
        "❌ Sprawdź Render Environment i wykonaj "
        "nowy deploy."
    )
    return

log.info("======================================")
log.info("📱 IPHONE FLIP BOT")
log.info("OLX + VINTED")
log.info("Oba portale równocześnie co 15 sekund")
log.info("======================================")

known = set()
first_scan = True

async with async_playwright() as p:

    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled"
        ]
    )

    context = await browser.new_context(
        viewport={
            "width": 1440,
            "height": 900
        },
        locale="pl-PL",
        timezone_id="Europe/Warsaw",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    )

    olx_page = await context.new_page()
    vinted_page = await context.new_page()

    while True:

        cycle_start = time.monotonic()

        log.info(
            "🔎 ROZPOCZYNAM WSPÓLNY SKAN OLX + VINTED"
        )

        try:
            all_results = await scan_both(
                olx_page,
                vinted_page
            )

            new_count = 0

            log.info(
                f"📦 Znaleziono łącznie: "
                f"{len(all_results)}"
            )

            if first_scan:

                for offer in all_results:
                    offer_url = offer.get("url")

                    if offer_url:
                        known.add(offer_url)

                first_scan = False

                log.info(
                    f"🟢 Pierwszy skan — zapisano "
                    f"{len(known)} istniejących ofert. "
                    f"Nie wysyłam ich."
                )

            else:

                for offer in all_results:

                    offer_url = offer.get("url")

                    if not offer_url:
                        continue

                    if offer_url in known:
                        continue

                    known.add(offer_url)

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

                    await asyncio.sleep(1)

            log.info(
                f"🆕 Nowych ofert: {new_count}"
            )

        except Exception as e:

            log.exception(
                f"❌ Błąd wspólnego skanu: {e}"
            )

        elapsed = time.monotonic() - cycle_start

        wait_time = max(
            0,
            SCAN_INTERVAL - elapsed
        )

        log.info(
            f"⏱️ Następny wspólny skan za "
            f"{wait_time:.1f} sekund"
        )

        await asyncio.sleep(wait_time)
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

asyncio.run(run_bot())
