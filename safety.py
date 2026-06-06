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

# ─── SESSION SPEND TRACKER ───────────────────────────────────────────────────
# Accumulates estimated cost across all guard() calls in one pipeline run.
# Compared against SPEND_CAP_USD before every paid call — halts if exceeded.

_session_spend: float = 0.0

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
    In LIVE_MODE:  checks LIVE_APPROVED, enforces SPEND_CAP_USD,
                   logs cumulative cost, then allows the call through.

    Args:
        service:        Human-readable name of the service being called.
        estimated_cost: Estimated USD cost for this call (optional).
    """
    global _session_spend

    cost     = estimated_cost or 0.0
    cost_str = f"  Estimated cost: ${cost:.2f}" if estimated_cost is not None else ""

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

    # ── SPEND CAP CHECK ──────────────────────────────────────────────────────
    cap = float(os.getenv("SPEND_CAP_USD", "9999"))
    if _session_spend + cost > cap:
        raise LiveCallBlockedError(
            f"\n"
            f"{'='*60}\n"
            f"  🛑 SPEND CAP REACHED — RUN HALTED\n"
            f"{'='*60}\n"
            f"  Service:      {service}\n"
            f"  This call:    ${cost:.2f}\n"
            f"  Spent so far: ${_session_spend:.2f}\n"
            f"  Cap:          ${cap:.2f}\n"
            f"  Would reach:  ${_session_spend + cost:.2f}\n"
            f"\n"
            f"  To allow more spending, raise SPEND_CAP_USD in .env.\n"
            f"{'='*60}"
        )

    # Approved and under cap — log and proceed
    _session_spend += cost
    banner = (
        f"\n"
        f"{'='*60}\n"
        f"  💳 LIVE API CALL — REAL MONEY BEING SPENT\n"
        f"{'='*60}\n"
        f"  Service:       {service}\n"
        f"{cost_str}\n"
        f"  Session total: ${_session_spend:.2f} / ${cap:.2f} cap\n"
        f"{'='*60}"
    )
    logger.warning(banner)
    print(banner)


def status() -> str:
    """Returns a human-readable status string for logging."""
    if is_test_mode():
        return "🧪 TEST MODE — no real API calls will be made"
    approved = os.getenv("LIVE_APPROVED", "false").strip().lower()
    cap = os.getenv("SPEND_CAP_USD", "no cap")
    if approved in ("true", "1", "yes"):
        return f"💳 LIVE MODE — APPROVED — cap: ${cap}"
    return "⚠️  LIVE MODE — real API calls NOT yet approved (set LIVE_APPROVED=true)"


def get_session_spend() -> float:
    """Returns the cumulative estimated spend for this pipeline run."""
    return _session_spend
