"""
scratch/reset_aug1_picks.py
============================
Utility to reset all bets logged on or after Aug 1, 2026 back to 'pending'
so they can be re-graded fresh. Use with caution.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config

BET_LOG_PATH = os.path.join(Config.DATA_DIR, "bet_log.json")
CUTOFF_DATE  = "2026-08-01"


def main():
    if not os.path.exists(BET_LOG_PATH):
        print("No bet log found.")
        return

    with open(BET_LOG_PATH, "r", encoding="utf-8") as f:
        bets = json.load(f)

    reset_count = 0
    for b in bets:
        date = b.get("date", "")
        if date >= CUTOFF_DATE and b.get("result") in ("win", "loss"):
            b["result"]          = "pending"
            b["pnl"]             = None
            b["clv_pct"]         = None
            b["clv_display"]     = None
            b["clv_confirmed"]   = None
            b["variance_type"]   = "pending"
            b["variance_label"]  = "Pending"
            b["variance_detail"] = "Reset by reset_aug1_picks.py"
            reset_count += 1

    with open(BET_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(bets, f, indent=2)

    print(f"Reset {reset_count} bets on or after {CUTOFF_DATE} back to pending.")


if __name__ == "__main__":
    confirm = input(f"This will reset all bets on/after {CUTOFF_DATE} to pending. Continue? (yes/no): ")
    if confirm.strip().lower() == "yes":
        main()
    else:
        print("Aborted.")
