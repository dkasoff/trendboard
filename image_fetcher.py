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
CATEGORY_IMAGES = {
    "moisturizer":    "https://images.unsplash.com/photo-1570194065650-d99fb4b8ccb0?w=500&q=85",
    "serum":          "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=500&q=85",
    "cleanser":       "https://images.unsplash.com/photo-1556228578-8c89e6adf883?w=500&q=85",
    "sunscreen":      "https://images.unsplash.com/photo-1556228852-80b6e5eeff06?w=500&q=85",
    "toner":          "https://images.unsplash.com/photo-1631390090687-5a9c3b88ec5e?w=500&q=85",
    "exfoliant":      "https://images.unsplash.com/photo-1556228841-a3c527ebefe5?w=500&q=85",
    "retinoid":       "https://images.unsplash.com/photo-1596755389378-c31d21fd1273?w=500&q=85",
    "eye_treatment":  "https://images.unsplash.com/photo-1512290923902-8a9f81dc236c?w=500&q=85",
    "mask":           "https://images.unsplash.com/photo-1596462502278-27bfdc403348?w=500&q=85",
    "face_oil":       "https://images.unsplash.com/photo-1608248543803-ba4f8c70ae0b?w=500&q=85",
    "led_device":     "https://images.unsplash.com/photo-1598440947619-2c35fc9aa908?w=500&q=85",
    "lip_care":       "https://images.unsplash.com/photo-1599305445671-ac291c95aaa9?w=500&q=85",
    "body_care":      "https://images.unsplash.com/photo-1608248543803-ba4f8c70ae0b?w=500&q=85",
    "microcurrent":   "https://images.unsplash.com/photo-1612817288484-6f916006741a?w=500&q=85",
    "foundation":     "https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?w=500&q=85",
    "spf":            "https://images.unsplash.com/photo-1556228852-80b6e5eeff06?w=500&q=85",
    "essence":        "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=500&q=85",
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


# ── GOOGLE CSE — product image search ────────────────────────────────────────

def _google_image_search(query: str, fallback_query: str = "") -> str:
    """
    Calls Google Custom Search API (image mode) for a single result.
    The CSE is configured to search retailer sites (Amazon, Sephora, etc.)
    so results are always clean product shots.
    Returns a wsrv.nl-proxied URL, or "" on failure.
    """
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        logger.debug("Google CSE not configured — skipping product image fetch")
        return ""

    for attempt, q in enumerate([query, fallback_query]):
        if not q:
            continue
        try:
            params = urllib.parse.urlencode({
                "key":        GOOGLE_CSE_API_KEY,
                "cx":         GOOGLE_CSE_CX,
                "q":          q,
                "searchType": "image",
                "num":        5,            # fetch top 5, pick best
                "imgType":    "photo",
                "safe":       "active",
                "imgSize":    "medium",
            })
            url = f"https://www.googleapis.com/customsearch/v1?{params}"

            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            items = data.get("items", [])
            if items:
                # Prefer HTTPS; proxy through wsrv.nl to eliminate CORS issues
                for item in items:
                    link = item.get("link", "")
                    if link.startswith("https://"):
                        encoded = urllib.parse.quote(link.replace("https://", ""), safe="")
                        return f"https://wsrv.nl/?url={encoded}&w=300&h=300&fit=cover&output=webp"
                # fallback: take first result even if HTTP
                link = items[0].get("link", "")
                if link:
                    encoded = urllib.parse.quote(link.replace("https://", "").replace("http://", ""), safe="")
                    return f"https://wsrv.nl/?url={encoded}&w=300&h=300&fit=cover&output=webp"

        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.warning("Google CSE rate limit — sleeping 30s")
                time.sleep(30)
            else:
                logger.warning(f"Google CSE HTTP {e.code} for: {q}")
        except Exception as e:
            logger.warning(f"Google CSE error for '{q}': {e}")

        if attempt == 0:
            time.sleep(1)   # brief pause before fallback query

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
    LIVE_MODE: queries Google CSE (retailer sites) for the exact product shot.

    Args:
        brand:              e.g. "CeraVe"
        product_name:       e.g. "Moisturizing Cream"
        product_type_label: e.g. "Moisturizer" (used in fallback query)
    """
    full_name = f"{brand} {product_name}".strip()

    # ── TEST MODE ─────────────────────────────────────────────────────────────
    if is_test_mode():
        key = full_name.lower()
        url = TEST_PRODUCT_IMAGES.get(key, "")
        if url:
            logger.debug(f"  [test] product image: {key}")
        return url

    # ── LIVE MODE — Google CSE ────────────────────────────────────────────────
    # Primary: exact brand + product name (finds the product listing on Amazon/Sephora)
    # Fallback: broader query using product type
    primary  = f"{full_name} product"
    fallback = f"{brand} {product_type_label} skincare" if product_type_label else f"{full_name} skincare"

    logger.info(f"  Fetching product image: {full_name}")
    url = _google_image_search(primary, fallback)
    time.sleep(0.5)     # stay well within free-tier rate limits
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
