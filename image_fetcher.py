"""
trendboard.fyi — Product Image Fetcher
=======================================
Two-track image strategy:

  CATEGORY images (generic lifestyle shots)
  ─────────────────────────────────────────
  Source: hardcoded Unsplash URLs, one per category type.
  These never change — "Moisturizer" always shows the same
  beautiful unbranded flatlay. Zero API calls. No key needed.

  PRODUCT images (specific branded product shots)
  ────────────────────────────────────────────────
  Source: Google Custom Search API (image mode) searching a
  curated list of retailer sites (Amazon, Sephora, Ulta, etc.).
  Fetched once per pipeline run; cached in skincare_billboard.json.

Cost: ~$0/week (free tier = 100 queries/day; we use ~25/week)

Setup (one-time):
  1. https://programmablesearchengine.google.com
     → Add sites: www.amazon.com/*, www.sephora.com/*,
       www.ulta.com/*, www.target.com/*, www.walmart.com/*,
       www.dermstore.com/*, www.lookfantastic.com/*
     → Enable Image Search
     → Copy the Search Engine ID → GOOGLE_CSE_CX in .env

  2. https://console.cloud.google.com
     → APIs & Services → Custom Search API → Enable
     → Credentials → Create API Key → GOOGLE_CSE_API_KEY in .env
"""

import os
import json
import time
import logging
import urllib.request
import urllib.parse
import urllib.error
from safety import is_test_mode

logger = logging.getLogger(__name__)

GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX      = os.getenv("GOOGLE_CSE_CX", "")

# ── CATEGORY IMAGES — permanent Unsplash URLs ─────────────────────────────────
# Generic, unbranded lifestyle/flatlay shots. One per category type.
# These are used in BOTH test and live mode — no API call ever needed.
# To update: replace the Unsplash photo ID (the long number after "photo-").
def _unsplash(photo_id: str) -> str:
    """Proxy an Unsplash photo through wsrv.nl for reliable, CORS-safe delivery."""
    return f"https://wsrv.nl/?url=images.unsplash.com/{photo_id}&w=500&h=500&fit=cover&output=webp"

# All photo IDs verified HTTP 200 as of 2026-05-23.
# To replace a broken one: find a new ID on unsplash.com, curl-test it, update here.
CATEGORY_IMAGES = {
    "moisturizer":         _unsplash("photo-1556228720-195a672e8a03"),  # pastel cream jar
    "serum":               "https://wsrv.nl/?url=plus.unsplash.com/premium_photo-1674739375749-7efe56fc8bbb&w=500&h=500&fit=cover&output=webp",
    "cleanser":            _unsplash("photo-1556228578-8c89e6adf883"),   # foam cleanser
    "sunscreen":           _unsplash("photo-1505944270255-72b8c68c6a70"),  # SPF lotion
    "toner":               "https://wsrv.nl/?url=plus.unsplash.com/premium_photo-1673628551192-ca9aca8b57f0&w=500&h=500&fit=cover&output=webp",
    "exfoliant":           "https://wsrv.nl/?url=plus.unsplash.com/premium_photo-1677850271710-49fda851db22&w=500&h=500&fit=cover&output=webp",
    "retinoid":            _unsplash("photo-1596755389378-c31d21fd1273"),  # night cream
    "eye_treatment":       _unsplash("photo-1512290923902-8a9f81dc236c"),  # eye area
    "mask":                _unsplash("photo-1596462502278-27bfdc403348"),  # face mask
    "face_oil":            _unsplash("photo-1608248543803-ba4f8c70ae0b"),  # dropper oil
    "led_device":          _unsplash("photo-1598440947619-2c35fc9aa908"),  # skincare device
    "lip_care":            _unsplash("photo-1599305445671-ac291c95aaa9"),  # lip product
    "body_care":           _unsplash("photo-1471107340929-a87cd0f5b5f3"),  # body lotion
    "microcurrent":        "https://wsrv.nl/?url=plus.unsplash.com/premium_photo-1734468965603-d26738eb6ed0&w=500&h=500&fit=cover&output=webp",  # woman holding compact device
    "microcurrent_device": "https://wsrv.nl/?url=plus.unsplash.com/premium_photo-1734468965603-d26738eb6ed0&w=500&h=500&fit=cover&output=webp",
    "foundation":          _unsplash("photo-1522335789203-aabd1fc54bc9"),  # makeup flatlay
    "foundation_base":     _unsplash("photo-1522335789203-aabd1fc54bc9"),
    "spf":                 _unsplash("photo-1505944270255-72b8c68c6a70"),
    "essence":             "https://wsrv.nl/?url=plus.unsplash.com/premium_photo-1674739375749-7efe56fc8bbb&w=500&h=500&fit=cover&output=webp",
    "serum_essence":       "https://wsrv.nl/?url=plus.unsplash.com/premium_photo-1674739375749-7efe56fc8bbb&w=500&h=500&fit=cover&output=webp",
}

# ── TEST-MODE product image fallbacks ─────────────────────────────────────────
# Used when TEST_MODE=true so the UI looks real without API calls.
# Keys: lowercase "{brand} {product_name}"
TEST_PRODUCT_IMAGES = {
    "anua heartleaf 77% soothing toner":          "https://wsrv.nl/?url=m.media-amazon.com/images/I/61eSsB5AHmL._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
    "cerave moisturizing cream":                   "https://wsrv.nl/?url=m.media-amazon.com/images/I/61S7BrCBj7L._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
    "the ordinary niacinamide 10% + zinc 1%":      "https://wsrv.nl/?url=m.media-amazon.com/images/I/612wRN1gVsL._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
    "la roche-posay anthelios melt-in sunscreen":  "https://wsrv.nl/?url=m.media-amazon.com/images/I/71lZoiAoJML._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
    "paula's choice skin perfecting 2% bha":       "https://wsrv.nl/?url=m.media-amazon.com/images/I/71Z7d4Og5bL._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
    "cosrx advanced snail 96 mucin power essence": "https://wsrv.nl/?url=m.media-amazon.com/images/I/71yMXTNcGqL._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
    "drunk elephant protini polypeptide cream":    "https://wsrv.nl/?url=m.media-amazon.com/images/I/61dvSuSsJAL._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
    "laneige lip sleeping mask":                   "https://wsrv.nl/?url=m.media-amazon.com/images/I/71EHnBNFSLL._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
    "tatcha the water cream":                      "https://wsrv.nl/?url=m.media-amazon.com/images/I/71k+h3FujZL._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
    "neutrogena hydro boost water gel":            "https://wsrv.nl/?url=m.media-amazon.com/images/I/71NjTTk9t0L._SL500_.jpg&w=300&h=300&fit=cover&output=webp",
}


# ── DUCKDUCKGO IMAGE SEARCH — product images ──────────────────────────────────
# Free, no API key, no account required.
# Uses DDG's unofficial image search endpoint (same engine that powers the
# Images tab on duckduckgo.com). Stable since 2019; no known rate limits at
# our usage level (25 queries/week).

import re as _re

_DDG_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://duckduckgo.com/",
}

# Retailer domains to prefer when picking image results.
# Results whose *page* URL comes from these domains get priority over
# random blogs, Pinterest, Reddit, etc.
_PREFERRED_DOMAINS = (
    "amazon.com", "sephora.com", "ulta.com", "target.com",
    "walmart.com", "dermstore.com", "lookfantastic.com",
    "cerave.com", "neutrogena.com", "laroche-posay.com",
    "theordinary.com", "paulaschoice.com", "cosrx.com",
)

def _wsrv(image_url: str) -> str:
    """Wrap an image URL in wsrv.nl proxy. Handles encoding correctly."""
    params = urllib.parse.urlencode({
        "url":    image_url,
        "w":      300,
        "h":      300,
        "fit":    "cover",
        "output": "webp",
    })
    return f"https://wsrv.nl/?{params}"


def _ddg_image_search(query: str, fallback_query: str = "") -> str:
    """
    Searches DuckDuckGo Images for a product photo.
    Returns a wsrv.nl-proxied HTTPS URL, or "" on failure.

    Flow:
      1. GET duckduckgo.com/?q=... → extract the session token (vqd)
      2. GET duckduckgo.com/i.js?q=...&vqd=... → JSON image results
      3. Prefer results from known retailer domains; fall back to any HTTPS image
      4. Proxy final URL through wsrv.nl
    """
    for attempt, q in enumerate([query, fallback_query]):
        if not q:
            continue
        try:
            # ── Step 1: get vqd session token ────────────────────────────────
            encoded_q = urllib.parse.quote_plus(q)
            init_url  = f"https://duckduckgo.com/?q={encoded_q}&iax=images&ia=images"
            req = urllib.request.Request(init_url, headers=_DDG_HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            # vqd token — try four patterns in order of specificity
            vqd_match = (
                _re.search(r'vqd="([^"]+)"',         html) or
                _re.search(r"vqd='([^']+)'",          html) or
                _re.search(r'data-vqd="([^"]+)"',     html) or
                _re.search(r'vqd=([\w\-]+)',           html)   # widened: was [\d-]+
            )
            if not vqd_match:
                logger.warning(f"DDG: vqd token not found for '{q}' — possible bot-challenge page")
                continue
            vqd = vqd_match.group(1)

            # ── Step 2: fetch image results ───────────────────────────────────
            params = urllib.parse.urlencode({
                "q":   q,
                "vqd": vqd,
                "p":   "1",
                "s":   "0",
                "f":   ",,,",
                "l":   "us-en",
                "o":   "json",
            })
            img_req = urllib.request.Request(
                f"https://duckduckgo.com/i.js?{params}",
                headers={**_DDG_HEADERS, "Accept": "application/json"},
            )
            with urllib.request.urlopen(img_req, timeout=12) as resp:
                data = json.loads(resp.read())

            results = data.get("results", [])[:15]

            # ── Step 3a: prefer images from known retailer pages ──────────────
            for result in results:
                page_url = result.get("url", "")
                img_url  = result.get("image", "")
                if img_url.startswith("https://") and any(d in page_url for d in _PREFERRED_DOMAINS):
                    logger.debug(f"  DDG: retailer hit — {page_url[:60]}")
                    return _wsrv(img_url)

            # ── Step 3b: fall back to any HTTPS image ─────────────────────────
            for result in results:
                img_url = result.get("image", "")
                if img_url.startswith("https://"):
                    logger.debug(f"  DDG: generic hit — {img_url[:60]}")
                    return _wsrv(img_url)

        except Exception as e:
            logger.warning(f"DDG image search error for '{q}': {e}")

        if attempt == 0:
            time.sleep(1.5)   # pause before trying fallback query

    return ""


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def fetch_category_image(type_id: str, type_label: str = "") -> str:
    """
    Returns a permanent Unsplash lifestyle image for a product category.
    No API call — URL is hardcoded. Works in both test and live mode.

    Args:
        type_id:    e.g. "moisturizer"
        type_label: e.g. "Moisturizer" (unused, kept for interface compat)
    """
    url = CATEGORY_IMAGES.get(type_id, "")
    if url:
        logger.debug(f"  [category] {type_id} → Unsplash ✓")
    else:
        logger.warning(f"  [category] no Unsplash URL for type_id='{type_id}' — add to CATEGORY_IMAGES")
    return url


def fetch_product_image(brand: str, product_name: str,
                        product_type_label: str = "") -> str:
    """
    Returns the best image URL for a specific branded product.

    TEST_MODE: returns a hardcoded wsrv.nl URL from TEST_PRODUCT_IMAGES (no API).
    LIVE_MODE: searches DuckDuckGo Images — free, no key required.

    Args:
        brand:              e.g. "CeraVe"
        product_name:       e.g. "Moisturizing Cream"
        product_type_label: e.g. "Moisturizer" (used in fallback query)
    """
    # ── Deduplicate brand prefix ──────────────────────────────────────────────
    # Guard against product_name already containing the brand
    # e.g. brand="Foreo", product_name="Foreo Microcurrent Device"
    # → clean_name="Microcurrent Device" → full_name="Foreo Microcurrent Device"
    clean_name = product_name.strip()
    if clean_name.lower().startswith(brand.strip().lower()):
        clean_name = clean_name[len(brand.strip()):].strip()
    full_name = f"{brand.strip()} {clean_name}".strip()

    # ── TEST MODE ─────────────────────────────────────────────────────────────
    if is_test_mode():
        key = full_name.lower()
        url = TEST_PRODUCT_IMAGES.get(key, "")
        if url:
            logger.debug(f"  [test] product image: {key}")
        return url

    # ── LIVE MODE — DuckDuckGo image search ──────────────────────────────────
    # Exclude social/lifestyle sites that dominate generic results
    exclusions = "-pinterest -reddit -instagram -tumblr"
    primary  = f"{full_name} skincare product {exclusions}"
    fallback = f"{full_name} {product_type_label} {exclusions}" if product_type_label else f"{full_name} buy"

    logger.info(f"  Fetching product image: {full_name}")
    url = _ddg_image_search(primary, fallback)
    time.sleep(1.0)     # polite delay between products
    return url


def enrich_categories_with_images(categories: list[dict]) -> list[dict]:
    """
    Adds category_image to each ranked category dict using permanent Unsplash URLs.
    Never makes an API call — instant, always works.
    """
    logger.info(f"\n  Assigning category images ({len(categories)} categories)…")
    for cat in categories:
        type_id    = cat.get("type_id", "")
        type_label = cat.get("type_label", "")
        url = fetch_category_image(type_id, type_label)
        cat["category_image"] = url
        logger.info(f"  {type_label:20s} → {'✓ ' + type_id if url else '✗ missing type_id'}")
    return categories


def enrich_products_with_images(products: list[dict]) -> list[dict]:
    """
    Adds image_url to each product dict.
    TEST_MODE: uses hardcoded fallbacks.
    LIVE_MODE: queries Google CSE for exact branded product shots.
    Skips products that already have an image_url.
    """
    logger.info(f"\n  Fetching product images ({len(products)} products)…")
    for i, p in enumerate(products):
        brand      = p.get("brand", "")
        name       = p.get("product_name", "")
        type_label = p.get("product_type_label", "")
        existing   = p.get("image_url", "")

        if existing:
            logger.debug(f"  [{i+1}] already has image — skipping")
            continue

        url = fetch_product_image(brand, name, type_label)
        p["image_url"] = url
        logger.info(f"  [{i+1}] {brand} {name} → {'✓' if url else '✗ no image'}")

    found = sum(1 for p in products if p.get("image_url"))
    logger.info(f"  Images found: {found}/{len(products)}")
    return products
