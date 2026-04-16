"""
Quick test — pulls real Google Trends data for your top 6 products.
Run this to see actual search velocity numbers.
"""

from pytrends.request import TrendReq
import time

pytrends = TrendReq(hl='en-US', tz=360, timeout=(10, 25))

products = [
    "sleep mouth tape",
    "infrared sauna blanket",
    "blue light therapy",
    "flat back earrings",
    "IPL hair removal",
    "sleep earbuds",
]

print("\n" + "="*55)
print("  TRENDBOARD.FYI — Live Google Trends Data")
print("="*55)

for keyword in products:
    try:
        pytrends.build_payload(
            [keyword],
            cat=0,
            timeframe='today 3-m',
            geo='US',
            gprop=''
        )
        df = pytrends.interest_over_time()

        if df.empty:
            print(f"  {keyword:<30} — no data")
            continue

        values = df[keyword].tolist()
        current = values[-1]
        prior   = values[-2] if len(values) >= 2 else 0
        peak    = max(values)

        if prior > 0:
            wow = ((current - prior) / prior) * 100
        else:
            wow = 0

        trend = "↑" if wow > 0 else "↓" if wow < 0 else "→"

        print(f"  {keyword:<30}  current: {current:>3}  prior: {prior:>3}  "
              f"WoW: {wow:>+6.1f}%  peak: {peak:>3}  {trend}")

        time.sleep(1)  # rate limit

    except Exception as e:
        print(f"  {keyword:<30} — error: {e}")

print("="*55)
print("  Done. These are real numbers from Google Trends.")
print("="*55 + "\n")