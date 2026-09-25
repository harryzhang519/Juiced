"""
scratch/export_roi_for_llm.py
==============================
Export bet history to files suitable for LLM analysis.

Outputs:
  data/export_bets_history.csv      — flat CSV of all settled bets
  data/export_full_bet_history.json — full JSON dump
  data/llm_roi_history_prompt.md    — pre-formatted LLM prompt
"""
import csv
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config

BET_LOG_PATH        = os.path.join(Config.DATA_DIR, "bet_log.json")
PIKKIT_PATH         = os.path.join(Config.DATA_DIR, "pikkit_bets.json")
EXPORT_CSV_PATH     = os.path.join(Config.DATA_DIR, "export_bets_history.csv")
EXPORT_JSON_PATH    = os.path.join(Config.DATA_DIR, "export_full_bet_history.json")
EXPORT_PROMPT_MD_PATH = os.path.join(Config.DATA_DIR, "llm_roi_history_prompt.md")


def load_all_bets() -> list[dict]:
    """Load bets from both bet_log.json and pikkit_bets.json."""
    bets = []
    for path in [BET_LOG_PATH, PIKKIT_PATH]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    bets.extend(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
    return bets


def export_csv(bets: list[dict]) -> None:
    fieldnames = [
        "id", "date", "sport", "game", "selection", "market",
        "sportsbook", "odds", "stake", "payout", "result", "pnl",
        "ev_pct", "clv_pct", "offered_odds", "fair_odds", "closing_odds",
    ]
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    with open(EXPORT_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(bets)


def export_json(bets: list[dict]) -> None:
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    with open(EXPORT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(bets, f, indent=2)


def export_prompt_md(bets: list[dict]) -> None:
    """Generate a pre-formatted markdown prompt for LLM analysis."""
    settled  = [b for b in bets if b.get("result") in ("win", "loss", "push")]
    wins     = [b for b in settled if b["result"] == "win"]
    losses   = [b for b in settled if b["result"] == "loss"]
    total_pnl = sum(b.get("pnl") or 0 for b in settled)
    win_rate  = len(wins) / len(settled) * 100 if settled else 0

    lines = [
        "# Betting ROI History — LLM Analysis Prompt",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Summary",
        f"- Total settled bets: {len(settled)}",
        f"- Record: {len(wins)}W-{len(losses)}L",
        f"- Win rate: {win_rate:.1f}%",
        f"- Net P&L: ${total_pnl:+.2f}",
        "",
        "## Instruction",
        "Analyze the following bet history. Identify:",
        "1. Which markets/sports/sportsbooks are most profitable",
        "2. Patterns in winning vs losing bets",
        "3. Whether EV% at entry correlates with actual outcomes",
        "4. Specific recommendations to improve ROI",
        "",
        "## Bet History (last 100 settled)",
        "",
        "| Date | Sport | Selection | Market | Odds | Stake | P&L | Result | EV% |",
        "|------|-------|-----------|--------|------|-------|-----|--------|-----|",
    ]

    for b in sorted(settled, key=lambda x: x.get("date", ""), reverse=True)[:100]:
        ev = f"{b['ev_pct']*100:+.2f}%" if b.get("ev_pct") is not None else "—"
        pnl = f"${b['pnl']:+.2f}" if b.get("pnl") is not None else "—"
        sel = (b.get("selection") or "")[:40]
        lines.append(
            f"| {b.get('date','')[:10]} | {b.get('sport','')} | {sel} "
            f"| {b.get('market','')} | {b.get('offered_odds') or b.get('odds','')} "
            f"| ${b.get('stake',0):.2f} | {pnl} | {b.get('result','')} | {ev} |"
        )

    os.makedirs(Config.DATA_DIR, exist_ok=True)
    with open(EXPORT_PROMPT_MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    print("Loading bets...")
    bets = load_all_bets()
    print(f"Found {len(bets)} total bets")

    export_csv(bets)
    print(f"CSV exported → {EXPORT_CSV_PATH}")

    export_json(bets)
    print(f"JSON exported → {EXPORT_JSON_PATH}")

    export_prompt_md(bets)
    print(f"LLM prompt → {EXPORT_PROMPT_MD_PATH}")


if __name__ == "__main__":
    main()
