"""
trendboard.fyi — Skincare Product Extractor
============================================
Takes raw TikTok/Instagram video captions and extracts
product candidates using pattern matching and brand recognition.

This is the intelligence layer between raw scrape data
and the scoring engine. It answers one question:
"What specific product is this creator talking about?"

Two extraction methods:
1. Brand + Product pattern matching (high confidence)
2. Ingredient-as-product detection (medium confidence)

A product passes extraction when it has:
- A recognizable brand name OR a clear product type
- Mentioned by 5+ unique creators in 7 days
- Not on the exclusion list (too generic, not buyable)
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
import taxonomy


# ─── BRAND REGISTRY ──────────────────────────────────────────────────────────
# Organized by tier. Tier 1 = highest signal (derm-recommended or viral).
# When a Tier 1 brand appears in a caption, it's almost always a product mention.

BRANDS_TIER1 = {
    # K-Beauty — currently dominant category on TikTok Shop
    "medicube", "anua", "cosrx", "innisfree", "laneige", "sulwhasoo",
    "dr melaxin", "dr melaxin", "some by mi", "isntree", "tirtir",
    "beauty of joseon", "round lab", "klairs", "axis-y", "purito",
    "torriden", "rovectin", "skin1004", "tocobo", "numbuzin",
    "d'Alba", "aestura", "dr jart", "etude house", "missha",
    "holika holika", "tony moly", "skinfood", "iunik",

    # Derm-recommended US brands
    "cetaphil", "cerave", "la roche-posay", "vanicream", "aveeno",
    "neutrogena", "differin", "paula's choice", "the ordinary",
    "drunk elephant", "tatcha", "skinceuticals", "obagi",
    "peter thomas roth", "murad", "dermalogica", "epionce",
    "isdin", "elta md", "supergoop", "colorescience",

    # Trending indie/viral brands
    "naturium", "good molecules", "inkey list", "versed",
    "hero cosmetics", "starface", "mighty patch", "snif",
    "rhode", "rare beauty", "tower 28", "ilia", "jones road",
    "summer fridays", "glow recipe", "kosas", "merit",
    "byoma", "topicals", "flora and fauna", "loops beauty",
    "selfless by hyram", "twentysomething", "facetory",

    # Devices
    "foreo", "nuface", "currentbody", "lightstim", "omnilux",
    "solawave", "ziip", "theraface", "hangsun", "project e beauty",
    "trophy skin", "silk'n", "ulike", "braun", "philips lumea",
    "tria", "nood", "jovs",
}

BRANDS_TIER2 = {
    # Broader beauty brands — still strong signal
    "charlotte tilbury", "nars", "fenty", "fenty beauty", "mac",
    "urban decay", "too faced", "benefit", "clinique", "estee lauder",
    "lancome", "givenchy beauty", "dior beauty", "ysl beauty",
    "georgio armani beauty", "hourglass", "pat mcgrath", "bobbi brown",
    "fresh", "origins", "kiehls", "origins", "ole henriksen",
    "first aid beauty", "youth to the people", "true botanicals",
    "alpyn beauty", "herbivore", "tata harper", "sunday riley",
    "biossance", "acure", "yes to", "burt's bees",
}

ALL_BRANDS = BRANDS_TIER1 | BRANDS_TIER2

# ─── PRODUCT TYPE PATTERNS ───────────────────────────────────────────────────
# When a brand is paired with one of these, we have a specific product.
# Also used standalone when the brand is a generic ingredient name.

PRODUCT_TYPES = [
    "serum", "moisturizer", "cleanser", "toner", "essence", "ampoule",
    "eye cream", "eye serum", "face oil", "face mist", "face mask",
    "sheet mask", "sleeping mask", "overnight mask", "lip mask", "lip balm",
    "spf", "sunscreen", "sun cream", "uv cream", "mineral sunscreen",
    "exfoliant", "exfoliator", "aha", "bha", "pha", "chemical exfoliant",
    "retinol", "retinoid", "tretinoin", "adapalene",
    "vitamin c", "vit c", "ascorbic acid", "niacinamide",
    "hyaluronic acid", "glycerin", "ceramide", "peptide",
    "snail mucin", "propolis", "centella", "cica",
    "led mask", "led device", "light therapy device", "red light",
    "microcurrent device", "gua sha", "jade roller", "facial roller",
    "pore vacuum", "blackhead remover", "comedone extractor",
    "face steamer", "dermaplaning", "microneedling",
    "micellar water", "cleansing oil", "cleansing balm",
    "primer", "foundation", "concealer", "setting spray", "setting powder",
    "blush", "bronzer", "highlighter", "contour", "eyeshadow",
    "mascara", "liner", "lip liner", "lipstick", "lip gloss",
    "brow gel", "brow pencil", "lash serum",
    "body lotion", "body butter", "body oil", "body scrub",
    "neck cream", "chest serum", "decolletage",
    "hair growth serum", "scalp serum", "hair oil",
    "perfume", "fragrance", "eau de parfum", "edp", "cologne",
]

# ─── STRONG SIGNAL PHRASES ───────────────────────────────────────────────────
# When these appear in a caption near a product name, confidence is high.

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

# ─── EXCLUSION LIST ──────────────────────────────────────────────────────────
# Too generic to extract a specific product from.

EXCLUSIONS = {
    "skincare", "beauty", "makeup", "routine", "tips", "hacks",
    "tutorial", "transformation", "glow up", "selfcare", "self care",
    "skin", "face", "body", "hair", "nails", "wellness",
    "product", "products", "item", "thing", "stuff",
}


# ─── DATA STRUCTURES ─────────────────────────────────────────────────────────

@dataclass
class VideoSignal:
    """One TikTok or Instagram video."""
    video_id: str
    creator_id: str
    creator_handle: str
    caption: str
    hashtags: list
    like_count: int
    comment_count: int
    share_count: int
    follower_count: int   # Creator's follower count
    posted_date: str
    platform: str         # "tiktok" or "instagram"
    is_sponsored: bool    # Has #ad, #sponsored, #gifted


@dataclass
class ProductCandidate:
    """
    A product extracted from scrape data.
    Becomes a scored product if it passes the velocity filter.
    """
    product_key: str          # Normalized name used as unique ID
    display_name: str         # Human-readable name
    brand: str                # Brand name if detected
    product_type: str         # Serum, cleanser, etc.
    category: str             # "Skincare", "Makeup", etc.

    # Signal counts
    unique_creator_count: int = 0
    total_video_count: int    = 0
    sponsored_count: int      = 0
    organic_count: int        = 0
    strong_signal_count: int  = 0
    negative_signal_count: int = 0

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
    # Each entry: {"handle": str, "followers": int, "date": str,
    #              "likes": int, "caption": str, "is_sponsored": bool}
    top_creator_posts: list = field(default_factory=list)

    # Raw confidence score
    confidence: float    = 0.0

    # Search keyword for Google Trends
    google_keyword: str  = ""

    # Taxonomy classification
    product_type_id: str    = ""   # e.g. "toner", "serum", "led_device"
    product_type_label: str = ""   # e.g. "Toner", "Serum / Essence"
    product_type_emoji: str = ""   # e.g. "🌊"


# ─── EXTRACTION ENGINE ────────────────────────────────────────────────────────

class ProductExtractor:
    """
    Extracts product candidates from raw video captions.
    """

    def __init__(self):
        # Compile brand patterns for fast matching
        self.brand_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(b) for b in sorted(ALL_BRANDS, key=len, reverse=True)) + r')\b',
            re.IGNORECASE
        )
        self.product_type_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(p) for p in sorted(PRODUCT_TYPES, key=len, reverse=True)) + r')\b',
            re.IGNORECASE
        )

    def extract_from_caption(self, caption: str) -> list[tuple[str, str, str, float]]:
        """
        Extracts (brand, product_type, display_name, confidence) tuples from a caption.
        Returns empty list if no product found.
        """
        caption_lower = caption.lower()
        results = []

        # Find brands mentioned
        brands_found = self.brand_pattern.findall(caption)
        brands_found = [b.lower() for b in brands_found]

        # Find product types mentioned
        types_found = self.product_type_pattern.findall(caption)
        types_found = [t.lower() for t in types_found]

        # Count strong/negative signals
        strong_signals = sum(1 for p in STRONG_SIGNAL_PHRASES if p in caption_lower)
        negative_signals = sum(1 for p in NEGATIVE_PHRASES if p in caption_lower)

        # Base confidence from signal quality
        base_confidence = 0.3
        if strong_signals > 0: base_confidence += 0.2 * min(strong_signals, 3)
        if negative_signals > 0: base_confidence -= 0.3

        # Case 1: Brand + Product type (highest confidence)
        if brands_found and types_found:
            brand = brands_found[0]
            ptype = types_found[0]
            display = f"{brand.title()} {ptype.title()}"
            key = self._normalize_key(display)
            confidence = min(base_confidence + 0.4, 1.0)
            results.append((brand, ptype, display, key, confidence))

        # Case 2: Brand only (medium confidence — brand is specific enough)
        elif brands_found and not types_found:
            brand = brands_found[0]
            # Only keep Tier 1 brands for brand-only extractions
            if brand in BRANDS_TIER1:
                display = brand.title()
                key = self._normalize_key(display)
                confidence = min(base_confidence + 0.2, 0.7)
                results.append((brand, "product", display, key, confidence))

        # Case 3: Ingredient-as-product (standalone ingredients that are also products)
        # e.g., "snail mucin", "retinol" without a brand
        elif not brands_found and types_found:
            ptype = types_found[0]
            # Only high-specificity product types qualify without a brand
            high_specificity = [
                "snail mucin", "led mask", "microcurrent device", "gua sha",
                "jade roller", "retinol", "tretinoin", "adapalene",
                "lash serum", "scalp serum",
            ]
            if ptype in high_specificity:
                display = ptype.title()
                key = self._normalize_key(display)
                confidence = min(base_confidence + 0.1, 0.5)
                results.append(("generic", ptype, display, key, confidence))

        return results

    def _normalize_key(self, text: str) -> str:
        """Creates a consistent key for deduplication."""
        return re.sub(r'[^a-z0-9]', '_', text.lower()).strip('_')

    def _get_creator_tier(self, follower_count: int) -> str:
        if follower_count >= 1_000_000: return "mega"
        if follower_count >= 100_000:   return "macro"
        if follower_count >= 10_000:    return "micro"
        return "nano"

    def _is_sponsored(self, caption: str) -> bool:
        sponsored_tags = ["#ad", "#sponsored", "#gifted", "#partner", "#collab", "#paid"]
        caption_lower = caption.lower()
        return any(tag in caption_lower for tag in sponsored_tags)

    def _get_category(self, brand: str, product_type: str) -> str:
        makeup_types = [
            "foundation", "concealer", "blush", "bronzer", "highlighter",
            "eyeshadow", "mascara", "liner", "lipstick", "lip gloss",
            "primer", "setting spray", "setting powder", "contour"
        ]
        device_types = [
            "led mask", "led device", "microcurrent device", "gua sha",
            "jade roller", "facial roller", "pore vacuum"
        ]
        fragrance_types = ["perfume", "fragrance", "eau de parfum", "edp", "cologne"]

        if product_type in makeup_types:          return "Makeup"
        if product_type in device_types:          return "Skincare Device"
        if product_type in fragrance_types:       return "Fragrance"
        if "hair" in product_type:                return "Haircare"
        if "body" in product_type:                return "Body Care"
        return "Skincare"

    def process_videos(self, videos: list[VideoSignal],
                       min_creators: int = 5) -> list[ProductCandidate]:
        """
        Main processing function.
        Takes a list of VideoSignal objects and returns
        ProductCandidate objects that pass the velocity filter.

        min_creators: minimum unique creators to qualify as a trend candidate
        """
        # Accumulate signals per product key
        candidates: dict[str, ProductCandidate] = {}

        for video in videos:
            extractions = self.extract_from_caption(video.caption)
            is_sponsored = self._is_sponsored(video.caption)

            # Count strong/negative signals
            caption_lower = video.caption.lower()
            strong = sum(1 for p in STRONG_SIGNAL_PHRASES if p in caption_lower)
            negative = sum(1 for p in NEGATIVE_PHRASES if p in caption_lower)

            for brand, ptype, display, key, confidence in extractions:
                if key not in candidates:
                    # Classify into taxonomy
                    type_id    = taxonomy.classify(brand, ptype, video.caption)
                    type_label = taxonomy.get_label(type_id)
                    type_emoji = taxonomy.get_emoji(type_id)

                    candidates[key] = ProductCandidate(
                        product_key      = key,
                        display_name     = display,
                        brand            = brand,
                        product_type     = ptype,
                        category         = self._get_category(brand, ptype),
                        google_keyword   = f"{brand} {ptype}".strip() if brand != "generic" else ptype,
                        product_type_id  = type_id,
                        product_type_label = type_label,
                        product_type_emoji = type_emoji,
                    )

                c = candidates[key]
                c.total_video_count += 1
                c.total_likes    += video.like_count
                c.total_comments += video.comment_count
                c.total_shares   += video.share_count
                c.strong_signal_count   += strong
                c.negative_signal_count += negative

                if is_sponsored:
                    c.sponsored_count += 1
                else:
                    c.organic_count += 1

                # Only count unique creators
                if video.creator_id not in c.creator_ids:
                    c.creator_ids.add(video.creator_id)
                    c.unique_creator_count += 1

                    # Creator tier
                    tier = self._get_creator_tier(video.follower_count)
                    if tier == "mega":    c.mega_creators  += 1
                    elif tier == "macro": c.macro_creators += 1
                    elif tier == "micro": c.micro_creators += 1
                    else:                 c.nano_creators  += 1

                    # Store post for attribution (keep top 10 by follower count)
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
                        })
                        # Keep only top 10 by follower count to save memory
                        if len(c.top_creator_posts) > 10:
                            c.top_creator_posts.sort(
                                key=lambda p: p["followers"], reverse=True
                            )
                            c.top_creator_posts = c.top_creator_posts[:10]

                # Update confidence
                c.confidence = max(c.confidence, confidence)

        # Apply velocity filter: minimum unique creators
        qualified = [
            c for c in candidates.values()
            if c.unique_creator_count >= min_creators
            and c.product_key not in EXCLUSIONS
            and c.negative_signal_count < c.strong_signal_count  # More positive than negative
        ]

        # Sort by creator count descending
        qualified.sort(key=lambda x: x.unique_creator_count, reverse=True)

        return qualified
