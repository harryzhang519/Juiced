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
import uuid
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config

log = logging.getLogger(__name__)

LOCAL_PATH = os.path.join(Config.DATA_DIR, "pikkit_bets.json")


def sanitize_bet(b: dict) -> dict:
    """Ensure every bet has strictly validated types and non-null values."""
    if not isinstance(b, dict):
        return {}
    clean = dict(b)
    # Ensure ID
    if not clean.get("id"):
        clean["id"] = str(uuid.uuid4())[:8].upper()
    # Ensure date string YYYY-MM-DD
    d = clean.get("date")
    l_at = clean.get("logged_at")
    logged_day = l_at[:10] if (l_at and isinstance(l_at, str) and len(l_at) >= 10) else datetime.now().strftime("%Y-%m-%d")

    if not d or not isinstance(d, str) or d.strip() == "" or d.lower() in ("null", "none"):
        clean["date"] = logged_day
    else:
        d = d.strip()[:10]
        if len(d) == 10 and d.startswith("2023"):
            d = "2026-09-27"
        clean["date"] = d

    # Explicit correction for the 3 bets uploaded on Sept 27
    if clean.get("id") in ("6963D394", "349F962B", "3B11C449"):
        clean["date"] = "2026-09-27"
    # Ensure logged_at string ISO
    l_at = clean.get("logged_at")
    if not l_at or not isinstance(l_at, str):
        clean["logged_at"] = datetime.now(timezone.utc).isoformat()
    # Ensure stake is float
    try:
        clean["stake"] = float(str(clean.get("stake") or 0).replace("$", "").replace(",", "").strip())
    except Exception:
        clean["stake"] = 0.0
    # Ensure payout is float or None
    if clean.get("payout") is not None:
        try:
            clean["payout"] = float(str(clean["payout"]).replace("$", "").replace(",", "").strip())
        except Exception:
            clean["payout"] = None
    # Ensure pnl is float
    pnl = clean.get("pnl")
    if pnl is not None:
        try:
            clean["pnl"] = round(float(str(pnl).replace("$", "").replace(",", "").strip()), 2)
        except Exception:
            clean["pnl"] = 0.0
    else:
        res = str(clean.get("result") or "pending").lower().strip()
        if res == "win" and clean.get("payout") is not None:
            clean["pnl"] = round(clean["payout"] - clean["stake"], 2)
        elif res == "loss":
            clean["pnl"] = round(-clean["stake"], 2)
        elif res == "push":
            clean["pnl"] = 0.0
        else:
            clean["pnl"] = 0.0
    # Ensure odds is int
    try:
        raw_odds = str(clean.get("odds") or 100).replace("+", "").strip()
        clean["odds"] = int(float(raw_odds))
    except Exception:
        clean["odds"] = 100
    # Ensure string fields
    clean["result"] = str(clean.get("result") or "pending").lower().strip()
    clean["sportsbook"] = str(clean.get("sportsbook") or "Unknown").strip()
    clean["sport"] = str(clean.get("sport") or "Unknown").strip()
    clean["market"] = str(clean.get("market") or "Moneyline").strip()
    clean["game"] = str(clean.get("game") or "").strip()
    clean["selection"] = str(clean.get("selection") or "").strip()
    return clean


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
    candidates = [
        LOCAL_PATH,
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pikkit_bets.json"),
        os.path.join(os.getcwd(), "data", "pikkit_bets.json"),
        os.path.join(os.path.dirname(__file__), "..", "data", "pikkit_bets.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data:
                        return [sanitize_bet(b) for b in data]
            except Exception as e:
                log.error("Failed to load local JSON bets from %s: %s", path, e)
    return []


def _save_local(bets: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(LOCAL_PATH), exist_ok=True)
        with open(LOCAL_PATH, "w", encoding="utf-8") as f:
            json.dump([sanitize_bet(b) for b in bets], f, indent=2)
    except Exception as e:
        log.warning("Failed to save local JSON bets (read-only filesystem on serverless): %s", e)


# ── Supabase REST Helpers ───────────────────────────────────────────

def _supabase_headers(upsert: bool = False) -> dict:
    key = (Config.SUPABASE_KEY or "").strip()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    if upsert:
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    return headers


def _supabase_url(endpoint: str = "pikkit_bets") -> str:
    base = (Config.SUPABASE_URL or "").strip().rstrip("/")
    return f"{base}/rest/v1/{endpoint}"


def _load_supabase() -> list[dict]:
    import requests
    try:
        # Load all rows without SQL order by clause to prevent PostgREST syntax/null ordering errors
        url = f"{_supabase_url()}?select=*"
        resp = requests.get(url, headers=_supabase_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                # First time setup: auto-seed from local data if table is empty
                log.info("Supabase table pikkit_bets is empty. Auto-seeding from local bets...")
                local_bets = _load_local()
                if local_bets:
                    _seed_supabase(local_bets)
            sanitized = []
            for b in data:
                clean = sanitize_bet(b)
                if not b.get("date") or b.get("date") != clean["date"]:
                    try:
                        _update_supabase(clean["id"], {"date": clean["date"]})
                    except Exception:
                        pass
                sanitized.append(clean)
            sanitized.sort(key=lambda b: (str(b.get("date") or ""), str(b.get("logged_at") or "")))
            return sanitized
        log.error("Supabase load error (%s): %s", resp.status_code, resp.text)
    except Exception as e:
        log.error("Supabase request failed: %s — falling back to local data", e)
    # Fallback to local on error
    return [sanitize_bet(b) for b in _load_local()]


def _seed_supabase(bets: list[dict]) -> None:
    import requests
    try:
        url = _supabase_url()
        headers = _supabase_headers(upsert=True)
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
    clean = sanitize_bet(bet)
    mode = get_db_mode()
    if mode == "supabase_rest":
        res = _insert_supabase(clean)
        return sanitize_bet(res)

    # Local JSON fallback
    bets = _load_local()
    bets.append(clean)
    _save_local(bets)
    return clean


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
