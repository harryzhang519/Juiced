"""
backend/api_client.py
=====================
The-Odds-API v4 wrapper with file-based caching and demo-mode fallback.

Public singleton: `client`
Key methods:
  client.get_available_sports()         → list of sport dicts
  client.get_odds(sport_key)            → raw odds list from API
  client.get_scores(sport_key, days_from) → completed scores
  client.get_cache_info(sport_key)      → {cached_at, is_fresh, file}
"""
from __future__ import annotations
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config

log = logging.getLogger(__name__)

HEADERS = {"Accept": "application/json"}
TIMEOUT = 15  # seconds


class OddsAPIClient:
    """Thin wrapper around The-Odds-API v4 with file-based caching."""

    def __init__(self):
        self.base = Config.ODDS_API_BASE
        self.key  = Config.ODDS_API_KEY

    # ── Sports ───────────────────────────────────────────────────

    def get_available_sports(self) -> list[dict]:
        """Return the list of tracked sports from config."""
        return [
            {"key": k, "label": v["label"], "emoji": v["emoji"]}
            for k, v in Config.SPORTS.items()
        ]

    # ── Odds ─────────────────────────────────────────────────────

    def get_odds(
        self,
        sport_key: str,
        markets: Optional[list[str]] = None,
        bookmakers: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Fetch odds for a sport from The-Odds-API.
        Falls back to cache file if in demo mode or request fails.
        """
        if markets is None:
            markets = Config.MARKETS
        if bookmakers is None:
            bookmakers = [Config.BOOK_A, Config.BOOK_B]

        cache_path = self._cache_path(sport_key)

        if Config.is_demo_mode():
            log.debug("Demo mode — reading from cache: %s", cache_path)
            return self._read_cache(cache_path) or []

        url = f"{self.base}/sports/{sport_key}/odds"
        params = {
            "apiKey":      self.key,
            "regions":     "us",
            "markets":     ",".join(markets),
            "bookmakers":  ",".join(bookmakers),
            "oddsFormat":  "american",
        }

        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            remaining = resp.headers.get("x-requests-remaining", "?")
            log.info("Fetched %d games for %s (quota remaining: %s)", len(data), sport_key, remaining)
            self._write_cache(cache_path, data)
            return data
        except requests.RequestException as e:
            log.warning("API request failed for %s: %s — using cache", sport_key, e)
            return self._read_cache(cache_path) or []

    # ── Scores ────────────────────────────────────────────────────

    def get_scores(self, sport_key: str, days_from: int = 3) -> list[dict]:
        """Fetch recent completed scores for auto-resolution."""
        if Config.is_demo_mode():
            return []

        url = f"{self.base}/sports/{sport_key}/scores"
        params = {
            "apiKey":    self.key,
            "daysFrom":  days_from,
        }
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            log.warning("Scores fetch failed for %s: %s", sport_key, e)
            return []

    # ── Props ─────────────────────────────────────────────────────

    def get_event_props(self, sport_key: str, event_id: str, markets: list[str]) -> dict:
        """Fetch player prop markets for a specific event."""
        if Config.is_demo_mode():
            return {}

        url = f"{self.base}/sports/{sport_key}/events/{event_id}/odds"
        params = {
            "apiKey":     self.key,
            "regions":    "us",
            "markets":    ",".join(markets),
            "oddsFormat": "american",
        }
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            log.warning("Props fetch failed for event %s: %s", event_id, e)
            return {}

    # ── Cache ─────────────────────────────────────────────────────

    def get_cache_info(self, sport_key: str) -> dict:
        cache_path = self._cache_path(sport_key)
        if not os.path.exists(cache_path):
            return {"file": cache_path, "cached_at": None, "is_fresh": False, "age_hours": None}

        mtime = os.path.getmtime(cache_path)
        cached_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
        is_fresh  = age_hours < Config.CACHE_TTL_HOURS

        return {
            "file":      cache_path,
            "cached_at": cached_at.isoformat(),
            "is_fresh":  is_fresh,
            "age_hours": round(age_hours, 2),
        }

    def _cache_path(self, sport_key: str) -> str:
        return os.path.join(Config.DATA_DIR, f"{sport_key}_odds.json")

    def _read_cache(self, path: str) -> Optional[list]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Cache read error %s: %s", path, e)
            return None

    def _write_cache(self, path: str, data: list) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            log.warning("Cache write error %s: %s", path, e)


# ── Singleton ────────────────────────────────────────────────────
client = OddsAPIClient()
