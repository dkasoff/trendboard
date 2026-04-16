"""
trendboard.fyi — Dynamic Trend Score (TS) Engine v2
=====================================================
Multi-Signal Weighting Architecture
Author: SynchroVBC Corp

Core Formula:
    TS = (w_v * V) + (w_d * D) + (w_s * S) + (w_c * C)

    V = Velocity       — Volume-weighted Google Trends WoW growth    weight: 22%
    D = Density        — Creator-tier-weighted community spread       weight: 28%
    S = Sentiment      — Split product + category sentiment           weight: 18%
    C = Conversion     — Purchase intent signals                      weight: 32%

Changes v1 → v2:
    [1] Sponsorship filter capped at ±15 pts (was uncapped, caused +46pt swings)
    [2] Velocity is now Volume-Weighted — high growth from low base is discounted
    [3] Density uses Creator Tier weighting (nano/micro/macro/mega)
    [4] Reddit comment depth raised to 10pt ceiling, 3x multiplier for niche subs
    [5] Sentiment split into Product Sentiment + Category Sentiment
    [6] Longevity is now a continuous multiplier, not binary pass/fail
    [7] COOLING early-warning state added — triggers before Falling Star
    [8] Cross-Pollination now classifies Lifecycle Stage

Weights updated:
    V: 25% → 22%
    D: 30% → 28%
    S: 15% → 18%
    C: 30% → 32%
"""

import math
from datetime import datetime
from dataclasses import dataclass, field


# ─── WEIGHTS (v2) ────────────────────────────────────────────────────────────

WEIGHTS = {
    "velocity":   0.22,
    "density":    0.28,
    "sentiment":  0.18,
    "conversion": 0.32,
}

SPONSORSHIP_MAX_ADJUSTMENT = 15.0   # [FIX 1] Cap ±15 pts
SPONSORED_DISCOUNT         = 0.50
ORGANIC_BOOST              = 1.50
CROSS_POLLINATION_MIN      = 3

TS_NEW_ENTRY_THRESHOLD     = 60
HISTORY_WINDOW_DAYS        = 180

# [FIX 6] Continuous longevity multiplier table
LONGEVITY_MULTIPLIERS = [
    (0,   7,  0.60),
    (8,  14,  0.80),
    (15, 21,  0.90),
    (22, 30,  1.00),
    (31, 999, 1.05),
]

PLATFORMS = ["google", "tiktok", "instagram", "reddit"]


# ─── DATA STRUCTURES ─────────────────────────────────────────────────────────

@dataclass
class GoogleSignal:
    current_volume: float
    prior_volume: float
    is_breakout: bool
    days_positive_velocity: int
    related_rising_queries: int


@dataclass
class TikTokSignal:
    total_video_count: int
    unique_creator_count: int
    sound_reuse_48h: int
    sponsored_post_count: int
    organic_post_count: int
    unboxing_count: int
    link_in_bio_count: int
    just_ordered_count: int
    restock_count: int
    must_buy_phrases: int
    negative_phrases: int
    # [FIX 3] Creator tier counts
    nano_creators: int  = 0    # <10k followers
    micro_creators: int = 0    # 10k–100k
    macro_creators: int = 0    # 100k–1M
    mega_creators: int  = 0    # 1M+
    # [FIX 5] Category-level sentiment
    category_positive_phrases: int  = 0
    category_negative_phrases: int  = 0
    # [FIX 7] Prior week sponsored ratio for Cooling detection
    prior_week_sponsored_ratio: float = 0.0


@dataclass
class InstagramSignal:
    save_count: int
    share_count: int
    like_count: int
    comment_count: int
    sponsored_post_count: int
    organic_post_count: int
    unique_creator_count: int


@dataclass
class RedditSignal:
    unique_subreddit_count: int
    total_post_count: int
    avg_comment_depth: float
    high_karma_post_count: int
    pros_cons_thread_count: int
    must_buy_phrases: int
    negative_phrases: int
    consumer_subreddit_hits: int
    niche_subreddit_hits: int = 0   # [FIX 4] Hits in high-signal niche subs


@dataclass
class ProductSignals:
    product_id: str
    product_name: str
    category: str
    google: GoogleSignal
    tiktok: TikTokSignal
    instagram: InstagramSignal
    reddit: RedditSignal
    ts_history: list = field(default_factory=list)
    days_in_database: int = 0


@dataclass
class TrendScore:
    product_id: str
    product_name: str
    category: str
    velocity_score: float
    density_score: float
    sentiment_score: float
    conversion_score: float
    product_sentiment: float      # [FIX 5]
    category_sentiment: float     # [FIX 5]
    longevity_multiplier: float   # [FIX 6]
    lifecycle_stage: str          # [FIX 8]
    raw_ts: float
    sponsorship_penalty: float
    organic_boost: float
    platform_count: int
    final_ts: float
    state: str
    platforms_present: list
    acceleration: float
    scored_at: str


# ─── [FIX 2] VOLUME-WEIGHTED VELOCITY ────────────────────────────────────────

def score_velocity(g: GoogleSignal) -> float:
    """
    V — Volume-weighted WoW growth.
    Discounts high growth from a low absolute base.
    A product at index 2 → 100 is less reliable than 40 → 100.
    """
    if g.prior_volume == 0:
        wow_growth = 100.0 if g.current_volume > 0 else 0.0
    else:
        wow_growth = ((g.current_volume - g.prior_volume) / g.prior_volume) * 100

    wow_growth = min(wow_growth, 500.0)
    wow_growth = max(wow_growth, -100.0)

    if wow_growth >= 0:
        base_score = 30 + (wow_growth / 500) * 70
    else:
        base_score = 30 + (wow_growth / 100) * 30

    # [FIX 2] Volume confidence multiplier
    vol = g.current_volume
    if vol < 10:
        volume_confidence = 0.30
    elif vol < 40:
        volume_confidence = 0.30 + ((vol - 10) / 30) * 0.50
    else:
        volume_confidence = 0.80 + ((vol - 40) / 60) * 0.20

    base_score = base_score * volume_confidence

    # Breakout bonus — discounted for low-volume breakouts
    if g.is_breakout and g.current_volume >= 30:
        base_score = min(base_score * 1.20, 100)
    elif g.is_breakout:
        base_score = min(base_score * 1.05, 100)

    # Staple penalty
    if g.current_volume > 60 and wow_growth < 5:
        base_score *= 0.60

    rising_bonus = min(g.related_rising_queries * 2, 10)
    base_score   = min(base_score + rising_bonus, 100)

    return round(base_score, 2)


# ─── [FIX 3+4] CREATOR-TIER-WEIGHTED DENSITY ─────────────────────────────────

def score_density(tiktok: TikTokSignal, instagram: InstagramSignal,
                  reddit: RedditSignal) -> float:
    """
    D — Creator-tier-weighted community spread.

    FIX 3: Tier weights: nano=1x, micro=3x, macro=8x, mega=20x
    FIX 4: Reddit depth ceiling raised to 10pts with niche sub 3x bonus
    """
    has_tier_data = (tiktok.nano_creators + tiktok.micro_creators +
                     tiktok.macro_creators + tiktok.mega_creators) > 0

    if has_tier_data:
        weighted = (
            tiktok.nano_creators  * 1  +
            tiktok.micro_creators * 3  +
            tiktok.macro_creators * 8  +
            tiktok.mega_creators  * 20
        )
        tk_creator_score = min(weighted / 500, 1.0) * 35
    else:
        tk_creator_score = min(tiktok.unique_creator_count / 500, 1.0) * 28

    sound_score      = min(tiktok.sound_reuse_48h / 1000, 1.0) * 18
    ig_creator_score = min(instagram.unique_creator_count / 200, 1.0) * 12
    reddit_spread    = min(reddit.unique_subreddit_count / 10, 1.0) * 8
    reddit_quality   = min(reddit.high_karma_post_count / 20, 1.0) * 8
    reddit_consumer  = min(reddit.consumer_subreddit_hits / 5, 1.0) * 5

    # [FIX 4] Raised ceiling + niche sub 3x
    base_depth_score  = min(reddit.avg_comment_depth / 10, 1.0) * 5
    niche_depth_bonus = min(reddit.niche_subreddit_hits / 3, 1.0) * 5
    depth_score       = base_depth_score + niche_depth_bonus   # Max 10 pts

    validation_bonus  = min(reddit.pros_cons_thread_count * 4, 9)

    raw = (tk_creator_score + sound_score + ig_creator_score +
           reddit_spread + reddit_quality + reddit_consumer +
           depth_score + validation_bonus)

    return round(min(raw, 100), 2)


# ─── [FIX 5] SPLIT SENTIMENT ─────────────────────────────────────────────────

def score_sentiment(tiktok: TikTokSignal,
                    reddit: RedditSignal) -> tuple[float, float, float]:
    """
    S — Split product + category sentiment.
    Final S = (product_sentiment * 0.70) + (category_sentiment * 0.30)
    Returns: (final_s, product_sentiment, category_sentiment)
    """
    # Product sentiment
    prod_pos   = (tiktok.must_buy_phrases + reddit.must_buy_phrases +
                  tiktok.unboxing_count * 2)
    prod_neg   = tiktok.negative_phrases + reddit.negative_phrases
    prod_total = prod_pos + prod_neg

    if prod_total == 0:
        product_sentiment = 50.0
    else:
        ratio      = prod_pos / prod_total
        raw_prod   = 5 + (ratio * 90)
        confidence = min(prod_total / 100, 1.0)
        product_sentiment = (raw_prod * confidence) + (50 * (1 - confidence))

    # Category sentiment
    cat_pos   = tiktok.category_positive_phrases
    cat_neg   = tiktok.category_negative_phrases
    cat_total = cat_pos + cat_neg

    if cat_total == 0:
        category_sentiment = min(product_sentiment * 1.05, 95.0)
    else:
        ratio      = cat_pos / cat_total
        raw_cat    = 5 + (ratio * 90)
        confidence = min(cat_total / 50, 1.0)
        category_sentiment = (raw_cat * confidence) + (50 * (1 - confidence))

    final_s = (product_sentiment * 0.70) + (category_sentiment * 0.30)
    return round(final_s, 2), round(product_sentiment, 2), round(category_sentiment, 2)


# ─── CONVERSION (restock now highest-weight signal) ──────────────────────────

def score_conversion(tiktok: TikTokSignal, instagram: InstagramSignal) -> float:
    """
    C — Purchase intent. Weight raised to 32% in v2.
    Restock is now the strongest signal — demand > supply = real money moving.
    """
    restock_score      = min(tiktok.restock_count     / 50,    1.0) * 38
    just_ordered_score = min(tiktok.just_ordered_count / 100,   1.0) * 32
    save_score         = min(instagram.save_count      / 5000,  1.0) * 28
    link_in_bio_score  = min(tiktok.link_in_bio_count  / 200,   1.0) * 24
    share_score        = min(instagram.share_count     / 1000,  1.0) * 10
    like_score         = min(instagram.like_count      / 50000, 1.0) * 4

    raw   = (restock_score + just_ordered_score + save_score +
             link_in_bio_score + share_score + like_score)
    score = min((raw / 136) * 100, 100)
    return round(score, 2)


# ─── [FIX 1] CAPPED SPONSORSHIP FILTER ───────────────────────────────────────

def apply_sponsorship_filter(raw_ts: float, tiktok: TikTokSignal,
                              instagram: InstagramSignal) -> tuple[float, float]:
    """FIX 1: Sponsorship nudge capped at ±15 pts."""
    total_tk = max(tiktok.sponsored_post_count + tiktok.organic_post_count, 1)
    total_ig = max(instagram.sponsored_post_count + instagram.organic_post_count, 1)

    sponsored_ratio = ((tiktok.sponsored_post_count + instagram.sponsored_post_count) /
                       (total_tk + total_ig))
    organic_ratio   = ((tiktok.organic_post_count + tiktok.unboxing_count) /
                       max(total_tk, 1))

    sponsored_penalty = sponsored_ratio * (1 - SPONSORED_DISCOUNT)
    organic_gain      = organic_ratio   * (ORGANIC_BOOST - 1)
    raw_adjustment    = (organic_gain - sponsored_penalty) * raw_ts

    capped = max(min(raw_adjustment, SPONSORSHIP_MAX_ADJUSTMENT),
                 -SPONSORSHIP_MAX_ADJUSTMENT)

    return round(max(raw_ts + capped, 0), 2), round(capped, 2)


# ─── [FIX 6] CONTINUOUS LONGEVITY MULTIPLIER ─────────────────────────────────

def get_longevity_multiplier(google: GoogleSignal) -> tuple[float, bool]:
    """FIX 6: Continuous ramp instead of binary gate."""
    days = google.days_positive_velocity
    for low, high, mult in LONGEVITY_MULTIPLIERS:
        if low <= days <= high:
            return mult, (mult >= 1.0)
    return 1.05, True


# ─── [FIX 8] PLATFORM COUNT + LIFECYCLE STAGE ────────────────────────────────

def count_platforms(tiktok: TikTokSignal, instagram: InstagramSignal,
                    reddit: RedditSignal,
                    google: GoogleSignal) -> tuple[int, list, str]:
    """FIX 8: Returns platform count, list, and lifecycle stage."""
    platforms = []
    if google.current_volume > 20:          platforms.append("google")
    if tiktok.unique_creator_count > 10:    platforms.append("tiktok")
    if instagram.save_count > 100:          platforms.append("instagram")
    if reddit.total_post_count > 3:         platforms.append("reddit")

    count       = len(platforms)
    pset        = set(platforms)
    total_posts = max(tiktok.sponsored_post_count + tiktok.organic_post_count, 1)
    spon_ratio  = tiktok.sponsored_post_count / total_posts

    if count == 4 and spon_ratio > 0.50:
        stage = "SATURATED"
    elif count == 4:
        stage = "MASS_MARKET"
    elif "google" in pset and "reddit" in pset and count == 2:
        stage = "EARLY"
    elif "tiktok" in pset and "google" in pset:
        stage = "EMERGING"
    elif count <= 1:
        stage = "NICHE"
    else:
        stage = "EMERGING"

    return count, platforms, stage


# ─── [FIX 7] STATE CLASSIFIER WITH COOLING ───────────────────────────────────

def classify_state(final_ts: float, velocity_score: float,
                   ts_history: list, days_in_db: int,
                   tiktok: TikTokSignal) -> tuple[str, float]:
    """
    FIX 7: Adds COOLING — one week earlier than Falling Star.
    Triggers: TS > 60 + first_deriv < 0 + sponsored ratio spike > 15% WoW
    """
    first_deriv  = 0.0
    acceleration = 0.0

    if len(ts_history) >= 2:
        first_deriv = ts_history[-1][1] - ts_history[-2][1]

    if len(ts_history) >= 3:
        t1, t2, t3    = ts_history[-3][1], ts_history[-2][1], ts_history[-1][1]
        acceleration  = (t3 - t2) - (t2 - t1)

    total_posts  = max(tiktok.sponsored_post_count + tiktok.organic_post_count, 1)
    spon_ratio   = tiktok.sponsored_post_count / total_posts
    spon_delta   = spon_ratio - tiktok.prior_week_sponsored_ratio

    # NEW ENTRY
    if final_ts >= TS_NEW_ENTRY_THRESHOLD:
        if len(ts_history) == 0 or all(h[1] < 20 for h in ts_history):
            return "NEW_ENTRY", acceleration

    # FALLING STAR — confirmed multi-week decline
    if final_ts >= 55 and acceleration < -5 and len(ts_history) >= 3:
        return "FALLING_STAR", acceleration

    # [FIX 7] COOLING — early warning, one week before Falling Star
    if final_ts >= 60 and first_deriv < 0 and spon_delta > 0.15 and len(ts_history) >= 2:
        return "COOLING", acceleration

    # [FIX 7] COOLING — checked before BELOW_THRESHOLD so it can trigger
    # even on lower-scoring products that are actively decelerating with ad spend spike
    if (final_ts >= 25 and
        first_deriv < 0 and
        spon_delta > 0.15 and
        len(ts_history) >= 2):
        return "COOLING", acceleration

    # STAPLE
    if final_ts >= 50 and velocity_score < 35:
        return "STAPLE", acceleration

    # TRENDING
    if final_ts >= 40:
        return "TRENDING", acceleration

    return "BELOW_THRESHOLD", acceleration


# ─── MAIN SCORER ─────────────────────────────────────────────────────────────

def calculate_trend_score(signals: ProductSignals) -> TrendScore:
    V                                        = score_velocity(signals.google)
    D                                        = score_density(signals.tiktok, signals.instagram, signals.reddit)
    S, prod_sent, cat_sent                   = score_sentiment(signals.tiktok, signals.reddit)
    C                                        = score_conversion(signals.tiktok, signals.instagram)

    raw_ts = (WEIGHTS["velocity"] * V + WEIGHTS["density"] * D +
              WEIGHTS["sentiment"] * S + WEIGHTS["conversion"] * C)

    adjusted_ts, net_adj  = apply_sponsorship_filter(raw_ts, signals.tiktok, signals.instagram)
    longevity_mult, _     = get_longevity_multiplier(signals.google)
    adjusted_ts           = adjusted_ts * longevity_mult

    platform_count, platforms_present, lifecycle_stage = count_platforms(
        signals.tiktok, signals.instagram, signals.reddit, signals.google
    )

    if platform_count == 1:   adjusted_ts *= 0.75
    elif platform_count == 2: adjusted_ts *= 0.90
    if lifecycle_stage == "EARLY": adjusted_ts = min(adjusted_ts * 1.05, 100)

    final_ts = round(min(adjusted_ts, 100), 2)

    state, acceleration = classify_state(
        final_ts, V, signals.ts_history, signals.days_in_database, signals.tiktok
    )

    return TrendScore(
        product_id           = signals.product_id,
        product_name         = signals.product_name,
        category             = signals.category,
        velocity_score       = V,
        density_score        = D,
        sentiment_score      = S,
        conversion_score     = C,
        product_sentiment    = prod_sent,
        category_sentiment   = cat_sent,
        longevity_multiplier = longevity_mult,
        lifecycle_stage      = lifecycle_stage,
        raw_ts               = round(raw_ts, 2),
        sponsorship_penalty  = round(net_adj, 2),
        organic_boost        = max(net_adj, 0.0),
        platform_count       = platform_count,
        final_ts             = final_ts,
        state                = state,
        platforms_present    = platforms_present,
        acceleration         = round(acceleration, 2),
        scored_at            = datetime.utcnow().isoformat()
    )


# ─── RANKER ──────────────────────────────────────────────────────────────────

def rank_products(scores: list[TrendScore]) -> list[TrendScore]:
    sorted_scores  = sorted(scores, key=lambda x: x.final_ts, reverse=True)
    eligible       = [s for s in sorted_scores if s.platform_count >= CROSS_POLLINATION_MIN]
    ineligible     = [s for s in sorted_scores if s.platform_count < CROSS_POLLINATION_MIN]
    saturated      = [s for s in eligible if s.lifecycle_stage == "SATURATED"]
    non_saturated  = [s for s in eligible if s.lifecycle_stage != "SATURATED"]

    final_ranked = (
        non_saturated[:15] +
        saturated +
        sorted(non_saturated[15:] + ineligible, key=lambda x: x.final_ts, reverse=True)
    )

    top_5 = final_ranked[:5]
    if top_5:
        max_v = max(s.velocity_score for s in top_5)
        for s in top_5:
            if s.velocity_score == max_v and s.state == "TRENDING":
                s.state = "HIGH_FLYER"

    return final_ranked


# ─── WEEKLY RUN ──────────────────────────────────────────────────────────────

def run_weekly_scoring(products: list[ProductSignals]) -> dict:
    scores = [calculate_trend_score(p) for p in products]
    ranked = rank_products(scores)

    return {
        "ranked_scores":         ranked,
        "run_date":              datetime.utcnow().isoformat(),
        "total_products_scored": len(scores),
        "new_entries":           [s for s in ranked if s.state == "NEW_ENTRY"],
        "falling_stars":         [s for s in ranked if s.state == "FALLING_STAR"],
        "cooling":               [s for s in ranked if s.state == "COOLING"],
        "high_flyers":           [s for s in ranked if s.state == "HIGH_FLYER"],
        "early_stage":           [s for s in ranked if s.lifecycle_stage == "EARLY"],
    }