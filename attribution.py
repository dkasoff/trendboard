"""
trendboard.fyi — Influencer Attribution Engine
================================================
Identifies the "spark" behind a trending product and builds the
story of how it went from unknown to Top 25.

For each product candidate, this module:
  1. Finds the most impactful creator post (the spark)
  2. Detects the trend pattern (derm-validated, viral reviewer,
     grassroots organic, brand-pushed, etc.)
  3. Builds a structured Attribution object with real creator data
  4. Passes all of this to Claude to write a sharp editorial sentence

Output example:
  "@dermdoctor posted a before/after; 200 creators followed in 48 hours"
  "K-beauty micro-creators drove organic buzz before any mega post existed"
  "Hyram's 3M-follower review sent search volume up 400% overnight"
"""

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ─── KNOWN CREATOR REGISTRY ──────────────────────────────────────────────────
# Maps TikTok handles to tier labels for richer attribution copy.
# These are the creators whose posts most reliably spark search volume spikes.

KNOWN_CREATORS = {
    # Dermatologists
    "dermdoctor":       {"label": "Dr. Dray (17M-follower dermatologist)", "tier": "derm"},
    "drdustinportela":  {"label": "Dr. Dustin Portela (dermatologist)",    "tier": "derm"},
    "dr.tomassian":     {"label": "Dr. Tomassian (dermatologist)",         "tier": "derm"},
    "skinbydrazi":      {"label": "Dr. Azi (dermatologist)",               "tier": "derm"},
    "drcharlesmd1":     {"label": "Dr. Charles (dermatologist)",           "tier": "derm"},
    "drwhitneybowe":    {"label": "Dr. Whitney Bowe (dermatologist)",      "tier": "derm"},
    "drshereene":       {"label": "Dr. Shereene Idriss (dermatologist)",   "tier": "derm"},

    # Skincare educators
    "skincarebyhyram":  {"label": "Hyram (6.8M skincare educator)",        "tier": "educator"},
    "gothamista":       {"label": "Gothamista (skincare educator)",         "tier": "educator"},
    "mixedmakeup":      {"label": "Mixed Makeup (educator)",               "tier": "educator"},
    "labmuffinbeautyscience": {"label": "Lab Muffin Beauty Science",       "tier": "educator"},

    # Viral reviewers
    "mikaylanogueira":  {"label": "Mikayla Nogueira (16.7M)",              "tier": "viral"},
    "glamzilla":        {"label": "Glamzilla (5M)",                        "tier": "viral"},
    "jadeylauren":      {"label": "Jadey Lauren (2M)",                     "tier": "viral"},
    "cassandrabankson": {"label": "Cassandra Bankson (1.5M)",              "tier": "viral"},

    # K-beauty specialists
    "beautywithinofficial": {"label": "Beauty Within (3M)",                "tier": "kbeauty"},
    "kimsundaram_":     {"label": "Kim Sundaram (K-beauty specialist)",    "tier": "kbeauty"},
}

# Tier priority for spark selection (lower = higher priority)
TIER_PRIORITY = {"derm": 0, "educator": 1, "viral": 2, "kbeauty": 3,
                 "mega": 4, "macro": 5, "micro": 6, "nano": 7}


# ─── DATA STRUCTURES ─────────────────────────────────────────────────────────

@dataclass
class CreatorPost:
    """A single creator's post about a product."""
    handle: str
    followers: int
    date: str
    likes: int
    comments: int
    caption_snippet: str
    is_sponsored: bool
    tier: str                    # nano / micro / macro / mega
    known_label: str = ""        # e.g. "Hyram (6.8M skincare educator)"


@dataclass
class Attribution:
    """
    The full attribution story for one trending product.
    Passed to Claude to generate the 'why it's trending' sentence.
    """
    product_name: str

    # The spark: the single most impactful post
    spark_handle: str       = ""
    spark_label: str        = ""     # Known creator label if in registry
    spark_followers: int    = 0
    spark_date: str         = ""
    spark_likes: int        = 0
    spark_tier: str         = ""
    spark_is_sponsored: bool = False

    # The wave: what happened after the spark
    creators_after_spark: int   = 0   # Creators who posted after spark date
    days_since_spark: int       = 0

    # Trend pattern
    pattern: str                = ""  # see TREND_PATTERNS below
    pattern_label: str          = ""

    # Supporting data
    total_creators: int         = 0
    mega_count: int             = 0
    macro_count: int            = 0
    micro_count: int            = 0
    nano_count: int             = 0
    organic_ratio: float        = 0.0
    has_derm_endorsement: bool  = False
    has_viral_reviewer: bool    = False
    is_kbeauty: bool            = False

    # All top posts (for Claude context)
    top_posts: list = field(default_factory=list)


# ─── TREND PATTERNS ──────────────────────────────────────────────────────────

TREND_PATTERNS = {
    "derm_sparked":     "Dermatologist-sparked",
    "educator_sparked": "Skincare educator-sparked",
    "viral_sparked":    "Viral reviewer-sparked",
    "kbeauty_wave":     "K-beauty wave",
    "grassroots":       "Organic grassroots",
    "brand_pushed":     "Brand-driven (high sponsored ratio)",
    "algorithm_pick":   "Algorithm pick (sudden spike, unknown origin)",
}


# ─── CORE ENGINE ─────────────────────────────────────────────────────────────

def build_attribution(candidate) -> Attribution:
    """
    Builds an Attribution object from a ProductCandidate.
    Identifies the spark post and trend pattern from stored creator posts.
    """
    posts = candidate.top_creator_posts or []

    attr = Attribution(
        product_name    = candidate.display_name,
        total_creators  = candidate.unique_creator_count,
        mega_count      = candidate.mega_creators,
        macro_count     = candidate.macro_creators,
        micro_count     = candidate.micro_creators,
        nano_count      = candidate.nano_creators,
    )

    if not posts:
        attr.pattern = "grassroots"
        attr.pattern_label = TREND_PATTERNS["grassroots"]
        return attr

    # Enrich posts with known creator labels
    enriched = []
    for p in posts:
        handle = p.get("handle", "").lower().lstrip("@")
        known = KNOWN_CREATORS.get(handle, {})
        enriched.append(CreatorPost(
            handle          = p.get("handle", ""),
            followers       = p.get("followers", 0),
            date            = p.get("date", ""),
            likes           = p.get("likes", 0),
            comments        = p.get("comments", 0),
            caption_snippet = p.get("caption", "")[:120],
            is_sponsored    = p.get("is_sponsored", False),
            tier            = known.get("tier") or p.get("tier", "nano"),
            known_label     = known.get("label", ""),
        ))

    # Select spark: prefer known creators, then by follower count
    enriched.sort(key=lambda p: (
        TIER_PRIORITY.get(p.tier, 7),
        -p.followers
    ))
    spark = enriched[0]

    attr.spark_handle       = spark.handle
    attr.spark_label        = spark.known_label or f"@{spark.handle}"
    attr.spark_followers    = spark.followers
    attr.spark_date         = spark.date
    attr.spark_likes        = spark.likes
    attr.spark_tier         = spark.tier
    attr.spark_is_sponsored = spark.is_sponsored
    attr.top_posts          = enriched[:5]

    # Calculate wave: posts after the spark date
    if spark.date:
        try:
            spark_dt = datetime.strptime(spark.date[:10], "%Y-%m-%d")
            attr.days_since_spark = (datetime.utcnow() - spark_dt).days
            attr.creators_after_spark = sum(
                1 for p in enriched[1:]
                if p.date and p.date[:10] >= spark.date[:10]
            )
        except ValueError:
            pass

    # Organic ratio
    total = candidate.sponsored_count + candidate.organic_count
    attr.organic_ratio = candidate.organic_count / total if total > 0 else 1.0

    # Flags
    attr.has_derm_endorsement = any(p.tier == "derm" for p in enriched)
    attr.has_viral_reviewer   = any(p.tier == "viral" for p in enriched)
    attr.is_kbeauty           = any(p.tier == "kbeauty" for p in enriched)

    # Determine trend pattern
    attr.pattern = _detect_pattern(attr)
    attr.pattern_label = TREND_PATTERNS.get(attr.pattern, attr.pattern)

    return attr


def _detect_pattern(attr: Attribution) -> str:
    """Picks the most accurate trend pattern label."""
    if attr.has_derm_endorsement:
        return "derm_sparked"
    if attr.spark_tier == "educator":
        return "educator_sparked"
    if attr.has_viral_reviewer or attr.spark_tier == "viral":
        return "viral_sparked"
    if attr.is_kbeauty:
        return "kbeauty_wave"
    if attr.organic_ratio < 0.5:
        return "brand_pushed"
    if attr.nano_count > (attr.micro_count + attr.macro_count + attr.mega_count):
        return "grassroots"
    return "algorithm_pick"


# ─── STORY GENERATOR ─────────────────────────────────────────────────────────

def generate_story(attr: Attribution, score=None) -> str:
    """
    Generates a sharp one-sentence 'why it's trending' story using Claude.
    Falls back to a template sentence if Claude is unavailable.

    In TEST_MODE: uses template (no API cost).
    In LIVE_MODE: uses Claude Haiku (~$0.001 per call).
    """
    from safety import is_test_mode

    if is_test_mode():
        return _template_story(attr)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _template_story(attr)

    prompt = _build_prompt(attr, score)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}]
        )
        story = response.content[0].text.strip().strip('"')
        logger.info(f"  Attribution story for {attr.product_name}: \"{story}\"")
        return story

    except Exception as e:
        logger.warning(f"Attribution story generation failed for {attr.product_name}: {e}")
        return _template_story(attr)


def _build_prompt(attr: Attribution, score=None) -> str:
    """Builds the Claude prompt with full attribution context."""

    top_post_lines = ""
    for i, p in enumerate(attr.top_posts[:3], 1):
        label = p.known_label or f"@{p.handle} ({p.followers:,} followers)"
        top_post_lines += (
            f"  #{i}: {label} — {p.likes:,} likes"
            f"{' [SPONSORED]' if p.is_sponsored else ' [ORGANIC]'}"
            f" — \"{p.caption_snippet[:80]}\"\n"
        )

    velocity = f"{score.velocity_score:.0f}/100" if score else "unknown"

    return f"""You are the editorial voice of Trendboard.fyi — a data-driven skincare trend chart.

Write ONE sentence (max 18 words) explaining why "{attr.product_name}" is blowing up RIGHT NOW.

ATTRIBUTION DATA:
- Trend pattern: {attr.pattern_label}
- Spark creator: {attr.spark_label} ({attr.spark_followers:,} followers)
  Posted {attr.days_since_spark} days ago — {attr.spark_likes:,} likes
  {"[SPONSORED POST]" if attr.spark_is_sponsored else "[ORGANIC POST]"}
- Creators who followed after spark: {attr.creators_after_spark}
- Total unique creators this week: {attr.total_creators}
  (mega: {attr.mega_count}, macro: {attr.macro_count}, micro: {attr.micro_count}, nano: {attr.nano_count})
- Organic vs sponsored ratio: {attr.organic_ratio:.0%} organic
- Has derm endorsement: {attr.has_derm_endorsement}
- Velocity score: {velocity}

TOP POSTS THIS WEEK:
{top_post_lines}

RULES:
- Be specific — name the creator or pattern if it's compelling
- Do NOT use the word "trending"
- Sound like a sharp beauty editor, not a press release
- If sponsored ratio is high (>50%), hint that it may be brand-pushed
- If derm-endorsed, lead with that — it's the strongest signal
- If grassroots with mostly nano/micro creators, emphasize that authenticity
- One sentence only — no explanations, no preamble

GOOD EXAMPLES:
  "Hyram posted once; 300 creators followed within the week"
  "Dermatologists validated the formula before any influencer touched it"
  "K-beauty micro-creators drove organic buzz for 3 weeks before it went mega"
  "The before/afters went viral; brands scrambled to sponsor it after the fact"
  "Every dermatologist on TikTok posted the same week — something in the data broke"

Output only the sentence."""


def _template_story(attr: Attribution) -> str:
    """Rule-based fallback story for test mode or API failures."""

    spark = attr.spark_label or f"a {attr.spark_tier} creator"
    wave  = attr.creators_after_spark
    days  = attr.days_since_spark

    if attr.has_derm_endorsement:
        return f"Dermatologist-endorsed on TikTok; {attr.total_creators} creators followed within days"

    if attr.pattern == "educator_sparked":
        return f"{spark} posted {days} days ago; {wave} creators picked it up immediately"

    if attr.pattern == "viral_sparked":
        likes_str = f"{attr.spark_likes:,} likes" if attr.spark_likes else "millions of views"
        return f"{spark}'s review hit {likes_str}; the waitlist followed"

    if attr.pattern == "kbeauty_wave":
        return f"K-beauty specialists drove organic buzz for weeks before it crossed over"

    if attr.pattern == "brand_pushed":
        return f"Heavy influencer seeding this week — {attr.organic_ratio:.0%} of posts are organic"

    if attr.pattern == "grassroots":
        return f"{attr.nano_count + attr.micro_count} micro-creators posted organically — no mega spark yet"

    return f"{attr.total_creators} unique creators posted this week with strong search momentum"
