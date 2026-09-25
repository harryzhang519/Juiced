"""
backend/db.py
=============
Database abstraction layer for EV Edge.
Supports:
  1. Supabase REST API (SUPABASE_URL + SUPABASE_KEY) — fast, serverless-native, no psycopg2 binary needed
  2. PostgreSQL (DATABASE_URL) — standard Postgres connection
  3. Local JSON fallback (data/pikkit_bets.json) — for local development and offline use
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

LOCAL_PATH = os.path.join(Config.DATA_DIR, "pikkit_bets.json")


# ── Mode Detection ──────────────────────────────────────────────────

def get_db_mode() -> str:
    """Returns 'supabase_rest', 'postgres', or 'local_json'."""
    url = (Config.SUPABASE_URL or "").strip()
    key = (Config.SUPABASE_KEY or "").strip()
    if url and key and "your-project" not in url and not url.startswith("https://xxx"):
        return "supabase_rest"
    if Config.DATABASE_URL and "your-db" not in Config.DATABASE_URL:
        return "postgres"
    return "local_json"


# ── Local JSON Helpers ──────────────────────────────────────────────

def _load_local() -> list[dict]:
    if not os.path.exists(LOCAL_PATH):
        return []
    try:
        with open(LOCAL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error("Failed to load local JSON bets: %s", e)
        return []


def _save_local(bets: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(LOCAL_PATH), exist_ok=True)
        with open(LOCAL_PATH, "w", encoding="utf-8") as f:
            json.dump(bets, f, indent=2)
    except Exception as e:
        log.warning("Failed to save local JSON bets (read-only filesystem on serverless): %s", e)


# ── Supabase REST Helpers ───────────────────────────────────────────

def _supabase_headers() -> dict:
    key = Config.SUPABASE_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _supabase_url(endpoint: str = "pikkit_bets") -> str:
    base = Config.SUPABASE_URL.rstrip("/")
    return f"{base}/rest/v1/{endpoint}"


def _load_supabase() -> list[dict]:
    import requests
    try:
        url = f"{_supabase_url()}?select=*&order=date.asc,logged_at.asc"
        resp = requests.get(url, headers=_supabase_headers(), timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                # First time setup: auto-seed from local data if table is empty
                log.info("Supabase table pikkit_bets is empty. Auto-seeding from local bets...")
                local_bets = _load_local()
                if local_bets:
                    _seed_supabase(local_bets)
                    return local_bets
            return data
        log.error("Supabase load error (%s): %s", resp.status_code, resp.text)
    except Exception as e:
        log.error("Supabase request failed: %s — falling back to local data", e)
    # Fallback to local on error
    return _load_local()


def _seed_supabase(bets: list[dict]) -> None:
    import requests
    try:
        url = _supabase_url()
        headers = _supabase_headers()
        # Insert in batches of 50
        for i in range(0, len(bets), 50):
            batch = bets[i:i+50]
            r = requests.post(url, headers=headers, json=batch, timeout=15)
            if r.status_code not in (200, 201):
                log.warning("Supabase seed batch %d failed: %s", i, r.text)
    except Exception as e:
        log.error("Supabase seeding failed: %s", e)


def _insert_supabase(bet: dict) -> dict:
    import requests
    try:
        url = _supabase_url()
        headers = _supabase_headers()
        r = requests.post(url, headers=headers, json=bet, timeout=8)
        if r.status_code in (200, 201):
            res = r.json()
            return res[0] if isinstance(res, list) and res else bet
        log.error("Supabase insert error (%s): %s", r.status_code, r.text)
    except Exception as e:
        log.error("Supabase insert request failed: %s", e)
    return bet


def _update_supabase(bet_id: str, updates: dict) -> Optional[dict]:
    import requests
    try:
        url = f"{_supabase_url()}?id=eq.{bet_id}"
        headers = _supabase_headers()
        r = requests.patch(url, headers=headers, json=updates, timeout=8)
        if r.status_code in (200, 204):
            res = r.json() if r.text else [updates]
            return res[0] if isinstance(res, list) and res else updates
        log.error("Supabase update error (%s): %s", r.status_code, r.text)
    except Exception as e:
        log.error("Supabase update request failed: %s", e)
    return None


def _delete_supabase(bet_id: str) -> bool:
    import requests
    try:
        url = f"{_supabase_url()}?id=eq.{bet_id}"
        headers = _supabase_headers()
        r = requests.delete(url, headers=headers, timeout=8)
        return r.status_code in (200, 204)
    except Exception as e:
        log.error("Supabase delete request failed: %s", e)
        return False


# ── Unified Public Interface ────────────────────────────────────────

def get_all_bets() -> list[dict]:
    """Retrieve all stored bets across the configured storage backend."""
    mode = get_db_mode()
    if mode == "supabase_rest":
        return _load_supabase()
    # Default to local JSON
    return _load_local()


def add_bet(bet: dict) -> dict:
    """Insert a new bet into the active storage backend."""
    mode = get_db_mode()
    if mode == "supabase_rest":
        return _insert_supabase(bet)

    # Local JSON fallback
    bets = _load_local()
    bets.append(bet)
    _save_local(bets)
    return bet


def update_bet(bet_id: str, updates: dict) -> Optional[dict]:
    """Update fields on an existing bet."""
    mode = get_db_mode()
    if mode == "supabase_rest":
        return _update_supabase(bet_id, updates)

    # Local JSON fallback
    bets = _load_local()
    for i, b in enumerate(bets):
        if b.get("id") == bet_id:
            bets[i].update(updates)
            _save_local(bets)
            return bets[i]
    return None


def delete_bet(bet_id: str) -> bool:
    """Delete a bet by ID."""
    mode = get_db_mode()
    if mode == "supabase_rest":
        return _delete_supabase(bet_id)

    # Local JSON fallback
    bets = _load_local()
    before = len(bets)
    bets = [b for b in bets if b.get("id") != bet_id]
    if len(bets) < before:
        _save_local(bets)
        return True
    return False
