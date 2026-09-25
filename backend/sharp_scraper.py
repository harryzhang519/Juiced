"""
backend/sharp_scraper.py
========================
Public betting data and line movement scraping.

Since Action Network requires authentication, this module provides:
  - get_public_betting_data(sport_key) → list of game betting split dicts
  - get_line_movement(sport_key, current_odds) → list of line movement dicts

In demo/no-key mode these return empty lists gracefully.
The line movement data is derived from comparing cached opening odds
vs current odds from the API.
"""
from __future__ import annotations
import json
import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config

log = logging.getLogger(__name__)


def get_public_betting_data(sport_key: str) -> list[dict]:
    """
    Attempt to retrieve public betting split percentages.
    Returns empty list if unavailable (Action Network requires auth).
    
    Returns list of dicts:
      {game, away_team, home_team, bet_pct_away, bet_pct_home, money_pct_away, money_pct_home}
    """
    # In production you would scrape Action Network or purchase their API.
    # Without credentials this gracefully returns empty, and the sharp signals
    # route falls back to odds-derived data.
    return []


def get_line_movement(sport_key: str, current_odds: list[dict]) -> list[dict]:
    """
    Compare current odds vs previously cached odds to derive line movement.

    Returns list of dicts:
      {game, selection, line_open, line_current, move}
    """
    if not current_odds:
        return []

    movements = []

    # Load a previous snapshot if it exists (saved on each refresh)
    snapshot_path = _snapshot_path(sport_key)
    prev_odds_map = _load_snapshot(snapshot_path)

    for game in current_odds:
        game_id  = game.get("id", "")
        away     = game.get("away_team", "")
        home     = game.get("home_team", "")
        matchup  = f"{away} @ {home}"

        for bm in game.get("bookmakers", []):
            bm_key = bm.get("key", "")
            for mkt in bm.get("markets", []):
                mkt_key = mkt.get("key", "")
                for outcome in mkt.get("outcomes", []):
                    sel  = outcome.get("name", "")
                    curr = outcome.get("price") or outcome.get("point")

                    prev_key = f"{game_id}:{bm_key}:{mkt_key}:{sel}"
                    prev = prev_odds_map.get(prev_key)

                    if curr is not None:
                        movements.append({
                            "game":        matchup,
                            "selection":   sel,
                            "bookmaker":   bm_key,
                            "market":      mkt_key,
                            "line_open":   prev if prev is not None else curr,
                            "line_current": curr,
                            "move":        round(float(curr) - float(prev), 2) if prev is not None else 0.0,
                        })

    # Save current as snapshot for next comparison
    _save_snapshot(snapshot_path, current_odds)

    return movements


# ── Snapshot helpers ──────────────────────────────────────────────

def _snapshot_path(sport_key: str) -> str:
    return os.path.join(Config.DATA_DIR, f"{sport_key}_snapshot.json")


def _load_snapshot(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Flatten to {game_id:bm:mkt:sel → price}
        flat = {}
        for game in raw:
            gid = game.get("id", "")
            for bm in game.get("bookmakers", []):
                bk = bm.get("key", "")
                for mkt in bm.get("markets", []):
                    mk = mkt.get("key", "")
                    for outcome in mkt.get("outcomes", []):
                        sel = outcome.get("name", "")
                        val = outcome.get("price") or outcome.get("point")
                        flat[f"{gid}:{bk}:{mk}:{sel}"] = val
        return flat
    except (json.JSONDecodeError, OSError, KeyError):
        return {}


def _save_snapshot(path: str, odds: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(odds, f)
    except OSError as e:
        log.warning("Could not save odds snapshot to %s: %s", path, e)
