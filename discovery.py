"""
trendboard.fyi — Skincare Discovery Scraper
============================================
Uses Apify to scrape TikTok videos and Instagram posts from:
  1. Skincare/beauty hashtags (broad signal)
  2. Trusted creator accounts (quality signal — TikTok only)

Returns a list of VideoSignal objects ready for the extractor.

Cost management:
  - TikTok Tier 1+2 hashtags: weekly, 200 videos each   ≈ $0.30/hashtag
  - TikTok creator accounts: weekly, 50 videos each      ≈ $0.30/account
  - Instagram hashtags: weekly, 100 posts each           ≈ $0.10/hashtag
  - Full weekly run: ~$55 TikTok + ~$1.20 Instagram

Rate limiting:
  - 3 second sleep between Apify calls
  - Polls for results up to 60 seconds before timing out
  - On timeout, returns empty list for that hashtag (non-blocking)

Usage:
    scraper = DiscoveryScraper(apify_token="your_token")
    videos = scraper.run_full_discovery()
"""

import os
import time
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apify_client import ApifyClient

from extractor import VideoSignal
from safety import guard, is_test_mode, COST_ESTIMATES

load_dotenv()
logger = logging.getLogger(__name__)


# ─── HASHTAG REGISTRY ────────────────────────────────────────────────────────
# Organized by tier. Tier 1 scrapes every run, Tier 2 every other run.
# 200 videos per hashtag is the sweet spot: enough signal, manageable cost.

HASHTAGS_TIER1 = [
    # Core skincare discovery — always scrape
    "skincaretok", "skincareproducts", "skincarereview",
    "dermatologistrecommended", "dermatologist",
    "acnetreatment", "acneskincare", "skincareroutine",
    "beautytok", "beautyreview", "beautyproducts",
    "amazonskincare", "amazonbeauty", "amazonfinds",
    "tiktokmademebuyit", "skincarehaul", "beautyhaul",
    "unboxing", "productreview", "beforeandafter",
]

HASHTAGS_TIER2 = [
    # Category specific — scrape weekly for skincare focus
    "koreanskincare", "kbeauty", "kbeautyroutine",
    "serumtok", "retinol", "niacinamide", "vitaminc",
    "hyaluronicacid", "spfsunscreen", "sunscreentok",
    "ledmask", "ledtherapy", "microneedling",
    "chemicalexfoliant", "ahaskincare", "bhaskincare",
    "cleanskincare", "glasskin", "skintok",
    "acneprone", "sensitiveskin", "dryskin",
    "antiaging", "peptides", "ceramides", "snailmucin",
    "slugging", "skincareingredients",
    "gelcleanser", "foamcleanser", "micellarwater",
    "tonerandserum", "eyecream", "neckcare",
    "bodycare", "bodyskincare", "exfoliation",
]

HASHTAGS_DEVICES = [
    # Beauty tools — bi-weekly
    "beautytools", "skincaregadgets", "facemassager",
    "guashatool", "jaderoller", "microcurrent",
    "lighttherapy", "redlighttherapy", "bluelighttherapy",
    "athomefacial", "ipl",
]

HASHTAGS_MAKEUP = [
    # Makeup — bi-weekly
    "makeuptok", "makeupproducts", "makeuphaul",
    "makeupfinds", "grwm", "getreadywithme",
    "lipcombo", "foundationreview", "concealerhacks",
    "blushdraping", "cleanmakeup", "glowymakeup",
]

# ─── INSTAGRAM ACTOR + HASHTAGS ──────────────────────────────────────────────
# Actor: apify/instagram-scraper (most-used, actively maintained)
# Searches by hashtag → returns recent posts with captions, likes, comments.
# Note: follower count requires addParentData=True (extra cost) — skipped for now.
# Instagram hashtag culture differs from TikTok: fewer viral spikes, more
# sustained community discussion. Good for confirming products that are
# genuinely embedded in the skincare community vs. one-off TikTok moments.

INSTAGRAM_ACTOR_ID = "shu8hvrXbJbY3Eb9W"   # apify/instagram-scraper

INSTAGRAM_HASHTAGS = [
    # Routine & review — highest product mention density
    "skincareroutine", "skincarereview", "skincarefinds",
    "skincareproducts", "skincarerecommendation",

    # K-beauty — dominant trending segment
    "kbeauty", "kbeautyroutine", "kbeautyproducts",

    # Ingredient-led — maps directly to our product taxonomy
    "retinol", "niacinamide", "spfsunscreen", "hyaluronicacid",

    # Purchase intent / discovery
    "sephorafinds", "amazonskincarehaul",

    # Skin concern communities — strong organic signal
    "acneskincare", "dryskincare", "sensitiveskin",

    # General discovery
    "skincaretok", "skintok",
]

# ─── CREATOR ACCOUNT REGISTRY ────────────────────────────────────────────────
# These are the accounts whose product mentions are the strongest lead signal.
# When they post about a product, Google search volume typically follows in 48–72h.

CREATOR_ACCOUNTS = [
    # Dermatologist tier — highest trust
    {"handle": "dermdoctor",       "tier": "derm",     "followers": 17_000_000},
    {"handle": "drdustinportela",  "tier": "derm",     "followers": 2_400_000},
    {"handle": "dr.tomassian",     "tier": "derm",     "followers": 2_000_000},
    {"handle": "skinbydrazi",      "tier": "derm",     "followers": 1_900_000},
    {"handle": "drcharlesmd1",     "tier": "derm",     "followers": 1_800_000},
    {"handle": "drwhitneybowe",    "tier": "derm",     "followers": 1_100_000},
    {"handle": "drshereene",       "tier": "derm",     "followers": 1_000_000},

    # Skincare educator tier
    {"handle": "skincarebyhyram",  "tier": "educator", "followers": 6_800_000},
    {"handle": "elevenesthetician","tier": "educator", "followers": 200_000},
    {"handle": "gothamista",       "tier": "educator", "followers": 800_000},
    {"handle": "labmuffinbeautyscience", "tier": "educator", "followers": 300_000},
    {"handle": "mixedmakeup",      "tier": "educator", "followers": 1_200_000},

    # Viral beauty reviewers — fastest trend signal
    {"handle": "mikaylanogueira",  "tier": "viral",    "followers": 16_700_000},
    {"handle": "glamzilla",        "tier": "viral",    "followers": 5_000_000},
    {"handle": "jadeylauren",      "tier": "viral",    "followers": 2_000_000},
    {"handle": "cassandrabankson", "tier": "viral",    "followers": 1_500_000},

    # K-beauty specialists
    {"handle": "beautywithinofficial", "tier": "kbeauty", "followers": 3_000_000},
    {"handle": "kimsundaram_",     "tier": "kbeauty",  "followers": 500_000},
]


# ─── TIKTOK ACTOR ────────────────────────────────────────────────────────────
# clockworks/tiktok-scraper — actor ID from Apify console Python snippet.
# Uses sync ApifyClient (not async); run["defaultDatasetId"] is dict key access.

TIKTOK_ACTOR_ID = "GdWCkxBtKWOsKjdch"   # clockworks/tiktok-scraper

# Minimal input — only the fields we need, everything else at actor defaults.
# Based on the official Python snippet from Apify console.
_TIKTOK_BASE_INPUT = {
    "excludePinnedPosts":           False,
    "shouldDownloadVideos":         False,
    "shouldDownloadCovers":         False,
    "shouldDownloadSlideshowImages":False,
    "shouldDownloadAvatars":        False,
    "shouldDownloadMusicCovers":    False,
    "commentsPerPost":              0,
    "topLevelCommentsPerPost":      0,
    "maxRepliesPerComment":         0,
    "scrapeRelatedVideos":          False,
    "proxyCountryCode":             "None",
    "downloadSubtitlesOptions":     "NEVER_DOWNLOAD_SUBTITLES",
}


# ─── VIDEO PARSERS ───────────────────────────────────────────────────────────

def parse_tiktok_video(raw: dict, source_hashtag: str = "") -> VideoSignal | None:
    """
    Parses a raw Apify TikTok result into a VideoSignal.
    Returns None if essential fields are missing.
    """
    try:
        author = raw.get("authorMeta", {}) or {}
        music  = raw.get("musicMeta", {}) or {}

        video_id      = str(raw.get("id", ""))
        creator_id    = str(author.get("id", ""))
        creator_handle= str(author.get("name", ""))
        caption       = str(raw.get("text", ""))
        like_count    = int(raw.get("diggCount", 0) or 0)
        comment_count = int(raw.get("commentCount", 0) or 0)
        share_count   = int(raw.get("shareCount", 0) or 0)
        follower_count= int(author.get("fans", 0) or 0)
        posted_date   = str(raw.get("createTimeISO", ""))

        if not video_id or not creator_id or not caption:
            return None

        # Extract hashtags from caption
        hashtags = re.findall(r'#(\w+)', caption.lower()) if caption else []

        # Detect sponsorship — prefer the actor's isAd flag (more reliable than
        # hashtag detection), fall back to hashtag scanning for older-format results
        sponsored_tags = {"ad", "sponsored", "gifted", "partner", "collab", "paid"}
        is_sponsored   = bool(raw.get("isAd", False)) or bool(sponsored_tags & set(hashtags))

        return VideoSignal(
            video_id       = video_id,
            creator_id     = creator_id,
            creator_handle = creator_handle,
            caption        = caption,
            hashtags       = hashtags,
            like_count     = like_count,
            comment_count  = comment_count,
            share_count    = share_count,
            follower_count = follower_count,
            posted_date    = posted_date,
            platform       = "tiktok",
            is_sponsored   = is_sponsored,
        )
    except Exception as e:
        logger.warning(f"Failed to parse TikTok video: {e}")
        return None


# ─── INSTAGRAM POST PARSER ───────────────────────────────────────────────────

def parse_instagram_post(raw: dict) -> VideoSignal | None:
    """
    Parses a raw apify/instagram-scraper result into a VideoSignal.

    Field mapping (apify/instagram-scraper response):
      raw["id"]            → video_id
      raw["ownerId"]       → creator_id
      raw["ownerUsername"] → creator_handle
      raw["caption"]       → caption
      raw["hashtags"]      → hashtags (already parsed list)
      raw["likesCount"]    → like_count
      raw["commentsCount"] → comment_count
      raw["timestamp"]     → posted_date (ISO 8601)
      raw["type"]          → "Image" | "Video" | "Sidecar"

    Note: follower_count is not available without addParentData=True.
    Defaults to 0 — Instagram posts contribute to density/sentiment scoring
    but not creator-tier weighting.
    """
    try:
        post_id = str(raw.get("id") or raw.get("shortCode", ""))
        caption = str(raw.get("caption") or "")

        if not post_id or not caption.strip():
            return None

        # Instagram "Limited permissions" for hashtag scrapes means ownerId and
        # ownerUsername are not returned. Fall back to shortCode as a unique
        # creator proxy for deduplication — not ideal but prevents empty IDs
        # collapsing all posts into one bucket.
        handle   = str(raw.get("ownerUsername", ""))
        owner_id = str(raw.get("ownerId") or raw.get("ownerUsername") or raw.get("shortCode", post_id))

        # Instagram likesCount semantics:
        #   -1  = account has disabled like count display (data unavailable)
        #    0  = like count is visible but post has zero likes
        #   >0  = true displayed like count
        # Treat -1 as 0 for scoring — we simply have no signal for hidden-like posts.
        raw_likes = raw.get("likesCount")
        likes     = max(int(raw_likes or 0), 0)
        comments  = int(raw.get("commentsCount") or 0)
        ts        = str(raw.get("timestamp", ""))

        # Hashtags come pre-parsed as a list from this actor
        hashtags = [str(h).lower().lstrip("#") for h in (raw.get("hashtags") or [])]

        # Fall back to extracting from caption if list is empty
        if not hashtags and caption:
            hashtags = re.findall(r'#(\w+)', caption.lower())

        # Detect sponsorship
        sponsored_tags = {"ad", "sponsored", "gifted", "partner", "collab", "paid",
                          "paidpartnership", "advertisement"}
        is_sponsored = (bool(sponsored_tags & set(hashtags)) or
                        any(f"#{t}" in caption.lower() for t in sponsored_tags))

        return VideoSignal(
            video_id       = f"ig_{post_id}",
            creator_id     = f"ig_{owner_id}",
            creator_handle = handle,
            caption        = caption,
            hashtags       = hashtags,
            like_count     = likes,
            comment_count  = comments,
            share_count    = 0,          # Instagram doesn't expose share counts
            follower_count = 0,          # Requires addParentData=True — skipped
            posted_date    = ts[:10] if ts else "",   # Trim to YYYY-MM-DD
            platform       = "instagram",
            is_sponsored   = is_sponsored,
        )
    except Exception as e:
        logger.warning(f"Failed to parse Instagram post: {e}")
        return None


# ─── DISCOVERY SCRAPER ────────────────────────────────────────────────────────

import re   # needed inside the module for hashtag extraction in parse_tiktok_video

class DiscoveryScraper:
    """
    Main discovery engine.
    Runs TikTok hashtag + creator scrapes and Instagram hashtag scrapes via Apify.

    TikTok:    sync ApifyClient  — actor GdWCkxBtKWOsKjdch (clockworks/tiktok-scraper)
    Instagram: async ApifyClientAsync — actor shu8hvrXbJbY3Eb9W (apify/instagram-scraper)
    """

    def __init__(self, apify_token: str = None):
        self.token          = apify_token or os.getenv("APIFY_TOKEN", "")
        self.client         = ApifyClient(self.token)   # sync, for TikTok
        self.seven_days_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    def scrape_hashtag(self, hashtag: str,
                       max_videos: int = 200) -> list[VideoSignal]:
        """
        Scrapes a single TikTok hashtag for recent videos.
        Uses sync ApifyClient — run["defaultDatasetId"] is dict key access.
        """
        logger.info(f"    Scraping TikTok #{hashtag} (max {max_videos})")
        guard("TikTok scraper: #" + hashtag, COST_ESTIMATES["apify_tiktok_hashtag"])

        try:
            run = self.client.actor(TIKTOK_ACTOR_ID).call(run_input={
                **_TIKTOK_BASE_INPUT,
                "hashtags":             [hashtag],
                "resultsPerPage":       max_videos,
                "oldestPostDateUnified": self.seven_days_ago,  # server-side date filter
            })
            raw_items = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())
        except Exception as e:
            logger.warning(f"    TikTok scrape failed for #{hashtag}: {e}")
            return []

        videos = []
        for item in raw_items:
            v = parse_tiktok_video(item, source_hashtag=hashtag)
            if v and v.posted_date >= self.seven_days_ago:
                videos.append(v)

        logger.info(f"    → {len(videos)} recent videos from #{hashtag}")
        time.sleep(3)   # polite delay between actor runs
        return videos

    def scrape_creator(self, creator: dict,
                       max_videos: int = 50) -> list[VideoSignal]:
        """
        Scrapes recent videos from a specific TikTok creator account.
        Uses sync ApifyClient — run["defaultDatasetId"] is dict key access.
        """
        handle = creator["handle"]
        logger.info(f"    Scraping TikTok @{handle} (max {max_videos})")
        guard("TikTok scraper: @" + handle, COST_ESTIMATES["apify_tiktok_hashtag"])

        try:
            run = self.client.actor(TIKTOK_ACTOR_ID).call(run_input={
                **_TIKTOK_BASE_INPUT,
                "profiles":              [handle],
                "profileScrapeSections": ["videos"],
                "profileSorting":        "latest",
                "resultsPerPage":        max_videos,
                "oldestPostDateUnified": self.seven_days_ago,
            })
            raw_items = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())
        except Exception as e:
            logger.warning(f"    TikTok scrape failed for @{handle}: {e}")
            return []

        videos = []
        for item in raw_items:
            v = parse_tiktok_video(item)
            if v:
                # Registry follower count is more reliable than what the actor returns
                v.follower_count = creator.get("followers", v.follower_count)
                if v.posted_date >= self.seven_days_ago:
                    videos.append(v)

        logger.info(f"    → {len(videos)} recent videos from @{handle}")
        time.sleep(3)
        return videos

    def scrape_instagram_hashtag(self, hashtag: str,
                                  max_posts: int = 100) -> list[VideoSignal]:
        """
        Scrapes a single Instagram hashtag using apify/instagram-scraper.

        Uses ApifyClientAsync (required by apify-client >= 1.x, Python >= 3.11).
        The async call is wrapped in asyncio.run() so the rest of the pipeline
        stays synchronous.

        Field notes (apify/instagram-scraper response):
          call_result.default_dataset_id  — attribute access, not dict key
          list_items_result.items         — list of post dicts
        """
        logger.info(f"    Scraping IG #{hashtag} (max {max_posts} posts)")
        guard("Instagram scraper: #" + hashtag,
              COST_ESTIMATES.get("apify_instagram_single", 0.10))

        import asyncio
        from apify_client import ApifyClientAsync

        async def _fetch() -> list[dict]:
            client       = ApifyClientAsync(self.token)
            actor_client = client.actor(INSTAGRAM_ACTOR_ID)

            call_result = await actor_client.call(run_input={
                "resultsType":        "posts",
                "search":             hashtag,
                "searchType":         "hashtag",
                "searchLimit":        1,       # one hashtag per call
                "resultsLimit":       max_posts,
                "addParentData":      False,   # follower count skipped — extra cost
                "onlyPostsNewerThan": self.seven_days_ago,
            })

            if call_result is None:
                logger.warning(f"    IG actor returned None for #{hashtag}")
                return []

            dataset_client    = client.dataset(call_result.default_dataset_id)
            list_items_result = await dataset_client.list_items()
            return list_items_result.items

        try:
            raw_items = asyncio.run(_fetch())
        except Exception as e:
            logger.warning(f"    Instagram scrape failed for #{hashtag}: {e}")
            return []

        posts = []
        for item in raw_items:
            v = parse_instagram_post(item)
            if v and (not v.posted_date or v.posted_date >= self.seven_days_ago):
                posts.append(v)

        logger.info(f"    → {len(posts)} recent posts from IG #{hashtag}")
        time.sleep(3)
        return posts

    def run_hashtag_discovery(self, run_devices: bool = False,
                               run_makeup: bool = False) -> list[VideoSignal]:
        """Runs all TikTok hashtag scrapes."""
        all_videos = []
        hashtags   = HASHTAGS_TIER1 + HASHTAGS_TIER2
        if run_devices: hashtags += HASHTAGS_DEVICES
        if run_makeup:  hashtags += HASHTAGS_MAKEUP

        logger.info(f"\n  TikTok hashtag discovery: {len(hashtags)} hashtags")
        for ht in hashtags:
            videos = self.scrape_hashtag(ht, max_videos=200)
            all_videos.extend(videos)

        logger.info(f"  Total from TikTok hashtags: {len(all_videos)} videos")
        return all_videos

    def run_instagram_discovery(self) -> list[VideoSignal]:
        """Runs all Instagram hashtag scrapes."""
        all_posts = []

        logger.info(f"\n  Instagram hashtag discovery: {len(INSTAGRAM_HASHTAGS)} hashtags")
        for ht in INSTAGRAM_HASHTAGS:
            posts = self.scrape_instagram_hashtag(ht, max_posts=100)
            all_posts.extend(posts)

        logger.info(f"  Total from Instagram hashtags: {len(all_posts)} posts")
        return all_posts

    def run_creator_discovery(self) -> list[VideoSignal]:
        """Runs all TikTok creator account scrapes."""
        all_videos = []

        logger.info(f"\n  Creator discovery: {len(CREATOR_ACCOUNTS)} accounts")
        for creator in CREATOR_ACCOUNTS:
            videos = self.scrape_creator(creator, max_videos=50)
            all_videos.extend(videos)

        logger.info(f"  Total from creators: {len(all_videos)} videos")
        return all_videos

    def run_full_discovery(self, run_devices: bool = False,
                            run_makeup: bool = False) -> list[VideoSignal]:
        """
        Runs the complete discovery pipeline: TikTok hashtags + creator accounts
        + Instagram hashtags.

        Returns deduplicated list of VideoSignal objects from last 7 days.
        In TEST_MODE returns empty list immediately — pipeline will use test data.

        Estimated cost per full run:
          TikTok  ~46 hashtags × $0.30  = ~$13.80
          TikTok  ~18 creators × $0.30  = ~$5.40
          Instagram ~20 hashtags × $0.10 = ~$2.00
          ─────────────────────────────────────────
          Total                           ~$21.20
          (Full 15k-video run runs closer to $55 — see safety.py)
        """
        if is_test_mode():
            logger.info("  TEST MODE — skipping live discovery, pipeline will use test data")
            return []

        logger.info("\n" + "="*60)
        logger.info("  TRENDBOARD — Skincare Discovery")
        logger.info("="*60)

        tiktok_hashtag_videos = self.run_hashtag_discovery(run_devices, run_makeup)
        tiktok_creator_videos = self.run_creator_discovery()
        instagram_posts       = self.run_instagram_discovery()

        # Combine all sources
        all_videos = tiktok_hashtag_videos + tiktok_creator_videos + instagram_posts

        # Deduplicate by video_id
        seen_ids = set()
        unique   = []
        for v in all_videos:
            if v.video_id not in seen_ids:
                seen_ids.add(v.video_id)
                unique.append(v)

        tiktok_count = sum(1 for v in unique if v.platform == "tiktok")
        ig_count     = sum(1 for v in unique if v.platform == "instagram")

        logger.info(f"\n  Total unique content pieces: {len(unique)}")
        logger.info(f"    TikTok:    {tiktok_count}")
        logger.info(f"    Instagram: {ig_count}")
        logger.info(f"  Date filter: {self.seven_days_ago} → today")

        return unique
