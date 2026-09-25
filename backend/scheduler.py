"""
backend/scheduler.py
====================
APScheduler-based background refresh for EV odds.

Public API:
  start_scheduler()              → starts background job, returns scheduler
  stop_scheduler()               → shuts down scheduler
  refresh_sport(sport, force)    → fetches + analyzes odds for one sport, returns result dict
  get_cached_result(sport)       → returns last analyzed result from memory
  get_all_status()               → returns status dict for all sports
  _get_client()                  → returns the OddsAPIClient singleton
"""
from __future__ import annotations
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
except Exception as _sched_import_err:
    BackgroundScheduler = None
    CronTrigger = None

from config import Config

log = logging.getLogger(__name__)

# ── In-memory result cache ────────────────────────────────────────
_results: dict[str, dict] = {}   # sport_key → analyzed result
_scheduler: Optional[BackgroundScheduler] = None


# ── Public API ────────────────────────────────────────────────────

def _get_client():
    from backend.api_client import client
    return client


def refresh_sport(sport_key: str, force: bool = False) -> Optional[dict]:
    """
    Fetch fresh odds + run EV analysis for one sport.
    Stores result in _results[sport_key] and on disk.
    Returns the result dict or None on error.
    """
    from backend.api_client import client
    from backend.devig import find_ev_bets, build_parlays

    log.info("Refreshing %s (force=%s)", sport_key, force)

    try:
        odds_list = client.get_odds(sport_key)
        if not odds_list:
            log.warning("No odds returned for %s", sport_key)
            # Return empty but valid result
            result = _make_result(sport_key, [], [])
            _results[sport_key] = result
            return result

        # Run EV analysis
        all_bets = []
        for game in odds_list:
            bets = find_ev_bets(
                game,
                book_a_key=Config.BOOK_A,
                book_b_key=Config.BOOK_B,
                min_ev=0.0,
                ev_grades=Config.EV_GRADES,
            )
            all_bets.extend(bets)

        # Sort by EV
        all_bets.sort(key=lambda b: b["ev_pct"], reverse=True)
        for i, b in enumerate(all_bets, 1):
            b["rank"] = i

        # Build parlays
        parlays = build_parlays(all_bets, n_legs=3, top_n=5)

        result = _make_result(sport_key, all_bets, parlays)
        _results[sport_key] = result

        # Persist to disk
        out_path = os.path.join(Config.DATA_DIR, f"{sport_key}_ev_results.json")
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        log.info("Refresh complete for %s: %d EV bets, %d parlays", sport_key, len(all_bets), len(parlays))
        return result

    except Exception as e:
        log.exception("Error refreshing %s: %s", sport_key, e)
        return None


def get_cached_result(sport_key: str) -> Optional[dict]:
    """Return last in-memory result, or try to load from disk."""
    if sport_key in _results:
        return _results[sport_key]

    # Try disk
    disk_path = os.path.join(Config.DATA_DIR, f"{sport_key}_ev_results.json")
    if os.path.exists(disk_path):
        try:
            with open(disk_path, "r", encoding="utf-8") as f:
                result = json.load(f)
            _results[sport_key] = result
            return result
        except (json.JSONDecodeError, OSError):
            pass
    return None


def get_all_status() -> dict:
    """Return scheduler status + per-sport cache info."""
    from backend.api_client import client

    sports_status = {}
    for sport_key in Config.SPORTS:
        cache_info = client.get_cache_info(sport_key)
        result = get_cached_result(sport_key)
        meta = result.get("meta", {}) if result else {}
        sports_status[sport_key] = {
            "label":       Config.SPORTS[sport_key]["label"],
            "cache_info":  cache_info,
            "analyzed_at": meta.get("analyzed_at"),
            "total_bets":  meta.get("total_bets", 0),
        }

    return {
        "scheduler_running": _scheduler is not None and _scheduler.running,
        "refresh_cron":      Config.REFRESH_CRON,
        "demo_mode":         Config.is_demo_mode(),
        "sports":            sports_status,
    }


# ── Scheduler lifecycle ───────────────────────────────────────────

def _refresh_all():
    """Refresh all configured sports — called by cron."""
    log.info("Scheduled refresh: refreshing %d sports", len(Config.SPORTS))
    for sport_key in Config.SPORTS:
        refresh_sport(sport_key, force=True)


def start_scheduler() -> Optional[BackgroundScheduler]:
    global _scheduler

    if BackgroundScheduler is None:
        log.warning("APScheduler is not installed or available. Background scheduler disabled.")
        return None

    if _scheduler and _scheduler.running:
        log.warning("Scheduler already running")
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")

    # Parse cron expression
    try:
        parts = Config.REFRESH_CRON.split()
        if len(parts) == 5:
            trigger = CronTrigger(
                minute=parts[0], hour=parts[1], day=parts[2],
                month=parts[3], day_of_week=parts[4]
            )
        else:
            raise ValueError(f"Invalid cron: {Config.REFRESH_CRON}")
    except Exception as e:
        log.warning("Could not parse REFRESH_CRON '%s': %s — using daily 9 AM", Config.REFRESH_CRON, e)
        trigger = CronTrigger(hour=9, minute=0)

    _scheduler.add_job(_refresh_all, trigger=trigger, id="daily_refresh", replace_existing=True)
    _scheduler.start()
    log.info("Scheduler started. Next refresh: %s", Config.REFRESH_CRON)

    # Run initial refresh on startup (non-blocking)
    import threading
    threading.Thread(target=_refresh_all, daemon=True).start()

    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")
    _scheduler = None


# ── Helpers ───────────────────────────────────────────────────────

def _make_result(sport_key: str, bets: list, parlays: list) -> dict:
    return {
        "sport_key": sport_key,
        "bets":      bets,
        "parlays":   parlays,
        "meta": {
            "sport_key":   sport_key,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "total_bets":  len(bets),
            "total_games": len({b["game"] for b in bets}),
            "demo_mode":   Config.is_demo_mode(),
        },
    }
