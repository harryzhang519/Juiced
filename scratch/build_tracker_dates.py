"""
scratch/build_tracker_dates.py
===============================
Utility to backfill missing 'date' fields in bet_log.json
from 'logged_at' timestamps, and ensure all bets have consistent fields.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config

BET_LOG_PATH = os.path.join(Config.DATA_DIR, "bet_log.json")


def load():
    if not os.path.exists(BET_LOG_PATH):
        return []
    with open(BET_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save(bets):
    with open(BET_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(bets, f, indent=2)


def backfill_dates(bets):
    """Fill in missing 'date' from 'logged_at' timestamp."""
    fixed = 0
    for b in bets:
        if not b.get("date") and b.get("logged_at"):
            b["date"] = b["logged_at"][:10]
            fixed += 1
    return fixed


def normalize_fields(bets):
    """Ensure all required fields exist on each bet."""
    required = {
        "id": None,
        "logged_at": None,
        "date": None,
        "game": "",
        "sport": "MLB",
        "market": "Moneyline",
        "selection": "",
        "target_book": "DraftKings",
        "benchmark_book": "FanDuel",
        "offered_odds": None,
        "fair_odds": None,
        "ev_pct": 0.0,
        "ev_pct_display": "+0.00%",
        "stake": 1.0,
        "closing_odds": None,
        "result": "pending",
        "recap": "",
        "clv_pct": None,
        "clv_display": None,
        "clv_confirmed": None,
        "pnl": None,
        "variance_type": None,
        "variance_label": None,
        "variance_detail": None,
    }
    added = 0
    for b in bets:
        for field, default in required.items():
            if field not in b:
                b[field] = default
                added += 1
    return added


def main():
    print(f"Loading {BET_LOG_PATH}...")
    bets = load()
    print(f"Loaded {len(bets)} bets")

    fixed = backfill_dates(bets)
    print(f"Backfilled dates: {fixed}")

    added = normalize_fields(bets)
    print(f"Normalized missing fields: {added}")

    save(bets)
    print("Done — saved.")


if __name__ == "__main__":
    main()
