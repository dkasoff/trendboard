from pytrends.request import TrendReq
import time

pytrends = TrendReq(hl='en-US', tz=360, timeout=(10,25))

products = [
    "sleep mouth tape",
    "infrared sauna blanket", 
    "blue light therapy",
    "flat back earrings",
    "IPL hair removal",
    "sleep earbuds",
]

print("\n" + "="*60)
print("  TRENDBOARD — Live Google Trends")
print("="*60)

for kw in products:
    try:
        time.sleep(5)
        pytrends.build_payload([kw], timeframe='today 3-m', geo='US')
        df = pytrends.interest_over_time()
        if not df.empty:
            vals = df[kw].tolist()
            cur = vals[-1]
            pri = vals[-2] if len(vals) >= 2 else 0
            wow = ((cur-pri)/pri*100) if pri > 0 else 0
            peak = max(vals)
            trend = "↑" if wow > 0 else "↓"
            print(f"  {kw:<28}  {cur:>3}  {wow:>+6.1f}%  peak:{peak:>3}  {trend}")
        else:
            print(f"  {kw:<28}  no data")
    except Exception as e:
        print(f"  {kw:<28}  error: {e}")
        time.sleep(15)

print("="*60)