"""
trendboard.fyi — Safety Gate
==============================
Central module that controls whether real paid API calls are allowed.

TEST_MODE=true  → All paid calls are blocked. Mock data is used instead.
TEST_MODE=false → Live calls are allowed, but ONLY after explicit approval
                  via LIVE_APPROVED=true in your .env.

Rules:
  - Never set TEST_MODE=false without Darren's approval.
  - Every paid call site imports and calls guard() before hitting the API.
  - guard() raises LiveCallBlockedError if not approved.
  - Estimated costs are logged before any live call.

Paid services and approximate costs:
  - Apify TikTok scraper:   ~$55 / full weekly run  (~15,000 videos)
  - Apify Instagram scraper: ~$10 / run
  - Reddit API:              Free (rate-limited)
  - Google Trends:           Free (rate-limited)
  - Claude API:              ~$0.05–$0.20 / 25 descriptions
  - Supabase:                Free tier (no charge until row limits hit)
"""

import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ─── COST ESTIMATES ──────────────────────────────────────────────────────────

COST_ESTIMATES = {
    "apify_tiktok_full":     55.00,
    "apify_tiktok_hashtag":   0.30,   # per hashtag @ 200 videos
    "apify_instagram_full":   10.00,
    "apify_instagram_single":  0.10,   # single hashtag @ 100 posts
    "apify_instagram_batch":   4.50,   # 19 hashtags × 100 posts batched
    "claude_descriptions":    0.15,   # per 25 products
    "reddit_api":             0.00,
    "google_trends":          0.00,
    "supabase_write":         0.00,
}


# ─── EXCEPTION ───────────────────────────────────────────────────────────────

class LiveCallBlockedError(Exception):
    """Raised when a paid API call is attempted without approval."""
    pass


# ─── CORE GATE ───────────────────────────────────────────────────────────────

def is_test_mode() -> bool:
    """Returns True if TEST_MODE is enabled (default: True for safety)."""
    val = os.getenv("TEST_MODE", "true").strip().lower()
    return val not in ("false", "0", "no", "off")


def guard(service: str, estimated_cost: float = None):
    """
    Call this before every paid API call.

    In TEST_MODE:  raises LiveCallBlockedError immediately.
    In LIVE_MODE:  checks for LIVE_APPROVED=true, logs cost warning,
                   then allows the call through.

    Args:
        service:        Human-readable name of the service being called.
        estimated_cost: Estimated USD cost for this call (optional).
    """
    cost_str = f"  Estimated cost: ${estimated_cost:.2f}" if estimated_cost is not None else ""

    if is_test_mode():
        raise LiveCallBlockedError(
            f"\n"
            f"{'='*60}\n"
            f"  🔒 LIVE CALL BLOCKED — TEST MODE IS ON\n"
            f"{'='*60}\n"
            f"  Service:  {service}\n"
            f"{cost_str}\n"
            f"\n"
            f"  To enable live calls:\n"
            f"  1. Get approval from Darren\n"
            f"  2. Set TEST_MODE=false in .env\n"
            f"  3. Set LIVE_APPROVED=true in .env\n"
            f"{'='*60}"
        )

    # LIVE MODE — check for explicit approval
    approved = os.getenv("LIVE_APPROVED", "false").strip().lower()
    if approved not in ("true", "1", "yes"):
        raise LiveCallBlockedError(
            f"\n"
            f"{'='*60}\n"
            f"  ⚠️  LIVE MODE IS ON — BUT NOT APPROVED\n"
            f"{'='*60}\n"
            f"  Service:  {service}\n"
            f"{cost_str}\n"
            f"\n"
            f"  TEST_MODE is false but LIVE_APPROVED is not set.\n"
            f"  Set LIVE_APPROVED=true in .env to confirm you want\n"
            f"  to spend real money on this run.\n"
            f"{'='*60}"
        )

    # Approved — log a clear warning and proceed
    banner = (
        f"\n"
        f"{'='*60}\n"
        f"  💳 LIVE API CALL — REAL MONEY BEING SPENT\n"
        f"{'='*60}\n"
        f"  Service:  {service}\n"
        f"{cost_str}\n"
        f"{'='*60}"
    )
    logger.warning(banner)
    print(banner)


def status() -> str:
    """Returns a human-readable status string for logging."""
    if is_test_mode():
        return "🧪 TEST MODE — no real API calls will be made"
    approved = os.getenv("LIVE_APPROVED", "false").strip().lower()
    if approved in ("true", "1", "yes"):
        return "💳 LIVE MODE — real API calls APPROVED — charges may apply"
    return "⚠️  LIVE MODE — real API calls NOT yet approved (set LIVE_APPROVED=true)"
