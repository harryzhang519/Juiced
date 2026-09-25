"""
backend/sharp_engine.py
=======================
Sharp money & Reverse Line Movement (RLM) signal classifier.

Input: list of game dicts with bet%, money%, and line movement data.
Output: list of signal dicts with classification label and strength.
"""
from __future__ import annotations
from typing import Optional


# ── Signal thresholds ─────────────────────────────────────────────

# Public bets overwhelmingly on one side but money % is on the other
RLM_BET_THRESHOLD   = 60    # % of bets on the "public" side
RLM_MONEY_THRESHOLD = 50    # % of money on the "sharp" side (opposite)

# Steam: large line movement without proportionate public betting
STEAM_LINE_MOVE_THRESHOLD = 1.5   # points or price change

# Tout: public is heavily on one side AND money follows (public play)
TOUT_BET_THRESHOLD = 70
TOUT_MONEY_THRESHOLD = 65


def analyze_sharp_signals(games: list[dict]) -> list[dict]:
    """
    Analyze a list of game/selection records and classify sharp vs public action.

    Each input item should have:
      matchup      (str)   e.g. "NYY @ BOS"
      selection    (str)   e.g. "Boston Red Sox"
      bet_pct      (float) % of bets on this side
      money_pct    (float) % of money on this side
      line_open    (float|None) opening line/spread/price
      line_current (float|None) current line

    Returns list of signal dicts.
    """
    results = []

    for g in games:
        matchup      = g.get("matchup", "Unknown")
        selection    = g.get("selection", "")
        bet_pct      = float(g.get("bet_pct") or 50)
        money_pct    = float(g.get("money_pct") or 50)
        line_open    = g.get("line_open")
        line_current = g.get("line_current")

        line_move = None
        if line_open is not None and line_current is not None:
            try:
                line_move = float(line_current) - float(line_open)
            except (TypeError, ValueError):
                line_move = None

        signal_type, label, strength, description = _classify(
            bet_pct, money_pct, line_move
        )

        results.append({
            "matchup":     matchup,
            "selection":   selection,
            "bet_pct":     bet_pct,
            "money_pct":   money_pct,
            "line_open":   line_open,
            "line_current": line_current,
            "line_move":   round(line_move, 2) if line_move is not None else None,
            "signal_type": signal_type,
            "label":       label,
            "strength":    strength,       # "strong" | "moderate" | "weak"
            "description": description,
        })

    # Sort: strong first, then by RLM (most interesting)
    order = {"strong": 0, "moderate": 1, "weak": 2}
    results.sort(key=lambda x: (order.get(x["strength"], 3), x["signal_type"] != "rlm"))

    return results


def _classify(
    bet_pct: float,
    money_pct: float,
    line_move: Optional[float],
) -> tuple[str, str, str, str]:
    """Return (signal_type, label, strength, description)."""

    money_gap = money_pct - bet_pct   # positive = money > bets (sharp lean)

    # ── Reverse Line Movement ──────────────────────────────────
    # Heavy public bets on one side, but money % on the other
    if bet_pct >= RLM_BET_THRESHOLD and money_pct < (100 - RLM_MONEY_THRESHOLD):
        strength = "strong" if bet_pct >= 75 and money_pct < 35 else "moderate"
        return (
            "rlm",
            "📉 Reverse Line Movement",
            strength,
            f"{bet_pct:.0f}% of bets but only {money_pct:.0f}% of money → sharp money fading the public side.",
        )

    # ── Steam Move ──────────────────────────────────────────────
    # Line moved significantly without big public bet volume
    if line_move is not None and abs(line_move) >= STEAM_LINE_MOVE_THRESHOLD and bet_pct < 60:
        direction = "moved against" if line_move < 0 else "moved toward"
        strength  = "strong" if abs(line_move) >= 3 else "moderate"
        return (
            "steam",
            "🔥 Steam Move",
            strength,
            f"Line {direction} {selection_placeholder()} by {abs(line_move):.1f} despite only {bet_pct:.0f}% public action — sharp bet likely.",
        )

    # ── Sharp Money (money >> bets, line moving favorably) ──────
    if money_gap >= 20 and money_pct >= 55:
        strength = "strong" if money_gap >= 35 else "moderate"
        return (
            "sharp_money",
            "💰 Sharp Money",
            strength,
            f"Money ({money_pct:.0f}%) far outpaces bets ({bet_pct:.0f}%) — larger bets on this side.",
        )

    # ── Public Side (tout/fade candidate) ───────────────────────
    if bet_pct >= TOUT_BET_THRESHOLD and money_pct >= TOUT_MONEY_THRESHOLD:
        return (
            "public",
            "👥 Heavy Public Action",
            "weak",
            f"{bet_pct:.0f}% of bets and {money_pct:.0f}% of money aligned — classic public side. Fade potential.",
        )

    # ── Balanced / No Signal ─────────────────────────────────────
    return (
        "balanced",
        "⚖️ Balanced Action",
        "weak",
        f"Bets: {bet_pct:.0f}% / Money: {money_pct:.0f}% — no significant sharp signal detected.",
    )


def selection_placeholder():
    return "this side"
