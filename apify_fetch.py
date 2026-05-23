"""
Real TikTok and Instagram signals via Apify scrapers.
"""
import os, re, requests
from scorer import TikTokSignal, InstagramSignal
from safety import guard, is_test_mode, COST_ESTIMATES

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.getenv("APIFY_TOKEN")
BASE  = "https://api.apify.com/v2"

# ── purchase-intent / sentiment phrase lists ───────────────────────────────────
_SPONSORED    = {"#ad","#sponsored","#partner","#gifted","paid partnership","#paidpartnership"}
_PURCHASE     = {"must have","obsessed","game changer","gamechanger","life changing",
                 "need this","best purchase","holy grail","worth it","10/10","love this"}
_NEGATIVE     = {"don't buy","dont buy","scam","waste of","disappointed","broke",
                 "terrible","regret","wouldn't recommend","not worth"}
_UNBOXING     = {"unboxing","unbox","first impression","first look","testing it"}
_LINK_BIO     = {"link in bio","linkinbio","link in my bio"}
_JUST_ORDERED = {"just ordered","just bought","just purchased","ordered this","finally bought"}
_RESTOCK      = {"restock","back in stock","restocked","available again","coming back"}
_CAT_POS      = {"amazing","incredible","so good","highly recommend","obsessed","love it"}
_CAT_NEG      = {"overrated","not worth","skip this","save your money","waste"}


def _has(text: str, phrases: set) -> bool:
    t = text.lower()
    return any(p in t for p in phrases)


def _run_actor(actor_slug: str, payload: dict, timeout: int = 180) -> list:
    """POST to Apify sync endpoint; returns list of dataset items."""
    # ── SAFETY GATE ──────────────────────────────────────────────────────────
    guard("Apify actor: " + actor_slug, COST_ESTIMATES["apify_tiktok_hashtag"])
    # ─────────────────────────────────────────────────────────────────────────
    actor_id = actor_slug.replace("/", "~")
    url = f"{BASE}/acts/{actor_id}/run-sync-get-dataset-items"
    r = requests.post(url, json=payload, params={"token": TOKEN}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_tiktok(keyword: str) -> TikTokSignal:
    hashtag = re.sub(r"\s+", "", keyword)
    print(f"  → TikTok  #{hashtag} …", end=" ", flush=True)
    try:
        items = _run_actor(
            "clockworks/tiktok-scraper",
            {"hashtags": [hashtag], "resultsPerPage": 50},
        )
    except Exception as e:
        print(f"FAIL ({e})")
        return _zero_tiktok()

    if not items:
        print("no results")
        return _zero_tiktok()

    total     = len(items)
    creators  = set()
    sponsored = organic = unboxing = link_bio = 0
    just_ord  = restock = must_buy = neg = 0
    cat_pos   = cat_neg = 0
    nano = micro = macro = mega = 0

    for v in items:
        caption   = v.get("text") or ""
        tags      = " ".join(v.get("hashtags") or [])
        text      = f"{caption} {tags}"
        author    = v.get("authorMeta") or {}
        creator   = author.get("id") or author.get("name", "")
        followers = int(author.get("fans", 0) or 0)

        creators.add(creator)

        if _has(text, _SPONSORED): sponsored += 1
        else:                       organic   += 1

        if _has(text, _UNBOXING):     unboxing  += 1
        if _has(text, _LINK_BIO):     link_bio  += 1
        if _has(text, _JUST_ORDERED): just_ord  += 1
        if _has(text, _RESTOCK):      restock   += 1
        if _has(text, _PURCHASE):     must_buy  += 1
        if _has(text, _NEGATIVE):     neg       += 1
        if _has(text, _CAT_POS):      cat_pos   += 1
        if _has(text, _CAT_NEG):      cat_neg   += 1

        if   followers < 10_000:    nano  += 1
        elif followers < 100_000:   micro += 1
        elif followers < 1_000_000: macro += 1
        else:                       mega  += 1

    print(f"videos:{total}  creators:{len(creators)}  sponsored:{sponsored}")
    return TikTokSignal(
        total_video_count         = total,
        unique_creator_count      = len(creators),
        sound_reuse_48h           = 0,          # not exposed by this actor
        sponsored_post_count      = sponsored,
        organic_post_count        = organic,
        unboxing_count            = unboxing,
        link_in_bio_count         = link_bio,
        just_ordered_count        = just_ord,
        restock_count             = restock,
        must_buy_phrases          = must_buy,
        negative_phrases          = neg,
        nano_creators             = nano,
        micro_creators            = micro,
        macro_creators            = macro,
        mega_creators             = mega,
        category_positive_phrases = cat_pos,
        category_negative_phrases = cat_neg,
        prior_week_sponsored_ratio= round(sponsored / max(total, 1), 3),
    )


def fetch_instagram(keyword: str) -> InstagramSignal:
    hashtag = re.sub(r"\s+", "", keyword)
    print(f"  → Instagram #{hashtag} …", end=" ", flush=True)
    try:
        items = _run_actor(
            "apify/instagram-hashtag-scraper",
            {"hashtags": [hashtag], "resultsLimit": 50},
        )
    except Exception as e:
        print(f"FAIL ({e})")
        return _zero_instagram()

    if not items:
        print("no results")
        return _zero_instagram()

    total     = len(items)
    likes     = comments = sponsored = organic = 0
    creators  = set()

    for p in items:
        likes    += int(p.get("likesCount", 0) or 0)
        comments += int(p.get("commentsCount", 0) or 0)
        owner     = p.get("ownerUsername") or p.get("ownerId", "")
        creators.add(owner)
        caption   = p.get("caption") or ""
        tags      = " ".join(p.get("hashtags") or [])
        text      = f"{caption} {tags}"
        if _has(text, _SPONSORED): sponsored += 1
        else:                       organic   += 1

    print(f"posts:{total}  likes:{likes}  comments:{comments}")
    return InstagramSignal(
        save_count          = 0,   # not publicly accessible
        share_count         = 0,   # not publicly accessible
        like_count          = likes,
        comment_count       = comments,
        sponsored_post_count= sponsored,
        organic_post_count  = organic,
        unique_creator_count= len(creators),
    )


def _zero_tiktok() -> TikTokSignal:
    return TikTokSignal(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def _zero_instagram() -> InstagramSignal:
    return InstagramSignal(0, 0, 0, 0, 0, 0, 0)
