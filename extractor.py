"""
trendboard.fyi — Skincare Product Extractor
============================================
Takes raw TikTok/Instagram video captions and extracts
product candidates using Claude AI — no fixed keyword dictionary.

Claude reads each caption as a human would, identifying specific
named skincare/beauty products regardless of whether the brand
was pre-programmed. This is the core intelligence of Trendboard.

Recency weighting (not hard cutoff):
  All scraped videos are used. Posts from the last 7 days contribute
  full weight to trend scores; older posts contribute less but are
  NOT discarded — they provide baseline signal for velocity calculation.

  Age weights:
    0-7 days:   1.0  (peak signal)
    8-14 days:  0.7
    15-21 days: 0.5
    22-30 days: 0.3
    30+ days:   0.1  (baseline only)

A product qualifies for scoring when it has:
  - At least 2 weighted-unique creators
  - Mentioned by Claude across multiple captions
  - Positive sentiment outweighs negative

Usage:
    extractor = ProductExtractor()
    candidates = extractor.process_videos(videos, min_creators=2)
"""

import os
import re
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
import taxonomy

logger = logging.getLogger(__name__)

# ── SMART TITLE CASE ─────────────────────────────────────────────────────────

_ACRONYMS = {
    "bha", "aha", "pha", "lha", "spf", "uva", "uvb", "uv",
    "led", "ha", "dna", "asc",
}

def _smart_title(text: str) -> str:
    def _cap(word: str) -> str:
        if not word: return word
        if word.lower() in _ACRONYMS: return word.upper()
        if not word[0].isalpha(): return word
        parts = word.split("-")
        return "-".join(p[0].upper() + p[1:] if p else p for p in parts)
    return " ".join(_cap(w) for w in text.split())


# ── DATA STRUCTURES ──────────────────────────────────────────────────────────

@dataclass
class VideoSignal:
    """One TikTok or Instagram video/post."""
    video_id: str
    creator_id: str
    creator_handle: str
    caption: str
    hashtags: list
    like_count: int
    comment_count: int
    share_count: int
    follower_count: int
    posted_date: str
    platform: str        # "tiktok" or "instagram"
    is_sponsored: bool


@dataclass
class ProductCandidate:
    """A product identified across multiple creator captions."""
    product_key: str
    display_name: str
    brand: str
    product_type: str
    category: str

    # Signal counts (raw)
    unique_creator_count: int  = 0
    total_video_count: int     = 0
    sponsored_count: int       = 0
    organic_count: int         = 0
    strong_signal_count: int   = 0
    negative_signal_count: int = 0

    # Recency-weighted creator score (used for velocity ranking)
    # Higher = more recent creator activity
    weighted_creator_score: float = 0.0

    # Creator tier breakdown
    nano_creators: int   = 0   # <10k followers
    micro_creators: int  = 0   # 10k-100k
    macro_creators: int  = 0   # 100k-1M
    mega_creators: int   = 0   # 1M+

    # Engagement
    total_likes: int     = 0
    total_comments: int  = 0
    total_shares: int    = 0

    # Creator IDs seen (for deduplication)
    creator_ids: set = field(default_factory=set)

    # Top creator posts — stored for attribution engine
    top_creator_posts: list = field(default_factory=list)

    # Confidence
    confidence: float    = 0.0

    # Google Trends keyword
    google_keyword: str  = ""

    # Taxonomy
    product_type_id: str    = ""
    product_type_label: str = ""
    product_type_emoji: str = ""


# ── SIGNAL PHRASES ───────────────────────────────────────────────────────────

STRONG_SIGNAL_PHRASES = [
    "changed my skin", "holy grail", "game changer", "life changing",
    "obsessed with", "can't live without", "must have", "must try",
    "so good", "works so well", "actually works", "finally found",
    "derm recommended", "dermatologist recommended", "derm approved",
    "clinically proven", "before and after", "results in",
    "cleared my", "faded my", "brightened my", "smoothed my",
    "link in bio", "amazon find", "amazon must have", "sephora find",
    "ulta find", "best purchase", "worth every penny",
    "just ordered", "just bought", "ordered more", "repurchase",
    "restock", "sold out", "back in stock", "finally restocked",
    "unboxing", "first impression", "honest review",
]

NEGATIVE_PHRASES = [
    "broke me out", "caused breakouts", "purging", "returned it",
    "don't buy", "waste of money", "doesn't work", "overrated",
    "scam", "burned my skin", "irritated", "allergic reaction",
    "counterfeit", "fake", "dupe is better",
]

EXCLUSIONS = {
    "skincare", "beauty", "makeup", "routine", "tips", "hacks",
    "tutorial", "transformation", "glow up", "selfcare", "self care",
    "skin", "face", "body", "hair", "nails", "wellness",
    "product", "products", "item", "thing", "stuff",
}


# ── RECENCY WEIGHTING ─────────────────────────────────────────────────────────

def _recency_weight(posted_date_str: str, today_str: str) -> float:
    """
    Returns a 0.1-1.0 weight based on how recently the post was made.
    Uses the full date range — nothing is discarded.
    """
    try:
        posted = datetime.strptime(posted_date_str[:10], "%Y-%m-%d").date()
        today  = datetime.strptime(today_str, "%Y-%m-%d").date()
        days_old = (today - posted).days
    except Exception:
        return 0.5   # unknown date → neutral weight

    if days_old <= 7:  return 1.0
    if days_old <= 14: return 0.7
    if days_old <= 21: return 0.5
    if days_old <= 30: return 0.3
    return 0.1


# ── CLAUDE-POWERED EXTRACTION ─────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a skincare trend analyst reading TikTok and Instagram captions.
Your job: identify every specific named skincare or beauty PRODUCT mentioned in each caption.

Rules:
- Extract SPECIFIC products only — you must have BOTH a real brand name AND a real product name/identifier
  Good: "Medicube Booster Shot Serum", "Rhode Peptide Lip Treatment", "Anua Heartleaf 77% Toner"
  Bad:  "Anua Product", "Rhode Bronzer", "Medicube Cream", "Rare Beauty Blush" (too vague)
- The product_name MUST be the actual product line/variant name, not a category word
  Good product_name: "Heartleaf 77% Soothing Toner", "Advanced Snail 96 Mucin Power Essence", "Low pH Good Morning Gel Cleanser"
  Bad product_name:  "Toner", "Serum", "Product", "Cream", "Beauty", "Cosmetics", "Makeup", "Skincare"
- If a caption only mentions a brand name without a specific product, SKIP IT — do not output anything for that caption
- Do NOT repeat the brand name as the product_name (e.g. "Medicube Medicube" is wrong)
- Do NOT use generic words as product_name: Product, Item, Stuff, Beauty, Cosmetics, Skincare, Makeup, Formula
- Do NOT extract vague product types alone: "serum", "moisturizer", "skincare routine"
- Do NOT extract ingredients alone: "retinol", "niacinamide" — ONLY if paired with brand AND specific name
- One caption can mention multiple products — list all of them
- If no specific named product is identifiable, omit that caption entirely

Return ONLY a JSON array (no explanation, no markdown):
[
  {"index": 1, "brand": "Medicube", "product_name": "Booster Shot Serum", "category": "serum"},
  {"index": 4, "brand": "Rhode", "product_name": "Peptide Lip Treatment", "category": "lip_care"},
  {"index": 4, "brand": "CeraVe", "product_name": "Foaming Facial Cleanser", "category": "cleanser"},
  {"index": 7, "brand": "Anua", "product_name": "Heartleaf 77% Soothing Toner", "category": "toner"}
]

Valid categories: serum, moisturizer, cleanser, toner, essence, sunscreen, exfoliant,
retinoid, eye_cream, face_oil, mask, lip_care, led_device, microcurrent_device,
body_care, foundation, concealer, blush, bronzer, mascara, lip_color, fragrance, other"""


def _repair_json_array(raw: str) -> list[dict]:
    """
    Extracts all complete {...} objects from a potentially truncated JSON array.
    Handles cases where the response is cut off mid-object (token limit hit).
    """
    results = []
    depth = 0
    start = -1
    for i, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(raw[start:i + 1])
                    if isinstance(obj, dict):
                        results.append(obj)
                except Exception:
                    pass
                start = -1
    return results


def _extract_batch_with_claude(captions: list[str], indices: list[int]) -> list[dict]:
    """
    Sends a batch of captions to Claude Haiku and returns structured product extractions.
    Captions are numbered 1..N locally within the batch (not by global video index).
    Returns list of dicts with 'caption_index' set to the global video index.
    """
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    except ImportError:
        logger.warning("anthropic not installed — falling back to regex extraction")
        return []

    # Use LOCAL 1-based numbering so Claude's returned index maps directly
    # to position within this batch (works identically for all batches).
    numbered = "\n".join(
        f"{local_i + 1}. {cap[:350]}"
        for local_i, cap in enumerate(captions)
    )

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Captions:\n{numbered}"}]
        )
        raw = msg.content[0].text.strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # Try clean parse first; fall back to object-by-object repair
        try:
            objects = json.loads(raw)
        except json.JSONDecodeError:
            objects = _repair_json_array(raw)

        # Map local 1-based index → global caption index
        results = []
        for r in objects:
            local_idx = int(r.get("index", 0)) - 1   # 0-based position in batch
            if 0 <= local_idx < len(indices):
                r["caption_index"] = indices[local_idx]
                results.append(r)
        return results

    except Exception as e:
        logger.warning(f"Claude batch extraction failed: {e}")
        return []


# ── REGEX FALLBACK ────────────────────────────────────────────────────────────
# Used when Claude API is unavailable. Keeps the pipeline runnable but with
# lower recall — it only finds brands it was told about.

_FALLBACK_BRANDS = {
    "medicube", "anua", "cosrx", "innisfree", "laneige", "tirtir",
    "beauty of joseon", "round lab", "torriden", "skin1004", "numbuzin",
    "cetaphil", "cerave", "la roche-posay", "neutrogena", "vanicream",
    "the ordinary", "drunk elephant", "paula's choice", "naturium",
    "rhode", "rare beauty", "glow recipe", "kosas", "byoma",
    "foreo", "nuface", "currentbody", "omnilux", "solawave",
}

_FALLBACK_TYPES = [
    "serum", "moisturizer", "cleanser", "toner", "essence",
    "sunscreen", "spf", "retinol", "exfoliant", "eye cream",
    "led mask", "face wash", "face cream", "lip treatment",
]

def _extract_regex_fallback(caption: str) -> list[dict]:
    """Simple regex fallback — lower recall, but zero API cost."""
    caption_lower = caption.lower()
    results = []

    for brand in sorted(_FALLBACK_BRANDS, key=len, reverse=True):
        if brand in caption_lower:
            for ptype in _FALLBACK_TYPES:
                if ptype in caption_lower:
                    results.append({
                        "brand":        _smart_title(brand),
                        "product_name": _smart_title(ptype),
                        "category":     ptype.replace(" ", "_"),
                    })
                    break
            else:
                results.append({
                    "brand":        _smart_title(brand),
                    "product_name": _smart_title(brand),
                    "category":     "other",
                })
            break   # one brand per caption in fallback mode

    return results


# ── MAIN EXTRACTOR ────────────────────────────────────────────────────────────

class ProductExtractor:
    """
    Extracts product candidates from video captions using Claude AI.

    Uses ALL scraped videos regardless of age. Older posts contribute
    lower weight to trend scores but are never discarded — they form the
    baseline that makes velocity calculation meaningful.
    """

    BATCH_SIZE = 50   # captions per Claude call — smaller = less truncation risk

    def __init__(self):
        self.today_str = date.today().isoformat()

    def _get_creator_tier(self, followers: int) -> str:
        if followers >= 1_000_000: return "mega"
        if followers >= 100_000:   return "macro"
        if followers >= 10_000:    return "micro"
        return "nano"

    def _normalize_key(self, brand: str, product: str) -> str:
        combined = f"{brand} {product}".lower()
        return re.sub(r"[^a-z0-9]", "_", combined).strip("_")

    def _count_signals(self, caption: str) -> tuple[int, int]:
        cl = caption.lower()
        strong   = sum(1 for p in STRONG_SIGNAL_PHRASES if p in cl)
        negative = sum(1 for p in NEGATIVE_PHRASES       if p in cl)
        return strong, negative

    def _is_sponsored(self, caption: str) -> bool:
        tags = ["#ad", "#sponsored", "#gifted", "#partner", "#collab", "#paid"]
        cl = caption.lower()
        return any(t in cl for t in tags)

    def extract_all(self, videos: list[VideoSignal]) -> dict[str, list[dict]]:
        """
        Runs Claude extraction across all captions in batches.
        Returns dict mapping video index → list of extracted products.
        """
        captions = [v.caption for v in videos]
        total    = len(captions)
        all_extractions: dict[int, list[dict]] = defaultdict(list)

        use_claude = bool(os.getenv("ANTHROPIC_API_KEY"))
        if not use_claude:
            logger.warning("  No ANTHROPIC_API_KEY — using regex fallback (lower recall)")

        logger.info(f"  Extracting products from {total} captions "
                    f"({'Claude AI' if use_claude else 'regex fallback'})...")

        for batch_start in range(0, total, self.BATCH_SIZE):
            batch_end     = min(batch_start + self.BATCH_SIZE, total)
            batch_caps    = captions[batch_start:batch_end]
            batch_indices = list(range(batch_start, batch_end))

            if use_claude:
                try:
                    results = _extract_batch_with_claude(batch_caps, batch_indices)
                    for r in results:
                        idx = r.get("caption_index", -1)
                        if 0 <= idx < total:
                            all_extractions[idx].append(r)
                    if batch_start % (self.BATCH_SIZE * 5) == 0:
                        pct = int(batch_end / total * 100)
                        logger.info(f"    ...{pct}% ({batch_end}/{total} captions)")
                except Exception as e:
                    logger.warning(f"  Batch {batch_start}-{batch_end} failed: {e} — using fallback")
                    for i, cap in enumerate(batch_caps):
                        for r in _extract_regex_fallback(cap):
                            all_extractions[batch_start + i].append(r)
            else:
                for i, cap in enumerate(batch_caps):
                    for r in _extract_regex_fallback(cap):
                        all_extractions[batch_start + i].append(r)

        found = sum(1 for v in all_extractions.values() if v)
        logger.info(f"  Products found in {found}/{total} captions")
        return dict(all_extractions)

    def process_videos(self, videos: list[VideoSignal],
                       min_creators: int = 2) -> list[ProductCandidate]:
        """
        Main processing function. Uses ALL videos — no date cutoff.

        Recency weighting:
          - Last 7 days:  full weight (1.0)
          - 8-14 days:    0.7
          - 15-21 days:   0.5
          - 22-30 days:   0.3
          - 30+ days:     0.1

        min_creators: minimum weighted unique creators to qualify.
        A product with 3 creators from this week scores the same as
        one with ~4-5 creators from 2 weeks ago.
        """
        logger.info(f"\n  Processing {len(videos)} videos (ALL dates, recency-weighted)...")

        # Step 1: Extract products from all captions
        extractions = self.extract_all(videos)

        # Step 2: Aggregate into ProductCandidate objects
        candidates: dict[str, ProductCandidate] = {}

        for video_idx, video in enumerate(videos):
            products_in_caption = extractions.get(video_idx, [])
            if not products_in_caption:
                continue

            strong, negative = self._count_signals(video.caption)
            is_sponsored     = self._is_sponsored(video.caption)
            weight           = _recency_weight(video.posted_date, self.today_str)
            tier             = self._get_creator_tier(video.follower_count)

            for prod in products_in_caption:
                brand        = str(prod.get("brand", "")).strip()
                product_name = str(prod.get("product_name", "")).strip()
                category     = str(prod.get("category", "other")).strip()

                if not brand or not product_name:
                    continue

                # Normalize to a consistent key
                key = self._normalize_key(brand, product_name)

                if key not in candidates:
                    display = _smart_title(f"{brand} {product_name}".strip())

                    # Classify into our taxonomy
                    try:
                        type_id    = taxonomy.classify(brand.lower(), category, video.caption)
                        type_label = taxonomy.get_label(type_id)
                        type_emoji = taxonomy.get_emoji(type_id)
                    except Exception:
                        type_id, type_label, type_emoji = category, _smart_title(category), "✨"

                    google_kw = f"{brand} {product_name}".strip()

                    candidates[key] = ProductCandidate(
                        product_key        = key,
                        display_name       = display,
                        brand              = brand.lower(),
                        product_type       = category,
                        category           = "Skincare",
                        google_keyword     = google_kw,
                        product_type_id    = type_id,
                        product_type_label = type_label,
                        product_type_emoji = type_emoji,
                    )

                c = candidates[key]
                c.total_video_count    += 1
                c.total_likes          += video.like_count
                c.total_comments       += video.comment_count
                c.total_shares         += video.share_count
                c.strong_signal_count  += strong
                c.negative_signal_count += negative

                if is_sponsored:
                    c.sponsored_count += 1
                else:
                    c.organic_count += 1

                # Unique creator tracking (raw count + recency-weighted score)
                if video.creator_id not in c.creator_ids:
                    c.creator_ids.add(video.creator_id)
                    c.unique_creator_count    += 1
                    c.weighted_creator_score  += weight   # recent = higher score

                    if tier == "mega":    c.mega_creators  += 1
                    elif tier == "macro": c.macro_creators += 1
                    elif tier == "micro": c.micro_creators += 1
                    else:                 c.nano_creators  += 1

                    if video.creator_handle:
                        c.top_creator_posts.append({
                            "handle":       video.creator_handle,
                            "followers":    video.follower_count,
                            "date":         video.posted_date,
                            "likes":        video.like_count,
                            "comments":     video.comment_count,
                            "caption":      video.caption[:200],
                            "is_sponsored": video.is_sponsored,
                            "tier":         tier,
                            "weight":       weight,
                        })
                        if len(c.top_creator_posts) > 10:
                            c.top_creator_posts.sort(
                                key=lambda p: (p["weight"], p["followers"]),
                                reverse=True
                            )
                            c.top_creator_posts = c.top_creator_posts[:10]

                c.confidence = max(c.confidence, 0.5 + (weight * 0.5))

        # Step 3: Velocity filter using weighted score
        qualified = [
            c for c in candidates.values()
            if c.weighted_creator_score >= min_creators
            and c.product_key not in EXCLUSIONS
        ]

        # Sort by weighted score (recency-boosted) then raw creator count
        qualified.sort(
            key=lambda x: (x.weighted_creator_score, x.unique_creator_count),
            reverse=True
        )

        logger.info(f"  Qualified candidates: {len(qualified)} "
                    f"(weighted score ≥ {min_creators})")
        return qualified
