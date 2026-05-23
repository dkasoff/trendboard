"""
trendboard.fyi — Skincare Discovery Scraper
============================================
Uses Apify to scrape TikTok videos from:
  1. Skincare/beauty hashtags (broad signal)
  2. Trusted creator accounts (quality signal)

Returns a list of VideoSignal objects ready for the extractor.

Cost management:
  - Tier 1+2 hashtags: weekly, 200 videos each
  - Creator accounts: weekly, 50 recent videos each
  - Total: ~15,000 results/week ≈ $55 at free tier

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
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from dotenv import load_dotenv

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


# ─── APIFY CLIENT ────────────────────────────────────────────────────────────

class ApifyClient:
    """
    Thin wrapper around Apify REST API.
    Handles actor runs and result polling.
    """

    BASE_URL = "https://api.apify.com/v2"

    def __init__(self, token: str):
        self.token = token

    def run_actor(self, actor_id: str, input_data: dict,
                  poll_timeout: int = 90) -> list[dict]:
        """
        Runs an Apify actor and waits for results.
        Returns list of result items, or empty list on failure.
        """
        # ── SAFETY GATE ──────────────────────────────────────────────────────
        guard("Apify TikTok scraper", COST_ESTIMATES["apify_tiktok_hashtag"])
        # ─────────────────────────────────────────────────────────────────────

        if not self.token:
            logger.warning("No Apify token — skipping scrape")
            return []

        try:
            # Start actor run
            url = f"{self.BASE_URL}/acts/{actor_id}/runs?token={self.token}"
            payload = json.dumps(input_data).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                run_data = json.loads(resp.read())

            run_id = run_data.get("data", {}).get("id")
            if not run_id:
                logger.warning(f"No run ID returned for actor {actor_id}")
                return []

            # Poll for completion
            start = time.time()
            while time.time() - start < poll_timeout:
                time.sleep(8)
                status_url = f"{self.BASE_URL}/actor-runs/{run_id}?token={self.token}"
                with urllib.request.urlopen(status_url, timeout=15) as resp:
                    status = json.loads(resp.read())

                run_status = status.get("data", {}).get("status", "")
                if run_status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                    break

            if run_status != "SUCCEEDED":
                logger.warning(f"Actor run {run_id} ended with status: {run_status}")
                return []

            # Fetch results
            items_url = f"{self.BASE_URL}/actor-runs/{run_id}/dataset/items?token={self.token}&limit=500"
            with urllib.request.urlopen(items_url, timeout=30) as resp:
                items = json.loads(resp.read())

            return items if isinstance(items, list) else []

        except Exception as e:
            logger.error(f"Apify error for {actor_id}: {e}")
            return []


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

        # Detect sponsorship
        sponsored_tags = {"ad", "sponsored", "gifted", "partner", "collab", "paid"}
        is_sponsored   = bool(sponsored_tags & set(hashtags))

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


# ─── DISCOVERY SCRAPER ────────────────────────────────────────────────────────

import re   # needed inside the module for hashtag extraction in parse_tiktok_video

class DiscoveryScraper:
    """
    Main discovery engine.
    Runs hashtag scrapes and creator account scrapes via Apify.
    """

    TIKTOK_ACTOR = "clockworks~free-tiktok-scraper"

    def __init__(self, apify_token: str = None):
        self.token  = apify_token or os.getenv("APIFY_TOKEN", "")
        self.client = ApifyClient(self.token)
        self.seven_days_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    def scrape_hashtag(self, hashtag: str,
                       max_videos: int = 200) -> list[VideoSignal]:
        """Scrapes a single TikTok hashtag for recent videos."""
        logger.info(f"    Scraping #{hashtag} (max {max_videos} videos)")

        raw_items = self.client.run_actor(
            self.TIKTOK_ACTOR,
            {
                "hashtags": [hashtag],
                "resultsPerPage": max_videos,
                "maxPostsPerQuery": max_videos,
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
            }
        )

        videos = []
        for item in raw_items:
            v = parse_tiktok_video(item, source_hashtag=hashtag)
            if v:
                # Only keep videos from last 7 days
                if v.posted_date >= self.seven_days_ago:
                    videos.append(v)

        logger.info(f"    → {len(videos)} recent videos from #{hashtag}")
        time.sleep(3)   # Rate limit between hashtag calls
        return videos

    def scrape_creator(self, creator: dict,
                       max_videos: int = 50) -> list[VideoSignal]:
        """Scrapes recent videos from a specific creator account."""
        handle = creator["handle"]
        logger.info(f"    Scraping @{handle} (max {max_videos} videos)")

        raw_items = self.client.run_actor(
            self.TIKTOK_ACTOR,
            {
                "profiles": [handle],
                "resultsPerPage": max_videos,
                "maxPostsPerQuery": max_videos,
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
            }
        )

        videos = []
        for item in raw_items:
            v = parse_tiktok_video(item)
            if v:
                # Override follower count with our registry data (more reliable)
                v.follower_count = creator.get("followers", v.follower_count)
                if v.posted_date >= self.seven_days_ago:
                    videos.append(v)

        logger.info(f"    → {len(videos)} recent videos from @{handle}")
        time.sleep(3)
        return videos

    def run_hashtag_discovery(self, run_devices: bool = False,
                               run_makeup: bool = False) -> list[VideoSignal]:
        """Runs all hashtag scrapes."""
        all_videos = []
        hashtags   = HASHTAGS_TIER1 + HASHTAGS_TIER2
        if run_devices: hashtags += HASHTAGS_DEVICES
        if run_makeup:  hashtags += HASHTAGS_MAKEUP

        logger.info(f"\n  Hashtag discovery: {len(hashtags)} hashtags")
        for ht in hashtags:
            videos = self.scrape_hashtag(ht, max_videos=200)
            all_videos.extend(videos)

        logger.info(f"  Total from hashtags: {len(all_videos)} videos")
        return all_videos

    def run_creator_discovery(self) -> list[VideoSignal]:
        """Runs all creator account scrapes."""
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
        Runs the complete discovery pipeline.
        Returns deduplicated list of VideoSignal objects from last 7 days.
        In TEST_MODE returns empty list immediately — pipeline will use test data.
        """
        if is_test_mode():
            logger.info("  TEST MODE — skipping live discovery, pipeline will use test data")
            return []

        logger.info("\n" + "="*60)
        logger.info("  TRENDBOARD — Skincare Discovery")
        logger.info("="*60)

        hashtag_videos = self.run_hashtag_discovery(run_devices, run_makeup)
        creator_videos = self.run_creator_discovery()

        # Combine and deduplicate by video_id
        all_videos  = hashtag_videos + creator_videos
        seen_ids    = set()
        unique      = []
        for v in all_videos:
            if v.video_id not in seen_ids:
                seen_ids.add(v.video_id)
                unique.append(v)

        logger.info(f"\n  Total unique videos: {len(unique)}")
        logger.info(f"  Date filter: {self.seven_days_ago} → today")

        return unique
