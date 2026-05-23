"""
trendboard.fyi — Product Image Fetcher
=======================================
Fetches the best product image for each top-25 item using
Google Custom Search API (image mode).

Called once per pipeline run (weekly). Results are embedded
directly into skincare_billboard.json — no live API calls
at page load time.

Cost: ~$0 for 25 products/week (free tier = 100 queries/day)

Setup (one-time):
  1. https://programmablesearchengine.google.com
     → New Search Engine → Search entire web → Enable Image Search
     → Copy the Search Engine ID into .env as GOOGLE_CSE_CX
  2. https://console.cloud.google.com
     → APIs & Services → Custom Search API → Enable
     → Credentials → Create API Key
     → Copy into .env as GOOGLE_CSE_API_KEY

Usage:
    from image_fetcher import fetch_product_image, fetch_category_image

    url = fetch_product_image("CeraVe", "Moisturizing Cream")
    # → "https://..."
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

# ── FALLBACK PLACEHOLDER IMAGES (used in TEST_MODE) ──────────────────────────
# Real product images embedded for the mock billboard so the UI looks great.
# Keys are lowercase "{brand} {product_name}".
TEST_IMAGE_FALLBACKS = {
    "anua heartleaf 77% soothing toner":          "https://images.sephora.com/is/image/sephora/skn-hero-anua-heartleaf-toner-2024",
    "cerave moisturizing cream":                   "https://m.media-amazon.com/images/I/61S7BrCBj7L._SL1500_.jpg",
    "the ordinary niacinamide 10% + zinc 1%":      "https://m.media-amazon.com/images/I/612wRN1gVsL._SL1500_.jpg",
    "la roche-posay anthelios melt-in sunscreen":  "https://m.media-amazon.com/images/I/71lZoiAoJML._SL1500_.jpg",
    "paula's choice skin perfecting 2% bha":       "https://m.media-amazon.com/images/I/71Z7d4Og5bL._SL1500_.jpg",
    "cosrx advanced snail 96 mucin power essence": "https://m.media-amazon.com/images/I/71yMXTNcGqL._SL1500_.jpg",
    "drunk elephant protini polypeptide cream":    "https://m.media-amazon.com/images/I/61dvSuSsJAL._SL1500_.jpg",
    "laneige lip sleeping mask":                   "https://m.media-amazon.com/images/I/71EHnBNFSLL._SL1500_.jpg",
    "tatcha the water cream":                      "https://m.media-amazon.com/images/I/71k+h3FujZL._SL1500_.jpg",
    "neutrogena hydro boost water gel":            "https://m.media-amazon.com/images/I/71NjTTk9t0L._SL1500_.jpg",
}

# Category lifestyle images for filter bar / category headers (TEST_MODE fallback)
CATEGORY_IMAGE_FALLBACKS = {
    "moisturizer":    "https://images.unsplash.com/photo-1570194065650-d99fb4b8ccb0?w=400&q=80",
    "serum":          "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=400&q=80",
    "cleanser":       "https://images.unsplash.com/photo-1556228578-8c89e6adf883?w=400&q=80",
    "sunscreen":      "https://images.unsplash.com/photo-1556228852-80b6e5eeff06?w=400&q=80",
    "toner":          "https://images.unsplash.com/photo-1631390090687-5a9c3b88ec5e?w=400&q=80",
    "exfoliant":      "https://images.unsplash.com/photo-1556228841-a3c527ebefe5?w=400&q=80",
    "retinoid":       "https://images.unsplash.com/photo-1596755389378-c31d21fd1273?w=400&q=80",
    "eye_treatment":  "https://images.unsplash.com/photo-1512290923902-8a9f81dc236c?w=400&q=80",
    "mask":           "https://images.unsplash.com/photo-1596462502278-27bfdc403348?w=400&q=80",
    "face_oil":       "https://images.unsplash.com/photo-1608248543803-ba4f8c70ae0b?w=400&q=80",
    "led_device":     "https://images.unsplash.com/photo-1598440947619-2c35fc9aa908?w=400&q=80",
    "lip_care":       "https://images.unsplash.com/photo-1599305445671-ac291c95aaa9?w=400&q=80",
    "body_care":      "https://images.unsplash.com/photo-1608248543803-ba4f8c70ae0b?w=400&q=80",
}


# ── GOOGLE CSE IMAGE SEARCH ───────────────────────────────────────────────────

def _google_image_search(query: str, fallback_query: str = "") -> str:
    """
    Calls Google Custom Search API for a single image result.
    Returns image URL string, or "" on failure.
    """
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        logger.debug("Google CSE not configured — skipping image fetch")
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
                "num":        3,           # fetch top 3, pick best
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
                # Prefer HTTPS, prefer known reliable domains
                for item in items:
                    link = item.get("link", "")
                    if link.startswith("https://"):
                        return link
                return items[0].get("link", "")

        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.warning("Google CSE rate limit hit — sleeping 30s")
                time.sleep(30)
            else:
                logger.warning(f"Google CSE HTTP {e.code} for query: {q}")
        except Exception as e:
            logger.warning(f"Google CSE error for '{q}': {e}")

        if attempt == 0:
            time.sleep(1)   # brief pause before fallback query

    return ""


def fetch_product_image(brand: str, product_name: str,
                        product_type_label: str = "") -> str:
    """
    Returns the best image URL for a specific product.

    In TEST_MODE: returns a hardcoded fallback URL (or "") — no API calls.
    In LIVE_MODE: queries Google Custom Search API.

    Args:
        brand:              e.g. "CeraVe"
        product_name:       e.g. "Moisturizing Cream"
        product_type_label: e.g. "Moisturizer"  (used in fallback query)

    Returns:
        str: https:// image URL, or "" if unavailable
    """
    full_name = f"{brand} {product_name}".strip()

    # ── TEST MODE: use hardcoded fallbacks ────────────────────────────────────
    if is_test_mode():
        key = full_name.lower()
        url = TEST_IMAGE_FALLBACKS.get(key, "")
        if url:
            logger.debug(f"  [test] image fallback: {key}")
        return url

    # ── LIVE MODE: call Google CSE ────────────────────────────────────────────
    primary_query  = f"{full_name} skincare product"
    fallback_query = f"{product_type_label} {brand} product" if product_type_label else ""

    logger.info(f"  Fetching image: {full_name}")
    url = _google_image_search(primary_query, fallback_query)
    time.sleep(0.5)     # stay well within free-tier rate limits
    return url


def fetch_category_image(type_id: str, type_label: str) -> str:
    """
    Returns a lifestyle image URL for a product category.

    In TEST_MODE: returns a curated Unsplash URL or "".
    In LIVE_MODE: queries Google CSE for a generic category shot.

    Args:
        type_id:    e.g. "moisturizer"
        type_label: e.g. "Moisturizer"

    Returns:
        str: https:// image URL, or ""
    """
    if is_test_mode():
        return CATEGORY_IMAGE_FALLBACKS.get(type_id, "")

    query          = f"{type_label} skincare product flatlay"
    fallback_query = f"best {type_label} beauty product"

    logger.info(f"  Fetching category image: {type_label}")
    url = _google_image_search(query, fallback_query)
    time.sleep(0.5)
    return url


def enrich_products_with_images(products: list[dict]) -> list[dict]:
    """
    Takes the ranked top-25 product list and adds image_url to each.
    Called once per pipeline run.

    Modifies products in-place and also returns the list.
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
