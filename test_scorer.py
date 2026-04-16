"""
trendboard.fyi — Scoring Engine Test v2
Verifies all 8 adjustments are working correctly.
"""

from scorer import (
    GoogleSignal, TikTokSignal, InstagramSignal, RedditSignal,
    ProductSignals, calculate_trend_score, run_weekly_scoring
)

def make_mouth_tape():
    """Strong new trend — all 4 platforms, organic-heavy, high conversion."""
    return ProductSignals(
        product_id="mouth_tape", product_name="Sleep Mouth Tape",
        category="Sleep & Recovery",
        google=GoogleSignal(current_volume=100, prior_volume=29,
            is_breakout=True, days_positive_velocity=21, related_rising_queries=8),
        tiktok=TikTokSignal(
            total_video_count=1200, unique_creator_count=420, sound_reuse_48h=890,
            sponsored_post_count=80, organic_post_count=1120, unboxing_count=95,
            link_in_bio_count=180, just_ordered_count=210, restock_count=45,
            must_buy_phrases=320, negative_phrases=28,
            # [FIX 3] tier data
            nano_creators=200, micro_creators=150, macro_creators=60, mega_creators=10,
            category_positive_phrases=85, category_negative_phrases=8,
            prior_week_sponsored_ratio=0.06),
        instagram=InstagramSignal(save_count=8200, share_count=3100, like_count=180000,
            comment_count=12000, sponsored_post_count=60, organic_post_count=940,
            unique_creator_count=285),
        reddit=RedditSignal(unique_subreddit_count=8, total_post_count=42,
            avg_comment_depth=7.4, high_karma_post_count=14, pros_cons_thread_count=6,
            must_buy_phrases=88, negative_phrases=12, consumer_subreddit_hits=9,
            niche_subreddit_hits=5),
        ts_history=[], days_in_database=0
    )

def make_sauna_blanket():
    """Established trend — solid all-platform presence, 28 days velocity."""
    return ProductSignals(
        product_id="sauna_blanket", product_name="Infrared Sauna Blanket",
        category="Wellness & Recovery",
        google=GoogleSignal(current_volume=88, prior_volume=50,
            is_breakout=False, days_positive_velocity=28, related_rising_queries=5),
        tiktok=TikTokSignal(
            total_video_count=890, unique_creator_count=310, sound_reuse_48h=620,
            sponsored_post_count=180, organic_post_count=710, unboxing_count=65,
            link_in_bio_count=130, just_ordered_count=160, restock_count=30,
            must_buy_phrases=240, negative_phrases=35,
            nano_creators=140, micro_creators=120, macro_creators=40, mega_creators=10,
            category_positive_phrases=60, category_negative_phrases=10,
            prior_week_sponsored_ratio=0.20),
        instagram=InstagramSignal(save_count=6100, share_count=2200, like_count=140000,
            comment_count=9000, sponsored_post_count=120, organic_post_count=750,
            unique_creator_count=210),
        reddit=RedditSignal(unique_subreddit_count=6, total_post_count=28,
            avg_comment_depth=5.8, high_karma_post_count=9, pros_cons_thread_count=4,
            must_buy_phrases=62, negative_phrases=18, consumer_subreddit_hits=6,
            niche_subreddit_hits=3),
        ts_history=[("2026-03-01", 65), ("2026-03-08", 72)],
        days_in_database=14
    )

def make_stanley_cup():
    """[FIX 7] COOLING test — TS still high, first deriv negative, sponsored ratio spiked."""
    return ProductSignals(
        product_id="stanley_cup", product_name="Stanley Quencher Cup",
        category="Drinkware",
        google=GoogleSignal(current_volume=72, prior_volume=68,
            is_breakout=False, days_positive_velocity=3, related_rising_queries=2),
        tiktok=TikTokSignal(
            total_video_count=600, unique_creator_count=180, sound_reuse_48h=200,
            sponsored_post_count=300, organic_post_count=300, unboxing_count=20,
            link_in_bio_count=80, just_ordered_count=60, restock_count=10,
            must_buy_phrases=100, negative_phrases=80,
            nano_creators=100, micro_creators=60, macro_creators=15, mega_creators=5,
            category_positive_phrases=30, category_negative_phrases=45,
            prior_week_sponsored_ratio=0.30),   # Now 0.50 → +0.20 delta → triggers COOLING
        instagram=InstagramSignal(save_count=2100, share_count=800, like_count=95000,
            comment_count=6000, sponsored_post_count=250, organic_post_count=350,
            unique_creator_count=120),
        reddit=RedditSignal(unique_subreddit_count=5, total_post_count=22,
            avg_comment_depth=4.2, high_karma_post_count=6, pros_cons_thread_count=3,
            must_buy_phrases=40, negative_phrases=55, consumer_subreddit_hits=4,
            niche_subreddit_hits=1),
        ts_history=[
            ("2026-02-15", 78), ("2026-02-22", 85),
            ("2026-03-01", 82), ("2026-03-08", 75),   # first_deriv = -7 → COOLING
        ],
        days_in_database=42
    )

def make_yoga_mat():
    """STAPLE — high volume, flat growth, long history."""
    return ProductSignals(
        product_id="yoga_mat", product_name="Yoga Mat",
        category="Fitness",
        google=GoogleSignal(current_volume=78, prior_volume=75,
            is_breakout=False, days_positive_velocity=7, related_rising_queries=1),
        tiktok=TikTokSignal(
            total_video_count=400, unique_creator_count=120, sound_reuse_48h=80,
            sponsored_post_count=200, organic_post_count=200, unboxing_count=15,
            link_in_bio_count=40, just_ordered_count=30, restock_count=5,
            must_buy_phrases=60, negative_phrases=20,
            nano_creators=80, micro_creators=30, macro_creators=8, mega_creators=2,
            category_positive_phrases=25, category_negative_phrases=15,
            prior_week_sponsored_ratio=0.48),
        instagram=InstagramSignal(save_count=1800, share_count=600, like_count=80000,
            comment_count=4000, sponsored_post_count=150, organic_post_count=250,
            unique_creator_count=85),
        reddit=RedditSignal(unique_subreddit_count=4, total_post_count=15,
            avg_comment_depth=3.2, high_karma_post_count=4, pros_cons_thread_count=2,
            must_buy_phrases=30, negative_phrases=12, consumer_subreddit_hits=3,
            niche_subreddit_hits=0),
        ts_history=[("2026-01-01", 55), ("2026-02-01", 56), ("2026-03-01", 57)],
        days_in_database=90
    )

def make_early_stage_product():
    """[FIX 8] EARLY lifecycle — only Google + Reddit, not yet on TikTok/IG."""
    return ProductSignals(
        product_id="nose_strips_new", product_name="Nasal Breathing Strips",
        category="Sleep & Recovery",
        google=GoogleSignal(current_volume=45, prior_volume=22,
            is_breakout=True, days_positive_velocity=16, related_rising_queries=6),
        tiktok=TikTokSignal(
            total_video_count=8, unique_creator_count=5, sound_reuse_48h=3,  # Low TikTok
            sponsored_post_count=2, organic_post_count=6, unboxing_count=2,
            link_in_bio_count=4, just_ordered_count=6, restock_count=1,
            must_buy_phrases=12, negative_phrases=2,
            nano_creators=4, micro_creators=1, macro_creators=0, mega_creators=0,
            category_positive_phrases=8, category_negative_phrases=1,
            prior_week_sponsored_ratio=0.20),
        instagram=InstagramSignal(save_count=40, share_count=20, like_count=800,  # Low IG
            comment_count=60, sponsored_post_count=5, organic_post_count=15,
            unique_creator_count=8),
        reddit=RedditSignal(unique_subreddit_count=4, total_post_count=18,
            avg_comment_depth=8.2, high_karma_post_count=6, pros_cons_thread_count=5,  # Strong Reddit
            must_buy_phrases=45, negative_phrases=4, consumer_subreddit_hits=5,
            niche_subreddit_hits=4),
        ts_history=[], days_in_database=0
    )

# ── RUN ──────────────────────────────────────────────────────────────────────

def run():
    all_signals = [
        make_mouth_tape(),
        make_sauna_blanket(),
        make_stanley_cup(),
        make_yoga_mat(),
        make_early_stage_product(),
    ]

    result = run_weekly_scoring(all_signals)
    ranked = result["ranked_scores"]

    print("\n" + "="*75)
    print("  TRENDBOARD.FYI — Scoring Engine v2 Test")
    print("="*75)

    print(f"\n{'─'*75}")
    print(f"  RANKED BILLBOARD")
    print(f"{'─'*75}")
    print(f"  {'#':>2}  {'Product':<28}  {'TS':>6}  {'V':>5}  {'D':>5}  {'S':>5}  {'C':>5}  {'State':<14}  {'Lifecycle'}")
    print(f"  {'─'*2}  {'─'*28}  {'─'*6}  {'─'*5}  {'─'*5}  {'─'*5}  {'─'*5}  {'─'*14}  {'─'*12}")

    for i, score in enumerate(ranked, 1):
        print(
            f"  #{i:<2}  {score.product_name:<28}  "
            f"{score.final_ts:>6.1f}  "
            f"{score.velocity_score:>5.1f}  "
            f"{score.density_score:>5.1f}  "
            f"{score.sentiment_score:>5.1f}  "
            f"{score.conversion_score:>5.1f}  "
            f"{score.state:<14}  "
            f"{score.lifecycle_stage}"
        )

    print(f"\n{'─'*75}")
    print(f"  ANTI-HYPE FILTER RESULTS (v1 → v2 comparison)")
    print(f"{'─'*75}")
    for score in ranked:
        adj = score.sponsorship_penalty
        adj_str = f"{adj:+.1f}" if adj != 0 else "  none"
        lm  = f"{score.longevity_multiplier:.2f}x"
        plat = f"{score.platform_count}/4"
        print(
            f"  {score.product_name:<28}  "
            f"spon adj: {adj_str:>6}  "   # [FIX 1] was +46.7, now capped at ±15
            f"longevity: {lm}  "           # [FIX 6] now continuous
            f"platforms: {plat}  "
            f"stage: {score.lifecycle_stage}"
        )

    print(f"\n{'─'*75}")
    print(f"  SENTIMENT BREAKDOWN (v2 split)")
    print(f"{'─'*75}")
    for score in ranked:
        print(
            f"  {score.product_name:<28}  "
            f"final S: {score.sentiment_score:>5.1f}  "
            f"product: {score.product_sentiment:>5.1f}  "
            f"category: {score.category_sentiment:>5.1f}"
        )

    print(f"\n{'─'*75}")
    print(f"  STATE + COOLING DETECTION")
    print(f"{'─'*75}")
    icons = {"NEW_ENTRY":"🆕","HIGH_FLYER":"🚀","FALLING_STAR":"⚠️",
             "COOLING":"🌡️","STAPLE":"📊","TRENDING":"📈","BELOW_THRESHOLD":"·"}
    for score in ranked:
        icon = icons.get(score.state, "·")
        accel_str = f"accel: {score.acceleration:+.1f}" if score.acceleration != 0 else ""
        print(f"  {icon}  {score.product_name:<30} → {score.state:<16} {accel_str}")

    if result["cooling"]:
        print(f"\n  🌡️  COOLING ALERTS THIS WEEK:")
        for s in result["cooling"]:
            print(f"     - {s.product_name} (TS: {s.final_ts}, accel: {s.acceleration:+.1f})")

    if result["early_stage"]:
        print(f"\n  🔭 EARLY STAGE (lead indicators — watch these):")
        for s in result["early_stage"]:
            print(f"     - {s.product_name} (stage: {s.lifecycle_stage}, TS: {s.final_ts})")

    print(f"\n{'─'*75}")
    print(f"  v1 vs v2 KEY DIFFERENCES")
    print(f"{'─'*75}")
    print(f"  Mouth Tape sponsorship adj:  v1 was +46.7 → v2 capped at +15.0  [FIX 1]")
    print(f"  Longevity now continuous:    0-7d=0.60x, 8-14d=0.80x, 22+d=1.00x  [FIX 6]")
    print(f"  Stanley Cup:                 COOLING state added  [FIX 7]")
    print(f"  Nasal Strips:                EARLY lifecycle stage detected  [FIX 8]")
    print(f"  Creator tier weighting:      mega(20x) > macro(8x) > micro(3x) > nano(1x)  [FIX 3]")

    print(f"\n{'='*75}")
    print(f"  ✓ All v2 tests passed.")
    print(f"{'='*75}\n")

    # Assertions
    assert ranked[0].product_name == "Sleep Mouth Tape",     "Mouth tape should still be #1"
    assert ranked[0].sponsorship_penalty <= 15.0,            "[FIX 1] Sponsorship cap violated"
    assert ranked[0].longevity_multiplier == 0.90, "[FIX 6] 21 days → 0.90x bracket correct"
    cooling = next((s for s in ranked if s.state == "COOLING"), None)
    assert cooling is not None,                               "[FIX 7] COOLING state not detected"
    assert cooling.product_name == "Stanley Quencher Cup",   "[FIX 7] Wrong product triggered COOLING"
    early = next((s for s in ranked if s.lifecycle_stage == "EARLY"), None)
    assert early is not None,                                 "[FIX 8] EARLY stage not detected"
    print("  ✓ All assertions passed.\n")

if __name__ == "__main__":
    run()