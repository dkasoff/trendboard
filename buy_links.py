"""
trendboard.fyi — Buy Link Resolver
====================================
Determines the best purchase URL for each top-25 product.

Priority order per product:
  1. Brand registry — known DTC brands get their direct site
  2. Amazon PA API  — returns exact ASIN + affiliate link (when configured)
  3. Amazon search  — fallback: search URL with affiliate tag (always works)
  4. Sephora search — for brands that don't sell direct and aren't on Amazon

Stores in JSON per product:
  buy_url     — the final href
  buy_source  — "brand" | "amazon" | "sephora" | "ulta"
  buy_label   — display string: "Shop on Sephora", "Shop on paulaschoice.com", etc.

Affiliate programs:
  - Amazon:        trendboard05-20 (tag already in .env)
  - DTC brands:    most run programs via ShareASale / Impact — add tracking
                   params to buy_url when affiliate_tag is set in registry
"""

import os
import json
import time
import logging
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)

AMAZON_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "trendboard05-20")


# ── BRAND REGISTRY ────────────────────────────────────────────────────────────
# Key   = brand name, lowercase, stripped.
# Keys should match what the extractor produces (brand field in ProductCandidate).
#
# buy_type options:
#   "brand"   → link to brand's own website (DTC)
#   "amazon"  → resolve via Amazon PA API or search URL
#   "sephora" → link to Sephora product search
#   "ulta"    → link to Ulta product search
#
# affiliate_param: appended to buy_url if set (e.g. ShareASale / Impact ref tag)

BRAND_REGISTRY = {

    # ── DTC SKINCARE ──────────────────────────────────────────────────────────
    "paula's choice": {
        "buy_type":  "brand",
        "buy_url":   "https://www.paulaschoice.com",
        "buy_label": "Shop on paulaschoice.com",
        "affiliate_param": "",          # add ShareASale param when enrolled
    },
    "the ordinary": {
        "buy_type":  "brand",
        "buy_url":   "https://theordinary.com",
        "buy_label": "Shop on theordinary.com",
        "affiliate_param": "",
    },
    "deciem": {
        "buy_type":  "brand",
        "buy_url":   "https://deciem.com",
        "buy_label": "Shop on deciem.com",
        "affiliate_param": "",
    },
    "drunk elephant": {
        "buy_type":  "sephora",         # sold primarily through Sephora in US
        "buy_url":   "",
        "buy_label": "Shop on Sephora",
        "affiliate_param": "",
    },
    "tatcha": {
        "buy_type":  "brand",
        "buy_url":   "https://www.tatcha.com",
        "buy_label": "Shop on tatcha.com",
        "affiliate_param": "",
    },
    "sunday riley": {
        "buy_type":  "sephora",
        "buy_url":   "",
        "buy_label": "Shop on Sephora",
        "affiliate_param": "",
    },
    "glossier": {
        "buy_type":  "brand",
        "buy_url":   "https://www.glossier.com",
        "buy_label": "Shop on glossier.com",
        "affiliate_param": "",
    },
    "summer fridays": {
        "buy_type":  "sephora",
        "buy_url":   "",
        "buy_label": "Shop on Sephora",
        "affiliate_param": "",
    },
    "peter thomas roth": {
        "buy_type":  "brand",
        "buy_url":   "https://www.peterthomasroth.com",
        "buy_label": "Shop on peterthomasroth.com",
        "affiliate_param": "",
    },
    "olehenriksen": {
        "buy_type":  "sephora",
        "buy_url":   "",
        "buy_label": "Shop on Sephora",
        "affiliate_param": "",
    },
    "innisfree": {
        "buy_type":  "brand",
        "buy_url":   "https://www.innisfreeworld.com",
        "buy_label": "Shop on innisfreeworld.com",
        "affiliate_param": "",
    },
    "missha": {
        "buy_type":  "brand",
        "buy_url":   "https://us.missha.com",
        "buy_label": "Shop on missha.com",
        "affiliate_param": "",
    },

    # ── K-BEAUTY ──────────────────────────────────────────────────────────────
    "anua": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "cosrx": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "beauty of joseon": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "laneige": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "some by mi": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "isntree": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "tirtir": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "skin1004": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "medicube": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },

    # ── MASS MARKET (drugstore / pharmacy) ───────────────────────────────────
    "cerave": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "neutrogena": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "la roche-posay": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "vanicream": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "aveeno": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "olay": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "hero cosmetics": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "differin": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },
    "stridex": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },

    # ── DEVICES ───────────────────────────────────────────────────────────────
    "nuface": {
        "buy_type":  "brand",
        "buy_url":   "https://www.mynuface.com",
        "buy_label": "Shop on mynuface.com",
        "affiliate_param": "",
    },
    "solawave": {
        "buy_type":  "brand",
        "buy_url":   "https://solawave.co",
        "buy_label": "Shop on solawave.co",
        "affiliate_param": "",
    },
    "currentbody": {
        "buy_type":  "brand",
        "buy_url":   "https://www.currentbody.com",
        "buy_label": "Shop on currentbody.com",
        "affiliate_param": "",
    },
    "foreo": {
        "buy_type":  "brand",
        "buy_url":   "https://www.foreo.com",
        "buy_label": "Shop on foreo.com",
        "affiliate_param": "",
    },
    "theraface": {
        "buy_type":  "brand",
        "buy_url":   "https://www.therabody.com",
        "buy_label": "Shop on therabody.com",
        "affiliate_param": "",
    },
    "drx spectra": {
        "buy_type":  "amazon",
        "buy_url":   "",
        "buy_label": "Shop on Amazon",
        "affiliate_param": "",
    },

    # ── LUXURY / PRESTIGE ─────────────────────────────────────────────────────
    "sk-ii": {
        "buy_type":  "sephora",
        "buy_url":   "",
        "buy_label": "Shop on Sephora",
        "affiliate_param": "",
    },
    "la mer": {
        "buy_type":  "brand",
        "buy_url":   "https://www.cremedelamer.com",
        "buy_label": "Shop on cremedelamer.com",
        "affiliate_param": "",
    },
    "augustinus bader": {
        "buy_type":  "brand",
        "buy_url":   "https://augustinusbader.com",
        "buy_label": "Shop on augustinusbader.com",
        "affiliate_param": "",
    },
    "sisley": {
        "buy_type":  "brand",
        "buy_url":   "https://www.sisley-paris.com",
        "buy_label": "Shop on sisley-paris.com",
        "affiliate_param": "",
    },
}


# ── AMAZON URL BUILDERS ───────────────────────────────────────────────────────

def amazon_search_url(brand: str, product_name: str) -> str:
    """
    Builds an Amazon search URL with the affiliate tag.
    Works immediately with no API needed.
    Returns something like:
      https://www.amazon.com/s?k=CeraVe+Moisturizing+Cream&tag=trendboard05-20
    """
    query = urllib.parse.quote_plus(f"{brand} {product_name}".strip())
    return f"https://www.amazon.com/s?k={query}&tag={AMAZON_TAG}"


def amazon_product_url(asin: str) -> str:
    """Builds a direct Amazon product URL from ASIN."""
    return f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"


def amazon_pa_lookup(brand: str, product_name: str) -> str:
    """
    Looks up the exact ASIN via Amazon Product Advertising API.
    Returns direct product URL, or falls back to search URL.

    Requires:
      AMAZON_PA_ACCESS_KEY  (different from affiliate tag)
      AMAZON_PA_SECRET_KEY
      AMAZON_PA_PARTNER_TAG (same as affiliate tag)

    These are separate from the affiliate tag — requires PA API approval.
    For now this falls through to search URL until PA API is configured.
    """
    access_key = os.getenv("AMAZON_PA_ACCESS_KEY", "")
    secret_key = os.getenv("AMAZON_PA_SECRET_KEY", "")

    if not access_key or not secret_key:
        logger.debug("Amazon PA API not configured — using search URL")
        return amazon_search_url(brand, product_name)

    # TODO: implement AWIS v5 signed request when PA API keys are available
    # For now fall through
    return amazon_search_url(brand, product_name)


# ── SEPHORA / ULTA BUILDERS ───────────────────────────────────────────────────

def sephora_search_url(brand: str, product_name: str) -> str:
    query = urllib.parse.quote_plus(f"{brand} {product_name}".strip())
    return f"https://www.sephora.com/search?keyword={query}"


def ulta_search_url(brand: str, product_name: str) -> str:
    query = urllib.parse.quote_plus(f"{brand} {product_name}".strip())
    return f"https://www.ulta.com/search?search={query}"


# ── RESOLVER ──────────────────────────────────────────────────────────────────

def resolve_buy_link(brand: str, product_name: str) -> dict:
    """
    Returns the best buy link for a product.

    Returns:
        {
            "buy_url":    "https://...",
            "buy_source": "brand" | "amazon" | "sephora" | "ulta",
            "buy_label":  "Shop on paulaschoice.com" | "Shop on Amazon" | ...
        }
    """
    brand_key = brand.lower().strip()
    entry     = BRAND_REGISTRY.get(brand_key)

    # ── 1. Registry match ─────────────────────────────────────────────────────
    if entry:
        buy_type = entry["buy_type"]
        label    = entry["buy_label"]

        if buy_type == "brand":
            base = entry["buy_url"]
            # Append product-level search path if we don't have an exact URL
            # For now link to homepage; PA API / brand search adds exact URL later
            url = base
            return {"buy_url": url, "buy_source": "brand", "buy_label": label}

        elif buy_type == "amazon":
            url = amazon_pa_lookup(brand, product_name)
            return {"buy_url": url, "buy_source": "amazon", "buy_label": label}

        elif buy_type == "sephora":
            url = sephora_search_url(brand, product_name)
            return {"buy_url": url, "buy_source": "sephora", "buy_label": label}

        elif buy_type == "ulta":
            url = ulta_search_url(brand, product_name)
            return {"buy_url": url, "buy_source": "ulta", "buy_label": label}

    # ── 2. No registry match — fall back to Amazon search ────────────────────
    logger.debug(f"No registry entry for '{brand}' — defaulting to Amazon search")
    url = amazon_search_url(brand, product_name)
    return {
        "buy_url":    url,
        "buy_source": "amazon",
        "buy_label":  "Shop on Amazon",
    }


def enrich_products_with_buy_links(products: list[dict]) -> list[dict]:
    """
    Adds buy_url, buy_source, buy_label to each product dict.
    Called during pipeline run; results stored in skincare_billboard.json.
    """
    logger.info(f"\n  Resolving buy links ({len(products)} products)…")
    for p in products:
        brand = p.get("brand", "")
        name  = p.get("product_name", "")
        result = resolve_buy_link(brand, name)
        p.update(result)
        logger.info(f"  {brand} {name} → {result['buy_label']}")
    return products
