import os
import asyncio
import logging
import threading
import time
import re
from urllib.parse import quote, urljoin

import requests
from flask import Flask
from playwright.async_api import async_playwright


# ============================================================
# KONFIGURACJA
# ============================================================

SCAN_INTERVAL = 15

# JEDNO WSPÓLNE WYSZUKIWANIE
SEARCH_TEXT = "iphone"

# Interesują nas iPhone 11-17
MIN_IPHONE = 11
MAX_IPHONE = 17

MAX_RESULTS_PER_SITE = 100

PLAYWRIGHT_TIMEOUT = 10000


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
    webhook = os.environ.get("DISCORD_WEBHOOK")

    if webhook:
        webhook = webhook.strip()

    return webhook


def send_discord(title, price, url, image=None, source=""):
    webhook = get_webhook()

    if not webhook:
        log.error("❌ Brak DISCORD_WEBHOOK.")
        return False

    embed = {
        "title": (title or "Nowe ogłoszenie")[:256],
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


# ============================================================
# WIADOMOŚĆ TESTOWA
# ============================================================

def send_test_message():
    webhook = get_webhook()

    if not webhook:
        log.error("❌ Brak DISCORD_WEBHOOK.")
        return False

    payload = {
        "embeds": [
            {
                "title": "🟢 iPhone Flip Bot — TEST",
                "description": (
                    "Bot uruchomił się poprawnie.\n\n"
                    "🔎 Wspólne wyszukiwanie: iPhone\n"
                    "📱 Modele: iPhone 11–17\n"
                    "🌐 OLX + Vinted\n"
                    "⏱️ Skan co 15 sekund"
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
            log.info("✅ Discord: wiadomość testowa wysłana")
            return True

        log.error(
            f"❌ Discord test HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    except Exception as e:
        log.error(f"❌ Discord test error: {e}")

    return False


# ============================================================
# SPRAWDZANIE CZY TO IPHONE 11-17
# ============================================================

def is_target_iphone(title):
    if not title:
        return False

    text = title.lower()

    # Musi wystąpić "iphone"
    if "iphone" not in text:
        return False

    # Szukamy numeru modelu 11-17
    matches = re.findall(r"\b(1[1-7])\b", text)

    for number in matches:
        model = int(number)

        if MIN_IPHONE <= model <= MAX_IPHONE:
            return True

    return False


# ============================================================
# NORMALIZACJA URL
# ============================================================

def normalize_url(base, href):
    if not href:
        return ""

    href = href.strip()

    if href.startswith("javascript:"):
        return ""

    full_url = urljoin(base, href)

    # Usuwamy parametry śledzące
    full_url = full_url.split("?")[0]

    return full_url


# ============================================================
# OLX
# ============================================================

async def scan_olx(page):
    found = []

    url = (
        "https://www.olx.pl/d/elektronika/telefony/"
        "telefony-komorkowe/"
        f"q-{quote(SEARCH_TEXT)}/"
        "?search%5Border%5D=created_at:desc"
    )

    log.info("OLX: sprawdzam iphone")

    try:
        await page.goto(
            url,
            wait_until="commit",
            timeout=PLAYWRIGHT_TIMEOUT
        )

        await page.wait_for_timeout(2500)

        # ----------------------------------------------------
        # OLX: najpierw próbujemy stary selektor
        # ----------------------------------------------------

        cards = await page.locator(
            '[data-cy="l-card"]'
        ).all()

        log.info(
            f"OLX: parser l-card widzi {len(cards)} kart"
        )

        # ----------------------------------------------------
        # JEŚLI 0 — używamy alternatywnego parsera
        # ----------------------------------------------------

        if not cards:
            cards = await page.locator(
                'a[href*="/d/oferta/"]'
            ).all()

            log.info(
                f"OLX: alternatywny parser widzi "
                f"{len(cards)} linków ofert"
            )

            seen = set()

            for link in cards:
                try:
                    href = await link.get_attribute("href")

                    full_url = normalize_url(
                        "https://www.olx.pl",
                        href
                    )

                    if not full_url:
                        continue

                    if "/d/oferta/" not in full_url:
                        continue

                    if full_url in seen:
                        continue

                    seen.add(full_url)

                    title = await link.inner_text()

                    title = " ".join(
                        (title or "").split()
                    )

                    if not is_target_iphone(title):
                        continue

                    # Szukamy ceny w rodzicu/linku
                    parent = link.locator("xpath=..")

                    parent_text = ""

                    try:
                        parent_text = await parent.inner_text()
                    except Exception:
                        pass

                    price = "Brak ceny"

                    price_match = re.search(
                        r"(\d[\d\s]*)(?:\s*)(zł|PLN)",
                        parent_text,
                        re.IGNORECASE
                    )

                    if price_match:
                        price = (
                            price_match.group(1).strip()
                            + " "
                            + price_match.group(2)
                        )

                    image = ""

                    try:
                        img = link.locator("img").first

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
                            "title": title[:256],
                            "price": price,
                            "image": image
                        }
                    )

                    if len(found) >= MAX_RESULTS_PER_SITE:
                        break

                except Exception:
                    continue

            log.info(
                f"OLX: znaleziono {len(found)} poprawnych ofert"
            )

            return found

        # ----------------------------------------------------
        # NORMALNY PARSER KART OLX
        # ----------------------------------------------------

        seen = set()

        for card in cards:
            try:
                link_elem = card.locator(
                    'a[href*="/d/oferta/"]'
                ).first

                if await link_elem.count() == 0:
                    link_elem = card.locator("a").first

                if await link_elem.count() == 0:
                    continue

                href = await link_elem.get_attribute("href")

                full_url = normalize_url(
                    "https://www.olx.pl",
                    href
                )

                if not full_url:
                    continue

                if "/d/oferta/" not in full_url:
                    continue

                if full_url in seen:
                    continue

                seen.add(full_url)

                # Cały tekst karty
                try:
                    card_text = await card.inner_text()
                except Exception:
                    card_text = ""

                card_text = " ".join(
                    card_text.split()
                )

                # Tytuł
                title_elem = card.locator(
                    "h6, h5, h4, [data-cy='ad-card-title']"
                ).first

                if await title_elem.count() > 0:
                    title = await title_elem.inner_text()
                else:
                    title = card_text[:200]

                title = " ".join(
                    (title or "").split()
                )

                if not is_target_iphone(title):
                    continue

                # Cena
                price_elem = card.locator(
                    '[data-testid="ad-price"]'
                ).first

                if await price_elem.count() > 0:
                    price = await price_elem.inner_text()
                    price = " ".join(price.split())
                else:
                    price = "Brak ceny"

                    price_match = re.search(
                        r"(\d[\d\s]*)(?:\s*)(zł|PLN)",
                        card_text,
                        re.IGNORECASE
                    )

                    if price_match:
                        price = (
                            price_match.group(1).strip()
                            + " "
                            + price_match.group(2)
                        )

                # Obrazek
                image = ""

                try:
                    img_elem = card.locator("img").first

                    if await img_elem.count() > 0:
                        image = (
                            await img_elem.get_attribute("src")
                            or ""
                        )
                except Exception:
                    pass

                found.append(
                    {
                        "source": "OLX",
                        "url": full_url,
                        "title": title[:256],
                        "price": price,
                        "image": image
                    }
                )

                if len(found) >= MAX_RESULTS_PER_SITE:
                    break

            except Exception:
                continue

        log.info(
            f"OLX: znaleziono {len(found)} poprawnych ofert"
        )

    except Exception as e:
        log.warning(
            f"⚠️ OLX błąd: {type(e).__name__}: {e}"
        )

    return found


# ============================================================
# VINTED
# ============================================================

async def scan_vinted(page):
    found = []

    url = (
        "https://www.vinted.pl/catalog"
        f"?search_text={quote(SEARCH_TEXT)}"
        "&order=newest_first"
    )

    log.info("Vinted: sprawdzam iphone")

    try:
        await page.goto(
            url,
            wait_until="commit",
            timeout=PLAYWRIGHT_TIMEOUT
        )

        await page.wait_for_timeout(2500)

        # Najpierw obecny selektor
        items = await page.locator(
            '[data-testid="grid-item"]'
        ).all()

        log.info(
            f"Vinted: parser widzi {len(items)} kart"
        )

        # ----------------------------------------------------
        # ALTERNATYWNY PARSER JEŚLI GRID-ITEM ZNIKNIE
        # ----------------------------------------------------

        if not items:
            items = await page.locator(
                'a[href*="/items/"]'
            ).all()

            log.info(
                f"Vinted: alternatywny parser widzi "
                f"{len(items)} linków"
            )

        seen = set()

        for item in items:
            try:
                # ------------------------------------------------
                # Ustalamy link
                # ------------------------------------------------

                if await item.get_attribute("href"):
                    link_elem = item
                else:
                    link_elem = item.locator(
                        'a[href*="/items/"]'
                    ).first

                if await link_elem.count() == 0:
                    continue

                href = await link_elem.get_attribute("href")

                full_url = normalize_url(
                    "https://www.vinted.pl",
                    href
                )

                if not full_url:
                    continue

                if "/items/" not in full_url:
                    continue

                if full_url in seen:
                    continue

                seen.add(full_url)

                # ------------------------------------------------
                # Tytuł
                # ------------------------------------------------

                title = ""

                try:
                    title = await link_elem.get_attribute(
                        "title"
                    )
                except Exception:
                    pass

                if not title:
                    try:
                        title = await item.inner_text()
                    except Exception:
                        title = ""

                title = " ".join(
                    (title or "").split()
                )

                # ------------------------------------------------
                # WAŻNE:
                # Vinted potrafi mieć tytuł + cenę w jednym tekście.
                # Szukamy iphone 11-17 w całej karcie.
                # ------------------------------------------------

                if not is_target_iphone(title):
                    continue

                # ------------------------------------------------
                # Cena
                # ------------------------------------------------

                price = "Brak ceny"

                try:
                    price_elem = item.locator(
                        '[data-testid*="price"]'
                    ).first

                    if await price_elem.count() > 0:
                        price = await price_elem.inner_text()
                        price = " ".join(price.split())
                except Exception:
                    pass

                # Jeżeli selektor ceny nie działa
                if price == "Brak ceny":
                    price_match = re.search(
                        r"(\d[\d\s]*[,.]?\d*)\s*(zł|PLN)",
                        title,
                        re.IGNORECASE
                    )

                    if price_match:
                        price = (
                            price_match.group(1).strip()
                            + " "
                            + price_match.group(2)
                        )

                # ------------------------------------------------
                # Obrazek
                # ------------------------------------------------

                image = ""

                try:
                    img_elem = item.locator("img").first

                    if await img_elem.count() > 0:
                        image = (
                            await img_elem.get_attribute("src")
                            or ""
                        )
                except Exception:
                    pass

                found.append(
                    {
                        "source": "Vinted",
                        "url": full_url,
                        "title": title[:256],
                        "price": price,
                        "image": image
                    }
                )

                if len(found) >= MAX_RESULTS_PER_SITE:
                    break

            except Exception:
                continue

        log.info(
            f"Vinted: znaleziono {len(found)} poprawnych ofert"
        )

    except Exception as e:
        log.warning(
            f"⚠️ Vinted błąd: {type(e).__name__}: {e}"
        )

    return found


# ============================================================
# WSPÓLNY SKAN
# ============================================================

async def scan_both(olx_page, vinted_page):
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
            f"❌ OLX — błąd całego skanu: "
            f"{results[0]}"
        )
    else:
        olx_results = results[0]

    if isinstance(results[1], Exception):
        log.error(
            f"❌ Vinted — błąd całego skanu: "
            f"{results[1]}"
        )
    else:
        vinted_results = results[1]

    return olx_results + vinted_results


# ============================================================
# GŁÓWNA PĘTLA
# ============================================================

async def run_bot():
    webhook = get_webhook()

    if not webhook:
        log.error(
            "❌ DISCORD_WEBHOOK nie został znaleziony."
        )
        return

    log.info("======================================")
    log.info("📱 IPHONE FLIP BOT")
    log.info("OLX + VINTED")
    log.info("🔎 WSPÓLNE WYSZUKIWANIE: IPHONE")
    log.info("📱 MODELE: IPHONE 11–17")
    log.info("⏱️ SKAN CO 15 SEKUND")
    log.info("======================================")

    # Test Discorda — zostawiamy, skoro działa
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
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
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
                "🔎 ROZPOCZYNAM WSPÓLNY SKAN"
            )

            try:
                all_results = await scan_both(
                    olx_page,
                    vinted_page
                )

                # ------------------------------------------------
                # Usuwamy duplikaty po URL
                # ------------------------------------------------

                unique_results = []
                urls_in_cycle = set()

                for offer in all_results:
                    offer_url = offer.get("url")

                    if not offer_url:
                        continue

                    if offer_url in urls_in_cycle:
                        continue

                    urls_in_cycle.add(offer_url)
                    unique_results.append(offer)

                log.info(
                    f"📦 Łącznie poprawnych ofert: "
                    f"{len(unique_results)}"
                )

                # ------------------------------------------------
                # PIERWSZY SKAN
                # ------------------------------------------------

                if first_scan:

                    for offer in unique_results:
                        offer_url = offer.get("url")

                        if offer_url:
                            known.add(offer_url)

                    first_scan = False

                    log.info(
                        f"🟢 Pierwszy skan — zapisano "
                        f"{len(known)} istniejących ofert."
                    )

                    log.info(
                        "🟢 Istniejące oferty NIE zostaną wysłane "
                        "na Discord."
                    )

                # ------------------------------------------------
                # KOLEJNE SKANY
                # ------------------------------------------------

                else:

                    new_count = 0

                    for offer in unique_results:

                        offer_url = offer.get("url")

                        if not offer_url:
                            continue

                        if offer_url in known:
                            continue

                        known.add(offer_url)

                        new_count += 1

                        log.info(
                            f"🆕 NOWA OFERTA [{offer.get('source')}] "
                            f"{offer.get('title')}"
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

                        await asyncio.sleep(0.5)

                    log.info(
                        f"🆕 Nowych ofert w tym skanie: "
                        f"{new_count}"
                    )

                # ------------------------------------------------
                # OGRANICZENIE PAMIĘCI
                # ------------------------------------------------

                if len(known) > 5000:
                    known = set(
                        list(known)[-3000:]
                    )

            except Exception as e:

                log.exception(
                    f"❌ Błąd wspólnego skanu: {e}"
                )

            # ----------------------------------------------------
            # Czekamy do następnego pełnego cyklu
            # ----------------------------------------------------

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


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    asyncio.run(run_bot())
