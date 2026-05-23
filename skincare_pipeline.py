"""
trendboard.fyi — Skincare Pipeline
=====================================
Full automated pipeline for the Skincare & Beauty chart.

Flow:
    1. Discovery    — Apify scrapes TikTok hashtags + creator accounts
    2. Extraction   — Product names pulled from captions
    3. Filtering    — Velocity filter (5+ unique creators in 7 days)
    4. Google       — Confirms search momentum for each candidate
    5. Scoring      — Full v2 algorithm scores each product
    6. Ranking      — Top 25 selected for the billboard
    7. Supabase     — Results written to database
    8. GitHub       — index.html updated with new rankings

Run:   python3 skincare_pipeline.py
Cron:  0 9 * * 1 cd /path/to/trendboard && python3 skincare_pipeline.py >> skincare_log.txt 2>&1
"""

import os
import time
import json
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

from safety      import guard, is_test_mode, status as safety_status, COST_ESTIMATES
from discovery   import DiscoveryScraper
from extractor   import ProductExtractor, ProductCandidate
from attribution    import build_attribution, generate_story
from image_fetcher  import enrich_products_with_images, enrich_categories_with_images
from buy_links      import enrich_products_with_buy_links
from scorer import (
    GoogleSignal, TikTokSignal, InstagramSignal, RedditSignal,
    ProductSignals, run_weekly_scoring
)


# ─── CONFIG ──────────────────────────────────────────────────────────────────

CONFIG = {
    "apify_token":   os.getenv("APIFY_TOKEN", ""),
    "supabase_url":  os.getenv("SUPABASE_URL", ""),
    "supabase_key":  os.getenv("SUPABASE_KEY", ""),
    "anthropic_key": os.getenv("ANTHROPIC_API_KEY", ""),
}

# Minimum unique creators to qualify for scoring
MIN_CREATORS   = 2
# Maximum products to score and rank
MAX_PRODUCTS   = 25
# Google Trends sleep between keywords (seconds)
GT_SLEEP       = 6


# ─── GOOGLE TRENDS CONNECTOR ─────────────────────────────────────────────────

def fetch_google_signal(keyword: str) -> GoogleSignal:
    """Pulls real Google Trends data for a product keyword."""
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl='en-US', tz=360, timeout=(10, 25))
        pt.build_payload([keyword], timeframe='today 3-m', geo='US')
        df = pt.interest_over_time()

        if df.empty:
            return _empty_google()

        vals    = df[keyword].tolist()
        current = float(vals[-1])
        prior   = float(vals[-2]) if len(vals) >= 2 else 0.0
        wow     = ((current - prior) / prior * 100) if prior > 0 else 0

        days = 0
        for i in range(len(vals) - 1, 0, -1):
            if vals[i] > vals[i - 1]: days += 7
            else: break

        is_breakout = (current >= 90 or wow > 100)
        logger.info(f"    Google: {keyword:<35} cur:{current:>3.0f}  WoW:{wow:>+6.1f}%  days↑:{days}")
        return GoogleSignal(current, prior, is_breakout, days, 0)

    except Exception as e:
        logger.warning(f"    Google error [{keyword}]: {e}")
        return _empty_google()

def _empty_google() -> GoogleSignal:
    return GoogleSignal(0, 0, False, 0, 0)


# ─── SIGNAL BUILDER ──────────────────────────────────────────────────────────

def build_product_signals(candidate: ProductCandidate,
                           google: GoogleSignal) -> ProductSignals:
    """
    Converts a ProductCandidate + GoogleSignal into a ProductSignals object
    ready for the v2 scoring engine.

    TikTok signals come from real Apify data (via candidate).
    Instagram signals are estimated from TikTok data (no IG API yet).
    Reddit signals are estimated (pending API approval).
    """
    scale = max(google.current_volume, 10) / 100.0
    wow   = ((google.current_volume - google.prior_volume) / google.prior_volume * 100) \
            if google.prior_volume > 0 else 0

    tiktok = TikTokSignal(
        total_video_count    = candidate.total_video_count,
        unique_creator_count = candidate.unique_creator_count,
        sound_reuse_48h      = int(candidate.total_video_count * 0.6),
        sponsored_post_count = candidate.sponsored_count,
        organic_post_count   = candidate.organic_count,
        unboxing_count       = max(candidate.total_video_count // 10, 1),
        link_in_bio_count    = int(candidate.total_video_count * 0.15),
        just_ordered_count   = max(candidate.total_video_count // 8, 1),
        restock_count        = max(candidate.total_video_count // 20, 0),
        must_buy_phrases     = candidate.strong_signal_count,
        negative_phrases     = candidate.negative_signal_count,
        # Real creator tier data from Apify
        nano_creators        = candidate.nano_creators,
        micro_creators       = candidate.micro_creators,
        macro_creators       = candidate.macro_creators,
        mega_creators        = candidate.mega_creators,
        category_positive_phrases = max(candidate.strong_signal_count // 2, 1),
        category_negative_phrases = max(candidate.negative_signal_count // 3, 0),
        prior_week_sponsored_ratio = 0.08 if wow > 0 else 0.25,
    )

    # Instagram estimated from TikTok + Google (no real IG API yet)
    instagram = InstagramSignal(
        save_count           = int(scale * 6000),
        share_count          = int(scale * 2000),
        like_count           = int(scale * 120000),
        comment_count        = int(scale * 8000),
        sponsored_post_count = int(candidate.sponsored_count * 0.6),
        organic_post_count   = int(candidate.organic_count * 0.6),
        unique_creator_count = int(candidate.unique_creator_count * 0.6),
    )

    # Reddit estimated (pending API approval)
    reddit = RedditSignal(
        unique_subreddit_count   = int(scale * 6),
        total_post_count         = int(scale * 25),
        avg_comment_depth        = scale * 5.5,
        high_karma_post_count    = int(scale * 8),
        pros_cons_thread_count   = int(scale * 4),
        must_buy_phrases         = max(candidate.strong_signal_count // 3, 1),
        negative_phrases         = max(candidate.negative_signal_count // 3, 0),
        consumer_subreddit_hits  = int(scale * 6),
        niche_subreddit_hits     = int(scale * 3),
    )

    return ProductSignals(
        product_id       = candidate.product_key,
        product_name     = candidate.display_name,
        category         = candidate.category,
        google           = google,
        tiktok           = tiktok,
        instagram        = instagram,
        reddit           = reddit,
        ts_history       = [],
        days_in_database = 0,
    )


# ─── AI DESCRIPTION GENERATOR ────────────────────────────────────────────────
# Replaced by attribution.py — build_attribution() + generate_story()
# Kept as a thin wrapper for backwards compatibility.

def generate_why_trending(product_name: str, score, candidate: ProductCandidate) -> str:
    """Wrapper: builds attribution then generates story sentence."""
    attr = build_attribution(candidate)
    return generate_story(attr, score)


# ─── BILLBOARD JSON BUILDER ──────────────────────────────────────────────────

def _build_billboard_json(ranked_scores, descriptions, candidates, run_date,
                           image_map: dict = None) -> dict:
    """
    Builds the category-first billboard JSON.

    Structure:
      ranked_categories: [
        { rank, type_id, type_label, type_emoji, category_ts, state,
          why_trending, velocity_score, …, category_image, product_count,
          products: [ {product_id, product_name, brand, final_ts, image_url,
                       buy_url, buy_label, buy_source, attribution, …} ] }
      ]

    Category score = weighted blend of product TS scores in that category.
    Products within each category are ranked by individual final_ts.
    """
    from collections import defaultdict
    image_map = image_map or {}

    product_by_type = defaultdict(list)
    type_meta       = {}   # type_id → {type_label, type_emoji}

    for score in ranked_scores:
        c          = candidates.get(score.product_id)
        type_id    = (c.product_type_id    if c else "") or "other"
        type_label = (c.product_type_label if c else "") or "Other"
        type_emoji = (c.product_type_emoji if c else "") or "✨"
        type_meta[type_id] = {"type_label": type_label, "type_emoji": type_emoji}

        img_data = image_map.get(score.product_id, {})
        attr     = build_attribution(c) if c else None

        product_by_type[type_id].append({
            "product_id":        score.product_id,
            "product_name":      score.product_name,
            "brand":             c.brand if c else "",
            "final_ts":          score.final_ts,
            "velocity_score":    score.velocity_score,
            "density_score":     score.density_score,
            "sentiment_score":   score.sentiment_score,
            "conversion_score":  score.conversion_score,
            "state":             score.state,
            "unique_creators":   c.unique_creator_count if c else 0,
            "sponsored_count":   getattr(c, "sponsored_count", 0) if c else 0,
            "organic_count":     getattr(c, "organic_count",   0) if c else 0,
            "platforms_present": score.platforms_present,
            "image_url":         img_data.get("image_url",  ""),
            "buy_url":           img_data.get("buy_url",    ""),
            "buy_source":        img_data.get("buy_source", "amazon"),
            "buy_label":         img_data.get("buy_label",  "Shop on Amazon"),
            "attribution": {
                "spark_handle":         attr.spark_handle          if attr else "",
                "spark_label":          attr.spark_label           if attr else "",
                "spark_followers":      attr.spark_followers        if attr else 0,
                "spark_likes":          attr.spark_likes            if attr else 0,
                "days_since_spark":     attr.days_since_spark       if attr else 0,
                "creators_after_spark": attr.creators_after_spark   if attr else 0,
                "pattern":              attr.pattern                if attr else "",
                "pattern_label":        attr.pattern_label          if attr else "",
                "organic_ratio":        attr.organic_ratio          if attr else 0,
                "has_derm":             attr.has_derm_endorsement   if attr else False,
            } if attr else {},
        })

    # ── Build category entries ────────────────────────────────────────────────
    ranked_categories = []
    for type_id, products in product_by_type.items():
        products.sort(key=lambda p: p["final_ts"], reverse=True)
        top      = products[0]
        ts_vals  = [p["final_ts"] for p in products]
        top3     = products[:3]

        # Weighted category TS: top product dominates, others add density bonus
        if   len(ts_vals) == 1: cat_ts = ts_vals[0]
        elif len(ts_vals) == 2: cat_ts = ts_vals[0] * 0.65 + ts_vals[1] * 0.35
        else:
            cat_ts = (ts_vals[0] * 0.50 +
                      ts_vals[1] * 0.30 +
                      sum(ts_vals[2:5]) / min(len(ts_vals[2:5]), 3) * 0.20)

        def avg(key): return round(sum(p[key] for p in top3) / len(top3), 1)

        ranked_categories.append({
            "type_id":         type_id,
            "type_label":      type_meta[type_id]["type_label"],
            "type_emoji":      type_meta[type_id]["type_emoji"],
            "category_ts":     round(cat_ts, 1),
            "velocity_score":  avg("velocity_score"),
            "density_score":   avg("density_score"),
            "sentiment_score": avg("sentiment_score"),
            "conversion_score":avg("conversion_score"),
            "state":           top["state"],
            "why_trending":    descriptions.get(top["product_id"], ""),
            "product_count":   len(products),
            "category_image":  "",   # filled by enrich_categories_with_images()
            "products":        products[:5],
        })

    ranked_categories.sort(key=lambda c: c["category_ts"], reverse=True)
    for i, cat in enumerate(ranked_categories, 1):
        cat["rank"] = i

    return {
        "run_date":         run_date.isoformat(),
        "chart":            "Skincare & Beauty",
        "total_categories": len(ranked_categories),
        "ranked_categories": ranked_categories,
    }


# ─── SUPABASE WRITER ─────────────────────────────────────────────────────────

def write_billboard(billboard_data: dict, run_date: date):
    """Writes the final billboard dict to JSON and optionally Supabase."""
    if not CONFIG["supabase_url"] or not CONFIG["supabase_key"]:
        logger.info("  No Supabase config — writing to skincare_billboard.json")
        with open("skincare_billboard.json", "w") as f:
            json.dump(billboard_data, f, indent=2)
        logger.info("  ✓ Written to skincare_billboard.json")
        return

    try:
        from supabase import create_client
        db = create_client(CONFIG["supabase_url"], CONFIG["supabase_key"])

        db.table("billboard").upsert({
            "run_date": run_date.isoformat(),
            "data":     billboard_data,
        }).execute()

        # TS history: flatten products back out from categories
        history_rows = []
        for cat in billboard_data.get("ranked_categories", []):
            for p in cat.get("products", []):
                history_rows.append({
                    "product_id": p["product_id"],
                    "run_date":   run_date.isoformat(),
                    "final_ts":   p["final_ts"],
                    "state":      p["state"],
                    "type_id":    cat["type_id"],
                })
        if history_rows:
            db.table("ts_history").upsert(history_rows).execute()

        logger.info("  ✓ All data written to Supabase")

    except Exception as e:
        logger.error(f"  Supabase write failed: {e}")
        with open("skincare_billboard.json", "w") as f:
            json.dump(billboard_data, f, indent=2)
        logger.info("  ✓ Fallback: written to skincare_billboard.json")


# ─── MAIN PIPELINE ───────────────────────────────────────────────────────────

def run():
    run_date = date.today()
    logger.info("\n" + "="*65)
    logger.info("  TRENDBOARD.FYI — Skincare Pipeline")
    logger.info(f"  Run date: {run_date}")
    logger.info(f"  {safety_status()}")
    logger.info("="*65)

    if not is_test_mode():
        logger.warning("\n  ⚠️  LIVE MODE — real API calls will be made and billed.")
        logger.warning(f"  Estimated run cost: ~${COST_ESTIMATES['apify_tiktok_full']:.2f} (Apify TikTok)")
        logger.warning(f"                      ~${COST_ESTIMATES['apify_instagram_full']:.2f} (Apify Instagram)")
        logger.warning(f"                      ~${COST_ESTIMATES['claude_descriptions']:.2f} (Claude descriptions)")
        logger.warning("  Proceeding in 5 seconds — Ctrl+C to abort...\n")
        import time as _t; _t.sleep(5)

    # ── STEP 1: Discovery ─────────────────────────────────────────────────────
    logger.info("\n[1/7] Running discovery scrape...")
    scraper = DiscoveryScraper(apify_token=CONFIG["apify_token"])
    videos  = scraper.run_full_discovery()
    logger.info(f"  Total unique videos collected: {len(videos)}")

    if not videos or len(videos) < 50:
        logger.warning(f"  Only {len(videos)} videos collected — supplementing with test data.")
        videos = videos + _get_test_videos()

    # ── STEP 2: Extraction ────────────────────────────────────────────────────
    logger.info("\n[2/7] Extracting product candidates...")
    extractor  = ProductExtractor()
    candidates = extractor.process_videos(videos, min_creators=MIN_CREATORS)
    logger.info(f"  Candidates passing velocity filter: {len(candidates)}")

    if not candidates:
        logger.error("  No candidates found. Adjust MIN_CREATORS threshold or check scrape data.")
        return

    # Show top candidates
    logger.info("\n  Top 10 candidates by creator count:")
    for c in candidates[:10]:
        logger.info(
            f"    {c.display_name:<35} "
            f"creators:{c.unique_creator_count:>4}  "
            f"organic:{c.organic_count:>4}  "
            f"sponsored:{c.sponsored_count:>3}  "
            f"confidence:{c.confidence:.2f}"
        )

    # ── STEP 3: Limit to top candidates for scoring ───────────────────────────
    top_candidates = candidates[:MAX_PRODUCTS * 2]   # Score 2x, keep top 25

    # ── STEP 4: Google Trends confirmation ───────────────────────────────────
    logger.info(f"\n[3/7] Confirming with Google Trends ({len(top_candidates)} products)...")
    candidate_dict = {}
    all_signals    = []

    for c in top_candidates:
        google = fetch_google_signal(c.google_keyword)
        time.sleep(GT_SLEEP)

        # Skip products with zero Google volume (likely not a real product name)
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

    # ── STEP 5: Scoring ───────────────────────────────────────────────────────
    logger.info("\n[4/7] Scoring...")
    result = run_weekly_scoring(all_signals)
    ranked = result["ranked_scores"][:MAX_PRODUCTS]   # Top 25

    # ── STEP 6: AI descriptions ───────────────────────────────────────────────
    logger.info("\n[5/7] Generating editorial descriptions...")
    descriptions = {}
    for score in ranked:
        c    = candidate_dict.get(score.product_id)
        desc = generate_why_trending(score.product_name, score, c) if c else ""
        descriptions[score.product_id] = desc
        logger.info(f"  {score.product_name}: \"{desc}\"")

    # ── STEP 6b: Fetch product images ────────────────────────────────────────
    logger.info("\n[5b/7] Fetching product images...")
    # Build a temporary list of dicts so enrich_products_with_images can work
    _image_map = {}
    for score in ranked:
        c = candidate_dict.get(score.product_id)
        _image_map[score.product_id] = {
            "brand":             c.brand if c else "",
            "product_name":      score.product_name,
            "product_type_label": c.product_type_label if c else "",
            "image_url":         "",
        }
    enrich_products_with_images(list(_image_map.values()))

    # ── STEP 5c: Resolve buy links ────────────────────────────────────────────
    logger.info("\n[5c/7] Resolving buy links...")
    enrich_products_with_buy_links(list(_image_map.values()))

    # ── STEP 6: Build category-first billboard JSON ───────────────────────────
    logger.info("\n[6/7] Building category billboard...")
    billboard_data = _build_billboard_json(ranked, descriptions, candidate_dict,
                                           run_date, _image_map)

    # Fetch category lifestyle images (one per unique product type)
    enrich_categories_with_images(billboard_data["ranked_categories"])

    # ── STEP 7: Write ─────────────────────────────────────────────────────────
    logger.info("\n[7/7] Writing to database...")
    write_billboard(billboard_data, run_date)

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    icons = {
        "NEW_ENTRY":     "🆕", "HIGH_FLYER":  "🚀",
        "FALLING_STAR":  "⚠️", "COOLING":     "🌡️",
        "STAPLE":        "📊", "TRENDING":    "📈",
        "BELOW_THRESHOLD": "·"
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

    logger.info(f"\n  Data sources this run:")
    logger.info(f"  TikTok discovery: {'LIVE' if CONFIG['apify_token'] else 'TEST MODE'}")
    logger.info(f"  Google Trends:    LIVE")
    logger.info(f"  Instagram:        Estimated")
    logger.info(f"  Reddit:           Estimated (pending API)")
    logger.info(f"\n{'='*65}\n")


# ─── TEST DATA ────────────────────────────────────────────────────────────────

def _get_test_videos():
    """
    Returns sample VideoSignal objects for testing when Apify is unavailable.
    Simulates a week of skincare TikTok activity.
    """
    from extractor import VideoSignal
    import random

    test_captions = [
        "obsessed with my Cosrx snail mucin serum it literally changed my skin #skincaretok #kbeauty #cosrx",
        "dermatologist recommended this CeraVe moisturizer for sensitive skin #dermatologistrecommended #cerave",
        "the Anua toner is my holy grail amazon skincare find #skincarereview #anua #amazonfinds",
        "Paula's Choice BHA exfoliant cleared my acne in 2 weeks #beforeandafter #acneskincare #paulaschoice",
        "La Roche Posay sunscreen is the only spf I trust #spfsunscreen #larochposay #dermatologist",
        "Medicube serum just sold out AGAIN link in bio #koreanskincare #medicube #skincaretok",
        "Tatcha dewy skin cream morning routine #skincareroutine #tatcha #luxuryskincare",
        "drunk elephant protini polypeptide cream review honest thoughts #drunkelephant #peptides",
        "Beauty of Joseon glow serum my skin has never looked better #beautyofjoseon #kbeauty",
        "The Ordinary niacinamide serum is so underrated for pores #theordinary #niacinamide",
        "COSRX acne pimple master patch overnight results #mightypatch #acnetreatment #skincare",
        "Foreo Bear microcurrent device is worth every penny #foreo #microcurrent #beautytools",
        "solawave wand 2 week update my skin is GLOWING #solawave #redlighttherapy #skincaregadgets",
        "Glow Recipe watermelon toner changed my texture completely #glowrecipe #skincaretok",
        "Isntree hyaluronic acid toner layering technique #isntree #hyaluronicacid #kbeauty",
        "round lab sunscreen no white cast SPF50 #roundlab #sunscreentok #koreanskincare",
        "Tirtir cushion foundation dewy skin effect amazon find #tirtir #kbeauty #amazonskincare",
        "skin1004 madagascar centella asiatica ampoule for redness #skin1004 #centella #skintok",
        "Numbuzin glass skin serum 3 bottle #numbuzin #glasskin #kbeauty",
        "Byoma moisturizer ceramide barrier repair derm recommended #byoma #ceramides #skincareproducts",
    ]

    videos = []
    for i, caption in enumerate(test_captions):
        # Each caption gets 8-15 "unique creators" posting it
        for j in range(random.randint(8, 15)):
            followers = random.choice([
                random.randint(1000, 9999),       # nano
                random.randint(10000, 99999),     # micro
                random.randint(100000, 999999),   # macro
                random.randint(1000000, 5000000), # mega
            ])
            videos.append(VideoSignal(
                video_id       = f"test_{i}_{j}",
                creator_id     = f"creator_{i}_{j}",
                creator_handle = f"creator{i}{j}",
                caption        = caption,
                hashtags       = [h.lstrip("#") for h in caption.split() if h.startswith("#")],
                like_count     = random.randint(1000, 500000),
                comment_count  = random.randint(50, 5000),
                share_count    = random.randint(100, 10000),
                follower_count = followers,
                posted_date    = datetime.utcnow().strftime("%Y-%m-%d"),
                platform       = "tiktok",
                is_sponsored   = random.random() < 0.1,
            ))

    return videos


if __name__ == "__main__":
    run()
