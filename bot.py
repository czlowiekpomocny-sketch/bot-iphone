import os
import asyncio
import logging
import threading
import time
import re

import requests
from flask import Flask
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ============================================================

# KONFIGURACJA

# ============================================================

SCAN_INTERVAL = 15

# Jedno wyszukiwanie na portal:

# pobieramy najnowsze oferty i filtrujemy iPhone 11-17

SEARCH_TEXT = "iphone"

# Ile najnowszych ofert pobieramy z każdego portalu

MAX_RESULTS_PER_PORTAL = 50

# Maksymalny czas oczekiwania Playwright

PLAYWRIGHT_TIMEOUT = 12000

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

color = 3066993 if source == "OLX" else 3447003

embed = {
    "title": (title or "Nowe ogłoszenie")[:256],
    "url": url,
    "color": color,
    "description": (
        f"💰 **Cena:** {price or 'Brak ceny'}\n"
        f"🌐 **Źródło:** {source}\n"
        f"📱 **Model:** iPhone 11–17"
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
            f"🟢 Discord [{source}] -> "
            f"{(title or 'Oferta')[:60]}"
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

# ============================================================

# WIADOMOŚĆ TESTOWA

# ============================================================

def send_test_message():
webhook = get_webhook()

```
if not webhook:
    log.error("❌ DISCORD_WEBHOOK nie istnieje.")
    return False

payload = {
    "embeds": [
        {
            "title": "🟢 iPhone Flip Bot — TEST",
            "description": (
                "Bot uruchomił się poprawnie.\n\n"
                "🔎 OLX + Vinted\n"
                "📱 iPhone 11–17\n"
                "⏱️ Wspólny skan co 15 sekund"
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
        log.info("🟢 Discord: wiadomość testowa wysłana")
        return True

    log.error(
        f"❌ Discord test HTTP {response.status_code}: "
        f"{response.text[:300]}"
    )

except Exception as e:
    log.error(f"❌ Discord test error: {e}")

return False
```

# ============================================================

# FILTR IPHONE 11-17

# ============================================================

def is_target_iphone(title):
"""
Zwraca True tylko dla iPhone 11, 12, 13, 14, 15, 16 lub 17.

```
Akceptuje np.:
iPhone 11
iPhone 11 Pro
iPhone 12 Pro Max
iPhone 13 mini
iPhone 14 Pro
iPhone 15 Plus
iPhone 16 Pro Max
iPhone 17
"""

if not title:
    return False

text = title.lower()

# Normalizacja
text = text.replace("-", " ")
text = re.sub(r"\s+", " ", text)

# Musi wystąpić słowo iphone
if "iphone" not in text:
    return False

# Szukamy numeru modelu 11-17
match = re.search(
    r"\biphone\s+(11|12|13|14|15|16|17)\b",
    text
)

return match is not None
```

# ============================================================

# POMOCNICZE

# ============================================================

def clean_url(base, href):
if not href:
return ""

```
href = href.strip()

if href.startswith("/"):
    return base + href.split("?")[0]

return href.split("?")[0]
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
    "q-iphone/"
    "?search%5Border%5D=created_at:desc"
)

log.info("🔎 OLX: szukam najnowszych ofert iPhone")

try:
    await page.goto(
        url,
        wait_until="commit",
        timeout=PLAYWRIGHT_TIMEOUT
    )

    await page.wait_for_timeout(1500)

    # OLX może używać różnych struktur kart.
    cards = page.locator('[data-cy="l-card"]')

    card_count = await cards.count()

    log.info(
        f"OLX: parser widzi {card_count} kart"
    )

    for i in range(min(card_count, MAX_RESULTS_PER_PORTAL)):
        try:
            card = cards.nth(i)

            # URL
            links = card.locator("a")
            link_count = await links.count()

            if link_count == 0:
                continue

            href = await links.first.get_attribute("href")

            if not href or "/d/oferta/" not in href:
                continue

            full_url = clean_url(
                "https://www.olx.pl",
                href
            )

            # Tytuł
            title = ""

            for selector in ["h6", "h4", "[data-cy='ad-card-title']"]:
                elem = card.locator(selector).first

                if await elem.count() > 0:
                    try:
                        title = await elem.inner_text()
                        if title.strip():
                            break
                    except Exception:
                        pass

            if not title:
                try:
                    title = await links.first.inner_text()
                except Exception:
                    title = "Ogłoszenie OLX"

            title = title.strip()

            # Filtr 11-17
            if not is_target_iphone(title):
                continue

            # Cena
            price = "Brak ceny"

            price_elem = card.locator(
                '[data-testid="ad-price"]'
            )

            if await price_elem.count() > 0:
                try:
                    price = (
                        await price_elem.first.inner_text()
                    ).strip()
                except Exception:
                    pass

            # Zdjęcie
            image = ""

            img = card.locator("img").first

            if await img.count() > 0:
                try:
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
        f"pasujących iPhone 11–17"
    )

except PlaywrightTimeoutError:
    log.warning(
        "🟡 OLX: timeout — pomijam ten cykl"
    )

except Exception as e:
    log.warning(
        f"🟡 OLX błąd: {type(e).__name__}: {e}"
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
    "?search_text=iphone"
    "&order=newest_first"
)

log.info("🔎 Vinted: szukam najnowszych ofert iPhone")

try:
    await page.goto(
        url,
        wait_until="commit",
        timeout=PLAYWRIGHT_TIMEOUT
    )

    await page.wait_for_timeout(2000)

    # Główna struktura Vinted
    items = page.locator(
        '[data-testid="grid-item"]'
    )

    item_count = await items.count()

    log.info(
        f"Vinted: parser widzi {item_count} ofert"
    )

    for i in range(min(item_count, MAX_RESULTS_PER_PORTAL)):
        try:
            item = items.nth(i)

            links = item.locator("a")
            link_count = await links.count()

            if link_count == 0:
                continue

            link = links.first

            href = await link.get_attribute("href")

            if not href or "/items/" not in href:
                continue

            full_url = clean_url(
                "https://www.vinted.pl",
                href
            )

            # Tytuł
            title = await link.get_attribute("title")

            if not title:
                try:
                    title = await item.inner_text()
                except Exception:
                    title = ""

            if not title:
                title = "Ogłoszenie Vinted"

            # Vinted czasami zwraca kilka linii.
            title_lines = [
                line.strip()
                for line in title.split("\n")
                if line.strip()
            ]

            title = (
                title_lines[0]
                if title_lines
                else "Ogłoszenie Vinted"
            )

            # Filtr 11-17
            if not is_target_iphone(title):
                continue

            # Cena
            price = "Brak ceny"

            price_elem = item.locator(
                '[data-testid*="price"]'
            )

            if await price_elem.count() > 0:
                try:
                    price = (
                        await price_elem.first.inner_text()
                    ).strip()
                except Exception:
                    pass

            # Zdjęcie
            image = ""

            img = item.locator("img").first

            if await img.count() > 0:
                try:
                    image = (
                        await img.get_attribute("src")
                        or ""
                    )
                except Exception:
                    pass

            found.append(
                {
                    "source": "Vinted",
                    "url": full_url,
                    "title": title,
                    "price": price,
                    "image": image
                }
            )

        except Exception:
            continue

    log.info(
        f"🟢 Vinted: znaleziono {len(found)} "
        f"pasujących iPhone 11–17"
    )

except PlaywrightTimeoutError:
    log.warning(
        "🟡 Vinted: timeout — pomijam ten cykl"
    )

except Exception as e:
    log.warning(
        f"🟡 Vinted błąd: {type(e).__name__}: {e}"
    )

return found
```

# ============================================================

# RÓWNOCZESNY SKAN

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
        f"❌ OLX: {results[0]}"
    )
else:
    olx_results = results[0]

if isinstance(results[1], Exception):
    log.error(
        f"❌ Vinted: {results[1]}"
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
    log.error(
        "❌ Render → Environment → "
        "DISCORD_WEBHOOK"
    )
    return

log.info("======================================")
log.info("📱 IPHONE FLIP BOT")
log.info("🟢 OLX + VINTED")
log.info("🟢 iPhone 11–17")
log.info("🟢 NAJNOWSZE OFERTY")
log.info("⏱️ WSPÓLNY SKAN CO 15 SEKUND")
log.info("======================================")

# Test Discord
send_test_message()

# Tutaj trzymamy URL-e już widzianych ofert
known = set()

# Pierwszy skan tylko buduje bazę.
# Nie wysyłamy starych ofert.
first_scan = True

async with async_playwright() as p:

    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled"
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

    while True:

        cycle_start = time.monotonic()

        log.info(
            "======================================"
        )

        log.info(
            "🔎 ROZPOCZYNAM WSPÓLNY SKAN"
        )

        try:

            all_results = await scan_both(
                olx_page,
                vinted_page
            )

            # Usuwamy duplikaty URL
            unique = {}

            for offer in all_results:

                url = offer.get("url")

                if url:
                    unique[url] = offer

            all_results = list(unique.values())

            log.info(
                f"📦 Łącznie pasujących ofert: "
                f"{len(all_results)}"
            )

            new_count = 0

            # ==========================================
            # PIERWSZY SKAN
            # ==========================================

            if first_scan:

                for offer in all_results:

                    url = offer.get("url")

                    if url:
                        known.add(url)

                first_scan = False

                log.info(
                    f"🟢 Baza początkowa: "
                    f"{len(known)} ofert"
                )

                log.info(
                    "🟢 Stare oferty NIE zostaną wysłane."
                )

            # ==========================================
            # KOLEJNE SKANY
            # ==========================================

            else:

                for offer in all_results:

                    url = offer.get("url")

                    if not url:
                        continue

                    if url in known:
                        continue

                    known.add(url)

                    new_count += 1

                    log.info(
                        f"🆕 NOWA OFERTA: "
                        f"{offer.get('title', '')}"
                    )

                    send_discord(
                        title=offer.get(
                            "title",
                            "Nowe ogłoszenie"
                        ),
                        price=offer.get(
                            "price",
                            "Brak ceny"
                        ),
                        url=url,
                        image=offer.get(
                            "image",
                            ""
                        ),
                        source=offer.get(
                            "source",
                            ""
                        )
                    )

                    # Mała przerwa między wiadomościami
                    await asyncio.sleep(0.5)

            log.info(
                f"🆕 Nowych ofert w tym skanie: "
                f"{new_count}"
            )

        except Exception as e:

            log.exception(
                f"❌ Błąd wspólnego skanu: {e}"
            )

        # ==============================================
        # CZEKAJ DO KOLEJNEGO CYKLU
        # ==============================================

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
```
