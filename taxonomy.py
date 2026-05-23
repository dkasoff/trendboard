"""
trendboard.fyi — Product Type Taxonomy
========================================
Two-layer classification system for skincare & beauty products.

Layer 1: Static keyword matching (free, instant, ~90% accurate)
Layer 2: Claude fallback for unknowns (~$0.001 per product, ~10% of products)

Each product type maps to a display label and an emoji used in the UI.
Products are grouped by type in the Top 25 dropdown view.
"""

import re
import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ─── PRODUCT TYPE DEFINITIONS ────────────────────────────────────────────────
# Each entry: (type_id, display_label, emoji, keywords)
# Keywords are matched against: brand name + product type + caption text
# Order matters — more specific types should come BEFORE general ones.

PRODUCT_TYPES = [

    # ── Treatments & Actives ─────────────────────────────────────────────────
    ("spot_treatment",   "Spot Treatment",     "🎯", [
        "pimple patch", "acne patch", "spot treatment", "spot gel",
        "blemish patch", "mighty patch", "starface", "acne sticker",
        "zit sticker", "hydrocolloid patch",
    ]),
    ("exfoliant",        "Exfoliant",          "✨", [
        "exfoliant", "exfoliator", "aha", "bha", "pha", "chemical exfoliant",
        "physical exfoliant", "glycolic", "lactic acid", "salicylic acid",
        "mandelic acid", "peel", "peeling", "resurfacing",
    ]),
    ("retinoid",         "Retinoid / Retinol",  "🔬", [
        "retinol", "retinoid", "tretinoin", "adapalene", "differin",
        "retin-a", "granactive retinoid", "retinal", "bakuchiol",
    ]),
    ("eye_treatment",    "Eye Treatment",       "👁️", [
        "eye cream", "eye serum", "eye gel", "under eye", "undereye",
        "eye patches", "eye mask", "dark circle", "crow's feet",
    ]),

    # ── Serums & Essences ────────────────────────────────────────────────────
    ("serum",            "Serum / Essence",     "💧", [
        "serum", "essence", "ampoule", "booster", "concentrate",
        "face drops", "niacinamide serum", "vitamin c serum",
        "hyaluronic acid serum", "snail mucin serum", "peptide serum",
        "brightening serum", "hydrating serum", "glow serum",
        "lash serum", "brow serum",
    ]),

    # ── Toners ───────────────────────────────────────────────────────────────
    ("toner",            "Toner",               "🌊", [
        "toner", "toning", "toning water", "toning lotion",
        "prep toner", "hydrating toner", "exfoliating toner",
        "balancing toner", "ph toner", "first essence",
        "softener", "lotion toner", "mist toner",
    ]),

    # ── Moisturizers ─────────────────────────────────────────────────────────
    ("moisturizer",      "Moisturizer",         "🧴", [
        "moisturizer", "moisturising", "moisturizing", "moisturiser",
        "hydrating cream", "face cream", "moisturizing cream",
        "gel cream", "water cream", "barrier cream", "lotion",
        "emulsion", "sleeping pack", "overnight cream", "night cream",
        "day cream", "ceramide cream", "peptide cream", "snail cream",
        "skin barrier", "dewy skin cream",
    ]),

    # ── Cleansers ────────────────────────────────────────────────────────────
    ("cleanser",         "Cleanser",            "🫧", [
        "cleanser", "face wash", "cleansing", "foam cleanser",
        "gel cleanser", "cream cleanser", "oil cleanser", "cleansing oil",
        "balm cleanser", "cleansing balm", "micellar water", "micellar",
        "double cleanse", "cleansing milk", "cleansing foam",
    ]),

    # ── Sunscreen ────────────────────────────────────────────────────────────
    ("sunscreen",        "Sunscreen / SPF",     "☀️", [
        "sunscreen", "spf", "sun cream", "sunblock", "uv protection",
        "uv filter", "mineral sunscreen", "chemical sunscreen",
        "broad spectrum", "pa+++", "tinted spf", "sunscreen serum",
        "lightweight spf", "no white cast",
    ]),

    # ── Face Masks ───────────────────────────────────────────────────────────
    ("mask",             "Face Mask",           "🎭", [
        "face mask", "sheet mask", "clay mask", "mud mask",
        "charcoal mask", "sleeping mask", "overnight mask",
        "peel-off mask", "hydrogel mask", "rubber mask",
        "wash-off mask", "glass skin mask",
    ]),

    # ── Face Oils ────────────────────────────────────────────────────────────
    ("face_oil",         "Face Oil",            "🌿", [
        "face oil", "facial oil", "dry oil", "rosehip oil",
        "jojoba oil", "squalane", "marula oil", "sea buckthorn",
        "argan oil", "bakuchiol oil", "face serum oil",
    ]),

    # ── Lip Care ─────────────────────────────────────────────────────────────
    ("lip_care",         "Lip Care",            "💋", [
        "lip mask", "lip balm", "lip serum", "lip butter",
        "lip scrub", "lip treatment", "lip sleeping mask",
        "laneige lip", "overnight lip", "lip oil",
    ]),

    # ── Beauty Tools & Devices ───────────────────────────────────────────────
    ("led_device",       "LED & Light Therapy", "💡", [
        "led mask", "led device", "light therapy", "red light therapy",
        "blue light therapy", "infrared", "omnilux", "currentbody",
        "lightstim", "dr. dennis gross", "foreo ufo",
    ]),
    ("microcurrent",     "Microcurrent Device", "⚡", [
        "microcurrent", "nuface", "ziip", "theraface",
        "microcurrent wand", "lifting device", "facial toning",
    ]),
    ("facial_tool",      "Facial Tool",         "🪨", [
        "gua sha", "jade roller", "facial roller", "ice roller",
        "facial massager", "face roller", "rose quartz",
        "solawave", "red light wand", "beauty wand",
        "pore vacuum", "blackhead remover", "face steamer",
    ]),
    ("hair_tool",        "Hair Tool / Scalp",   "💇", [
        "scalp serum", "hair growth", "hair serum", "scalp scrub",
        "hair oil scalp", "scalp massager", "hair mask scalp",
    ]),

    # ── Makeup: Complexion ───────────────────────────────────────────────────
    ("foundation",       "Foundation / Base",   "🪞", [
        "foundation", "concealer", "tinted moisturizer", "bb cream",
        "cc cream", "cushion foundation", "skin tint", "tinted spf",
        "primer", "setting spray", "setting powder", "loose powder",
        "pressed powder", "full coverage", "dewy foundation",
    ]),
    ("blush_bronzer",    "Blush & Bronzer",     "🌸", [
        "blush", "bronzer", "highlighter", "contour", "strobe",
        "liquid blush", "cream blush", "cheek tint", "blusher",
        "bronzing drops", "glow drops",
    ]),

    # ── Makeup: Eyes ─────────────────────────────────────────────────────────
    ("eye_makeup",       "Eye Makeup",          "👀", [
        "mascara", "eyeliner", "eyeshadow", "eye palette", "liner",
        "brow gel", "brow pencil", "brow pomade", "brow lamination",
        "lash primer", "lengthening mascara", "volumizing mascara",
    ]),

    # ── Makeup: Lips ─────────────────────────────────────────────────────────
    ("lip_makeup",       "Lip Makeup",          "💄", [
        "lipstick", "lip gloss", "lip liner", "lip combo",
        "liquid lipstick", "lip stain", "lip plumper",
        "lipliner", "gloss", "tinted lip",
    ]),

    # ── Body Care ────────────────────────────────────────────────────────────
    ("body_care",        "Body Care",           "🛁", [
        "body lotion", "body butter", "body oil", "body scrub",
        "body serum", "body wash", "shower gel", "exfoliating body",
        "neck cream", "chest serum", "decolletage", "stretch marks",
        "body moisturizer", "hand cream", "hand serum",
    ]),

    # ── Fragrance ────────────────────────────────────────────────────────────
    ("fragrance",        "Fragrance",           "🌺", [
        "perfume", "fragrance", "eau de parfum", "edp", "edt",
        "cologne", "body spray", "hair mist", "scent",
        "eau de toilette", "parfum",
    ]),
]

# Quick-lookup maps
_TYPE_ID_TO_META = {t[0]: {"label": t[1], "emoji": t[2]} for t in PRODUCT_TYPES}
_KEYWORD_TO_TYPE: dict[str, str] = {}
for type_id, label, emoji, keywords in PRODUCT_TYPES:
    for kw in keywords:
        _KEYWORD_TO_TYPE[kw.lower()] = type_id


# ─── LAYER 1: STATIC CLASSIFIER ──────────────────────────────────────────────

def classify_static(brand: str, product_type_raw: str,
                    caption: str = "") -> str | None:
    """
    Tries to classify a product into a taxonomy type using keyword matching.
    Returns a type_id string, or None if no match found.

    Checks (in order of priority):
    1. Raw product type string from extractor
    2. Brand name (some brands are type-specific, e.g. 'mighty patch')
    3. Caption text (for context clues)
    """
    combined = f"{brand} {product_type_raw} {caption}".lower()

    # Match longest keywords first (more specific wins)
    sorted_kws = sorted(_KEYWORD_TO_TYPE.keys(), key=len, reverse=True)
    for kw in sorted_kws:
        if kw in combined:
            return _KEYWORD_TO_TYPE[kw]

    return None


# ─── LAYER 2: CLAUDE FALLBACK ────────────────────────────────────────────────

_claude_cache: dict[str, str] = {}  # Cache to avoid repeat API calls


def classify_with_claude(brand: str, product_type_raw: str,
                          caption: str = "") -> str:
    """
    Uses Claude to classify a product when static matching fails.
    Results are cached in-memory to avoid duplicate calls.
    Returns a type_id string (defaults to 'serum' if classification fails).
    """
    cache_key = f"{brand}|{product_type_raw}".lower()
    if cache_key in _claude_cache:
        return _claude_cache[cache_key]

    from safety import is_test_mode
    if is_test_mode():
        logger.debug(f"TEST MODE: Claude fallback skipped for '{brand} {product_type_raw}' → defaulting to 'serum'")
        return "serum"

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "serum"

    type_options = "\n".join(
        f"  {t[0]}: {t[1]} (e.g. {', '.join(t[3][:3])})"
        for t in PRODUCT_TYPES
    )

    prompt = f"""You are classifying a beauty/skincare product into exactly one product type category.

Product: "{brand} {product_type_raw}"
Caption context: "{caption[:200]}"

Available types:
{type_options}

Reply with ONLY the type_id (e.g. "serum", "toner", "moisturizer"). Nothing else."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}]
        )
        result = response.content[0].text.strip().lower()

        # Validate it's a real type_id
        if result in _TYPE_ID_TO_META:
            _claude_cache[cache_key] = result
            logger.debug(f"Claude classified '{brand} {product_type_raw}' → {result}")
            return result
        else:
            logger.warning(f"Claude returned unknown type '{result}' for '{brand} {product_type_raw}'")
            return "serum"

    except Exception as e:
        logger.warning(f"Claude taxonomy fallback failed: {e}")
        return "serum"


# ─── PUBLIC API ──────────────────────────────────────────────────────────────

def classify(brand: str, product_type_raw: str, caption: str = "") -> str:
    """
    Classifies a product into a taxonomy type_id.
    Tries static matching first, falls back to Claude if needed.
    """
    result = classify_static(brand, product_type_raw, caption)
    if result:
        return result

    logger.debug(f"Static match failed for '{brand} {product_type_raw}' — trying Claude fallback")
    return classify_with_claude(brand, product_type_raw, caption)


def get_label(type_id: str) -> str:
    """Returns the display label for a type_id."""
    return _TYPE_ID_TO_META.get(type_id, {}).get("label", "Skincare")


def get_emoji(type_id: str) -> str:
    """Returns the emoji for a type_id."""
    return _TYPE_ID_TO_META.get(type_id, {}).get("emoji", "✨")


def get_all_types() -> list[dict]:
    """Returns all product types as a list of dicts for the UI dropdown."""
    return [
        {"type_id": t[0], "label": t[1], "emoji": t[2]}
        for t in PRODUCT_TYPES
    ]


def group_by_type(products: list[dict]) -> dict[str, list[dict]]:
    """
    Groups a ranked product list by product type for the dropdown UI.

    Input:  list of product dicts with a 'product_type_id' field
    Output: {type_id: [product, product, ...]} sorted by rank within each type
    """
    groups: dict[str, list[dict]] = {}
    for product in products:
        type_id = product.get("product_type_id", "serum")
        if type_id not in groups:
            groups[type_id] = []
        groups[type_id].append(product)

    # Sort each group by rank
    for type_id in groups:
        groups[type_id].sort(key=lambda p: p.get("rank", 999))

    return groups
