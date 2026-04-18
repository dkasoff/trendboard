"""
trendboard.fyi — Pipeline v1 (simplified)
"""

from pytrends.request import TrendReq
import time
from scorer import (
    GoogleSignal, TikTokSignal, InstagramSignal, RedditSignal,
    ProductSignals, run_weekly_scoring
)

PRODUCTS = [
    {"id": "mouth_tape",    "name": "Sleep Mouth Tape",         "cat": "Sleep & Recovery",    "kw": "sleep mouth tape"},
    {"id": "sauna_blanket", "name": "Infrared Sauna Blanket",   "cat": "Wellness & Recovery", "kw": "infrared sauna blanket"},
    {"id": "blue_light",    "name": "Blue Light Therapy",       "cat": "Skincare",            "kw": "blue light therapy"},
    {"id": "flat_back",     "name": "Flat Back Earrings",       "cat": "Jewelry",             "kw": "flat back earrings"},
    {"id": "ipl_removal",   "name": "At-Home IPL Hair Removal", "cat": "Beauty & Grooming",   "kw": "IPL hair removal"},
    {"id": "sleep_earbuds", "name": "Sleep Earbuds",            "cat": "Sleep & Audio",       "kw": "sleep earbuds"},
]

def fetch_google(kw):
    try:
        pt = TrendReq(hl='en-US', tz=360, timeout=(10,25))
        pt.build_payload([kw], timeframe='today 3-m', geo='US')
        df = pt.interest_over_time()
        if df.empty:
            print(f"  ✗ {kw} — no data")
            return GoogleSignal(0,0,False,0,0)
        vals = df[kw].tolist()
        cur  = float(vals[-1])
        pri  = float(vals[-2]) if len(vals)>=2 else 0
        wow  = ((cur-pri)/pri*100) if pri>0 else 0
        days = 0
        for i in range(len(vals)-1,0,-1):
            if vals[i]>vals[i-1]: days+=7
            else: break
        print(f"  ✓ {kw:<28} cur:{cur:>3.0f} WoW:{wow:>+6.1f}% days↑:{days}")
        return GoogleSignal(cur, pri, cur>=90 or wow>100, days, 0)
    except Exception as e:
        print(f"  ✗ {kw} — {e}")
        return GoogleSignal(0,0,False,0,0)

def estimate(g):
    s = g.current_volume / 100.0
    wow = ((g.current_volume-g.prior_volume)/g.prior_volume*100) if g.prior_volume>0 else 0
    tk = TikTokSignal(
        total_video_count=int(s*1000), unique_creator_count=int(s*400),
        sound_reuse_48h=int(s*800), sponsored_post_count=int(s*100),
        organic_post_count=int(s*900), unboxing_count=int(s*80),
        link_in_bio_count=int(s*150), just_ordered_count=int(s*180),
        restock_count=int(s*40), must_buy_phrases=int(s*280),
        negative_phrases=int(s*30) if wow<0 else int(s*20),
        nano_creators=int(s*180), micro_creators=int(s*130),
        macro_creators=int(s*50), mega_creators=int(s*8),
        category_positive_phrases=int(s*70),
        category_negative_phrases=int(s*10) if wow<0 else int(s*5),
        prior_week_sponsored_ratio=0.08 if wow>0 else 0.25
    )
    ig = InstagramSignal(
        save_count=int(s*7000), share_count=int(s*2500),
        like_count=int(s*150000), comment_count=int(s*10000),
        sponsored_post_count=int(s*80), organic_post_count=int(s*820),
        unique_creator_count=int(s*240)
    )
    rd = RedditSignal(
        unique_subreddit_count=int(s*8), total_post_count=int(s*35),
        avg_comment_depth=s*6.5, high_karma_post_count=int(s*12),
        pros_cons_thread_count=int(s*5), must_buy_phrases=int(s*75),
        negative_phrases=int(s*15) if wow>0 else int(s*40),
        consumer_subreddit_hits=int(s*8), niche_subreddit_hits=int(s*4)
    )
    return tk, ig, rd

def run():
    print("\n" + "="*60)
    print("  TRENDBOARD.FYI — Live Pipeline v1")
    print("="*60)

    signals = []
    for p in PRODUCTS:
        print(f"\n  [{p['name']}]")
        g = fetch_google(p["kw"])
        time.sleep(6)
        tk, ig, rd = estimate(g)
        signals.append(ProductSignals(
            product_id=p["id"], product_name=p["name"],
            category=p["cat"], google=g, tiktok=tk,
            instagram=ig, reddit=rd, ts_history=[], days_in_database=0
        ))

    result = run_weekly_scoring(signals)
    ranked = result["ranked_scores"]

    print(f"\n{'='*60}")
    print(f"  LIVE BILLBOARD — April 18, 2026")
    print(f"{'='*60}")

    icons = {"NEW_ENTRY":"🆕","HIGH_FLYER":"🚀","FALLING_STAR":"⚠️",
             "COOLING":"🌡️","STAPLE":"📊","TRENDING":"📈","BELOW_THRESHOLD":"·"}

    for i, s in enumerate(ranked, 1):
        icon = icons.get(s.state, "·")
        print(f"  {icon} #{i}  {s.product_name:<28}  TS:{s.final_ts:>5.1f}  V:{s.velocity_score:>5.1f}  [{s.state}]")

    print(f"\n  Google Trends: LIVE  |  Social: estimated")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run()