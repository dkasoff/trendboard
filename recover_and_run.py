"""
trendboard.fyi — Recovery Runner
=================================
Runs steps 2-7 of the skincare pipeline using already-scraped Apify data.
Bypasses step 1 (discovery) entirely — no new API calls, no new spend.

Data sources:
  TikTok:    tiktok_recovered.json   (10,471 items fetched from 71 Apify datasets)
  Instagram: Apify dataset dmtLJPA7BN3nhPq8d  (1,474 posts from manual run)

Usage:
    python3 recover_and_run.py
"""

import os
import json
import time
import logging
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

from apify_client   import ApifyClient
from discovery      import parse_tiktok_video, parse_instagram_post
from skincare_pipeline import (
    fetch_google_signal,
    build_product_signals,
    generate_why_trending,
    _build_billboard_json,
    write_billboard,
    CONFIG,
    MIN_CREATORS,
    MAX_PRODUCTS,
    GT_SLEEP,
)
from extractor      import ProductExtractor
from image_fetcher  import enrich_products_with_images, enrich_categories_with_images
from buy_links      import enrich_products_with_buy_links

TIKTOK_JSON        = "tiktok_recovered.json"
INSTAGRAM_DATASET  = os.getenv("INSTAGRAM_DATASET_ID", "dmtLJPA7BN3nhPq8d")
SEVEN_DAYS_AGO     = (datetime.utcnow().replace(hour=0,minute=0,second=0,microsecond=0)
                      - __import__('datetime').timedelta(days=7)).strftime("%Y-%m-%d")


def load_tiktok_videos():
    logger.info(f"  Loading TikTok data from {TIKTOK_JSON}...")
    with open(TIKTOK_JSON) as f:
        raw_items = json.load(f)
    logger.info(f"  Raw TikTok items: {len(raw_items)}")

    videos = []
    for item in raw_items:
        v = parse_tiktok_video(item)
        if v and (not v.posted_date or v.posted_date >= SEVEN_DAYS_AGO):
            videos.append(v)

    logger.info(f"  TikTok VideoSignals (within 7 days): {len(videos)}")
    return videos


def load_instagram_posts():
    logger.info(f"  Fetching Instagram dataset {INSTAGRAM_DATASET} (no charge)...")
    import asyncio
    from apify_client import ApifyClientAsync

    async def _fetch():
        client = ApifyClientAsync(os.getenv("APIFY_TOKEN"))
        result = await client.dataset(INSTAGRAM_DATASET).list_items()
        return result.items

    try:
        raw_items = asyncio.run(_fetch())
    except Exception as e:
        logger.warning(f"  Instagram dataset unavailable ({e}) — skipping, TikTok only.")
        return []
    logger.info(f"  Raw Instagram items: {len(raw_items)}")

    posts = []
    for item in raw_items:
        v = parse_instagram_post(item)
        if v and (not v.posted_date or v.posted_date >= SEVEN_DAYS_AGO):
            posts.append(v)

    logger.info(f"  Instagram VideoSignals (within 7 days): {len(posts)}")
    return posts


def run():
    run_date = date.today()
    logger.info("\n" + "="*65)
    logger.info("  TRENDBOARD.FYI — Recovery Runner")
    logger.info(f"  Run date: {run_date}")
    logger.info(f"  Using pre-scraped Apify data — no new spend")
    logger.info("="*65)

    # ── Load recovered data ────────────────────────────────────────────────────
    logger.info("\n[1/7] Loading recovered Apify data...")
    tiktok_videos    = load_tiktok_videos()
    instagram_posts  = load_instagram_posts()
    videos           = tiktok_videos + instagram_posts

    # Deduplicate by video_id
    seen, unique = set(), []
    for v in videos:
        if v.video_id not in seen:
            seen.add(v.video_id)
            unique.append(v)

    tiktok_count = sum(1 for v in unique if v.platform == "tiktok")
    ig_count     = sum(1 for v in unique if v.platform == "instagram")
    logger.info(f"  Total unique signals: {len(unique)} "
                f"(TikTok: {tiktok_count}, Instagram: {ig_count})")

    # ── STEP 2: Extraction ────────────────────────────────────────────────────
    logger.info("\n[2/7] Extracting product candidates...")
    extractor  = ProductExtractor()
    candidates = extractor.process_videos(unique, min_creators=MIN_CREATORS)
    logger.info(f"  Candidates passing velocity filter: {len(candidates)}")

    if not candidates:
        logger.error("  No candidates found. Check extractor keyword list.")
        return

    logger.info("\n  Top 20 candidates by creator count:")
    for c in candidates[:20]:
        logger.info(
            f"    {c.display_name:<35} "
            f"creators:{c.unique_creator_count:>4}  "
            f"organic:{c.organic_count:>4}  "
            f"sponsored:{c.sponsored_count:>3}  "
            f"confidence:{c.confidence:.2f}"
        )

    # ── STEP 3: Google Trends confirmation ────────────────────────────────────
    top_candidates = candidates[:MAX_PRODUCTS * 2]
    logger.info(f"\n[3/7] Confirming with Google Trends ({len(top_candidates)} products)...")
    candidate_dict = {}
    all_signals    = []

    for c in top_candidates:
        google = fetch_google_signal(c.google_keyword)
        time.sleep(GT_SLEEP)

        if google.current_volume == 0 and google.prior_volume == 0:
            logger.info(f"    Skipping {c.display_name} — no Google signal")
            continue

        signals = build_product_signals(c, google)
        all_signals.append(signals)
        candidate_dict[c.product_key] = c

    logger.info(f"  Products with Google confirmation: {len(all_signals)}")

    if not all_signals:
        logger.error("  No products survived Google confirmation. Exiting.")
        return

    # ── STEP 4: Scoring ───────────────────────────────────────────────────────
    from scorer import run_weekly_scoring
    logger.info("\n[4/7] Scoring...")
    result = run_weekly_scoring(all_signals)
    ranked = result["ranked_scores"][:MAX_PRODUCTS]

    # ── STEP 5: Descriptions ──────────────────────────────────────────────────
    logger.info("\n[5/7] Generating editorial descriptions...")
    descriptions = {}
    for score in ranked:
        c    = candidate_dict.get(score.product_id)
        desc = generate_why_trending(score.product_name, score, c) if c else ""
        descriptions[score.product_id] = desc
        logger.info(f"  {score.product_name}: \"{desc}\"")

    # ── STEP 5b: Product images ───────────────────────────────────────────────
    logger.info("\n[5b/7] Fetching product images...")
    _image_map = {}
    for score in ranked:
        c = candidate_dict.get(score.product_id)
        _image_map[score.product_id] = {
            "brand":              c.brand if c else "",
            "product_name":       score.product_name,
            "product_type_label": c.product_type_label if c else "",
            "image_url":          "",
        }
    enrich_products_with_images(list(_image_map.values()))

    # ── STEP 5c: Buy links ────────────────────────────────────────────────────
    logger.info("\n[5c/7] Resolving buy links...")
    enrich_products_with_buy_links(list(_image_map.values()))

    # ── STEP 6: Billboard JSON ────────────────────────────────────────────────
    logger.info("\n[6/7] Building category billboard...")
    billboard_data = _build_billboard_json(ranked, descriptions, candidate_dict,
                                           run_date, _image_map)
    enrich_categories_with_images(billboard_data["ranked_categories"])

    # ── STEP 7: Write ─────────────────────────────────────────────────────────
    logger.info("\n[7/7] Writing output...")
    write_billboard(billboard_data, run_date)

    # ── Summary ───────────────────────────────────────────────────────────────
    icons = {
        "NEW_ENTRY": "🆕", "HIGH_FLYER": "🚀", "FALLING_STAR": "⚠️",
        "COOLING": "🌡️", "STAPLE": "📊", "TRENDING": "📈", "BELOW_THRESHOLD": "·"
    }
    logger.info(f"\n{'='*65}")
    logger.info(f"  SKINCARE BILLBOARD — {run_date}")
    logger.info(f"{'='*65}")
    logger.info(f"  {'#':>2}  {'Category':<22}  {'CatTS':>6}  {'Products':>8}  State")
    logger.info(f"  {'─'*2}  {'─'*22}  {'─'*6}  {'─'*8}  {'─'*15}")
    for cat in billboard_data["ranked_categories"]:
        icon = icons.get(cat["state"], "·")
        logger.info(
            f"  {icon}#{cat['rank']:<2}  {cat['type_label']:<22}  "
            f"{cat['category_ts']:>6.1f}  {cat['product_count']:>8}  {cat['state']}"
        )
    logger.info(f"\n  TikTok:    {tiktok_count} signals (recovered from 71 Apify datasets)")
    logger.info(f"  Instagram: {ig_count} signals (dataset {INSTAGRAM_DATASET})")
    logger.info(f"  New Apify spend: $0.00")
    logger.info(f"\n{'='*65}\n")


if __name__ == "__main__":
    run()
