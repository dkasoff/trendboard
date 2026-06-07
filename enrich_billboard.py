"""
trendboard.fyi — Billboard Enricher
=====================================
Patches an existing skincare_billboard.json with:
  1. Real product images via DuckDuckGo (no API key needed)
  2. Claude-generated "why trending" stories

Does NOT re-run discovery, Google Trends, or scoring.
Safe to run repeatedly — skips products that already have an image.

Usage:
    python3 enrich_billboard.py
"""

import os
import json
import time
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BILLBOARD_PATH = "skincare_billboard.json"


# ── Claude story generator ────────────────────────────────────────────────────

def generate_story(product_name: str, category: str, creators: int,
                   sponsored: int, organic: int) -> str:
    """Calls Claude to write a one-sentence 'why it's trending' story."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        prompt = f"""You write one-sentence trend summaries for a skincare trend tracker called Trendboard.fyi.

Product: {product_name}
Category: {category}
Unique creators posting this week: {creators}
Organic posts: {organic}  |  Sponsored posts: {sponsored}

Write ONE punchy sentence (max 15 words) explaining why this product is trending right now.
Focus on the organic creator signal. Be specific and exciting, not generic.
Do not use quotes. Do not start with "This". Do not mention the number of creators literally.
Examples of good style:
- "Dermatologists and micro-creators are calling it the best barrier repair of the year"
- "K-beauty loyalists can't stop posting their glass-skin results"
- "A wave of before-and-afters is turning skeptics into believers"
"""
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}]
        )
        story = msg.content[0].text.strip().strip('"')
        logger.info(f"  ✓ Story: {story}")
        return story
    except Exception as e:
        logger.warning(f"  Claude story failed ({e}) — using fallback")
        return f"{creators} creators are posting organic reviews this week"


# ── DDG image fetcher ─────────────────────────────────────────────────────────

_BLOCKED_CDNS = (
    "m.media-amazon.com", "sephora.com/productimages",
    "pinimg.com", "fbcdn.net", "cdninstagram.com", "lookaside.fbsbx.com",
)

def fetch_image(brand: str, product_name: str, category: str) -> str:
    """Searches DuckDuckGo for a product image, skips blocked CDNs."""
    import urllib.parse
    try:
        from ddgs import DDGS
    except ImportError:
        logger.warning("ddgs not installed — run: pip3 install ddgs")
        return ""

    queries = [
        f"{brand} {product_name} product",
        f"{brand} {category} skincare",
        f"{product_name} skincare product",
    ]

    for q in queries:
        try:
            results = list(DDGS().images(q, max_results=8))
            time.sleep(1.0)
            for r in results:
                link = r.get("image", "")
                if not link:
                    continue
                if any(cdn in link for cdn in _BLOCKED_CDNS):
                    continue
                # must be https
                if not link.startswith("https://"):
                    continue
                stripped = link.replace("https://", "")
                encoded  = urllib.parse.quote(stripped, safe="/:@!$&'()*+,;=?#[]")
                url = f"https://wsrv.nl/?url={encoded}&w=300&h=300&fit=cover&output=webp"
                logger.info(f"  ✓ {brand} {product_name} → {link[:70]}")
                return url
        except Exception as e:
            logger.debug(f"  DDG error for '{q}': {e}")
            time.sleep(2)

    logger.warning(f"  ✗ No image found for {brand} {product_name}")
    return ""


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    logger.info("\n" + "="*60)
    logger.info("  Billboard Enricher — images + stories")
    logger.info("="*60)

    with open(BILLBOARD_PATH) as f:
        billboard = json.load(f)

    categories = billboard.get("ranked_categories", [])
    total_products = sum(len(c["products"]) for c in categories)
    logger.info(f"  {len(categories)} categories, {total_products} products\n")

    for cat in categories:
        cat_label = cat["type_label"]
        logger.info(f"\n── {cat_label} ──")

        for p in cat["products"]:
            name      = p.get("product_name", "")
            brand     = p.get("brand", "")
            creators  = p.get("unique_creators", 0)
            sponsored = p.get("sponsored_count", 0)
            organic   = p.get("organic_count", 0)

            # ── Story ────────────────────────────────────────────────────────
            existing_story = cat.get("why_trending", "")
            if (not existing_story or "unique creators posted" in existing_story
                    or "micro-creators posted" in existing_story):
                logger.info(f"  Generating story for {name}...")
                story = generate_story(name, cat_label, creators, sponsored, organic)
                # Apply to the category (top product drives the category story)
                if p == cat["products"][0]:
                    cat["why_trending"] = story

            # ── Image ────────────────────────────────────────────────────────
            if p.get("image_url"):
                logger.info(f"  {name} — image already set, skipping")
                continue

            logger.info(f"  Fetching image for {name}...")
            url = fetch_image(brand, name, cat_label)
            p["image_url"] = url

    # Write back
    with open(BILLBOARD_PATH, "w") as f:
        json.dump(billboard, f, indent=2)

    logger.info("\n" + "="*60)
    logger.info("  Done — skincare_billboard.json updated")
    logger.info("="*60)

    # Summary
    for cat in categories:
        products_with_images = sum(1 for p in cat["products"] if p.get("image_url"))
        logger.info(
            f"  {cat['type_label']:<22} "
            f"story: {'✓' if cat.get('why_trending') else '✗'}  "
            f"images: {products_with_images}/{len(cat['products'])}"
        )


if __name__ == "__main__":
    run()
