"""
backend/pikkit.py
=================
Bet screenshot parser and ROI tracker.

Responsibilities:
  - Save uploaded screenshot images to data/uploads/
  - Parse bet details from screenshots using Gemini Vision
  - Persist bets to data/pikkit_bets.json
  - Compute aggregate stats (ROI, win rate, bankroll curve, calendar heatmap)
  - AI pattern evaluation via Gemini

Bet schema:
  id, logged_at, source, screenshot, date, sportsbook, sport,
  game, selection, market, odds, stake, payout, result, pnl
"""
from __future__ import annotations
import hashlib
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

PIKKIT_PATH   = os.path.join(Config.DATA_DIR, "pikkit_bets.json")
UPLOADS_DIR   = os.path.join(Config.DATA_DIR, "uploads")


# ── Persistence (delegated to backend.db) ──────────────────────────

def _load() -> list:
    from backend.db import get_all_bets
    return get_all_bets()


# ── Screenshot Upload ─────────────────────────────────────────────

def save_upload(image_bytes: bytes, original_filename: str) -> str:
    """Save image bytes to uploads dir or fallback to /tmp in serverless. Returns stored filename."""
    ext = os.path.splitext(original_filename)[1].lower() or ".png"
    name_hash = hashlib.md5(image_bytes).hexdigest()[:12]
    filename = f"{name_hash}{ext}"
    try:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        path = os.path.join(UPLOADS_DIR, filename)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(image_bytes)
    except (OSError, PermissionError):
        # Serverless / Read-only filesystem fallback
        import tempfile
        tmp_dir = os.path.join(tempfile.gettempdir(), "uploads")
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, filename)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(image_bytes)
    return filename


# ── Gemini Vision Parse ───────────────────────────────────────────

def parse_screenshot(image_bytes: bytes, filename: str) -> tuple[list[dict], Optional[str]]:
    """
    Send a bet slip screenshot to Gemini Vision and extract bet details.
    Returns (list_of_parsed_bets, error_message_or_None).
    Each parsed bet dict has keys matching the pikkit schema.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return [], "GEMINI_API_KEY not set — cannot parse screenshot."

    try:
        import PIL.Image
        import io
        img = PIL.Image.open(io.BytesIO(image_bytes))

        prompt = """Analyze this sports betting screenshot and extract all bet details.

Return a JSON array of bets. Each bet object must have these exact keys:
{
  "date": "YYYY-MM-DD",
  "sportsbook": "FanDuel|DraftKings|BetMGM|Caesars|Betway|PointsBet|etc",
  "sport": "NFL|MLB|NBA|NHL|Soccer|Tennis|MMA|NCAAF|NCAAB|WNBA|etc",
  "game": "Team A vs Team B (or multi-game description)",
  "selection": "What was bet on (player name, team, prop description)",
  "market": "Moneyline|Spread|Total|Parlay|Same Game Parlay|Player Prop|Game Prop|etc",
  "odds": 150,
  "stake": 10.00,
  "payout": 25.00,
  "result": "win|loss|push|pending",
  "pnl": 15.00
}

Rules:
- odds in American format (e.g. +150, -110). Use integer.
- stake and payout in dollars as floats.
- pnl = payout - stake for wins, -stake for losses, 0 for push, null if pending.
- If multiple bets are visible, return all of them as separate array items.
- If a parlay, describe all legs in the "selection" field.
- Return ONLY the JSON array, no other text.
"""

        candidate_models = [
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ]

        text = ""
        last_err = None

        # Prefer google.genai client
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            for model_name in candidate_models:
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=[img, prompt],
                    )
                    if resp and resp.text:
                        text = resp.text.strip()
                        break
                except Exception as me:
                    last_err = me
                    log.warning("google.genai model %s failed: %s, trying next candidate...", model_name, me)
        except ImportError:
            pass

        # Fallback to legacy google.generativeai if needed
        if not text:
            try:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=api_key)
                for model_name in candidate_models:
                    try:
                        m = legacy_genai.GenerativeModel(model_name)
                        resp = m.generate_content([prompt, img])
                        if resp and resp.text:
                            text = resp.text.strip()
                            break
                    except Exception as me:
                        last_err = me
                        log.warning("legacy genai model %s failed: %s", model_name, me)
            except Exception as le:
                if not last_err:
                    last_err = le

        if not text:
            raise Exception(f"All Gemini Vision models failed. Last error: {last_err}")

        # Extract JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        # Try to parse
        if text.startswith("["):
            parsed = json.loads(text)
        elif text.startswith("{"):
            parsed = [json.loads(text)]
        else:
            # Try finding JSON array in text
            start = text.find("[")
            end   = text.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
            else:
                return [], f"Could not extract JSON from response: {text[:200]}"

        return parsed, None

    except Exception as e:
        log.warning("Vision parse error for %s: %s", filename, e)
        return [], str(e)


# ── Bet CRUD ──────────────────────────────────────────────────────

def create_bet_from_parsed(parsed: dict, screenshot_file: Optional[str] = None) -> dict:
    """Create a canonical pikkit bet dict from parsed/manual input."""
    stake  = float(parsed.get("stake") or 0)
    payout = parsed.get("payout")
    result = parsed.get("result", "pending")
    pnl    = parsed.get("pnl")

    # Compute pnl if missing
    if pnl is None:
        if result == "win" and payout is not None:
            pnl = float(payout) - stake
        elif result == "loss":
            pnl = -stake
        elif result == "push":
            pnl = 0.0

    return {
        "id":         str(uuid.uuid4())[:8].upper(),
        "logged_at":  datetime.now(timezone.utc).isoformat(),
        "source":     "screenshot" if screenshot_file else "manual",
        "screenshot": screenshot_file,
        "date":       parsed.get("date", datetime.now().strftime("%Y-%m-%d")),
        "sportsbook": parsed.get("sportsbook", "Unknown"),
        "sport":      parsed.get("sport", "Unknown"),
        "game":       parsed.get("game", ""),
        "selection":  parsed.get("selection", ""),
        "market":     parsed.get("market", "Moneyline"),
        "odds":       int(parsed.get("odds") or 100),
        "stake":      stake,
        "payout":     float(payout) if payout is not None else None,
        "result":     result,
        "pnl":        round(float(pnl), 2) if pnl is not None else None,
    }


def add_bet(bet: dict) -> dict:
    from backend.db import add_bet as db_add_bet
    return db_add_bet(bet)


def update_bet(bet_id: str, updates: dict) -> Optional[dict]:
    from backend.db import update_bet as db_update_bet
    bets = _load()
    target = next((b for b in bets if b.get("id") == bet_id), None)
    if target:
        target.update(updates)
        stake  = float(target.get("stake") or 0)
        payout = target.get("payout")
        result = target.get("result", "pending")
        if "result" in updates or "stake" in updates or "payout" in updates:
            if result == "win" and payout is not None:
                updates["pnl"] = round(float(payout) - stake, 2)
            elif result == "loss":
                updates["pnl"] = round(-stake, 2)
            elif result == "push":
                updates["pnl"] = 0.0
            else:
                updates["pnl"] = target.get("pnl")
    return db_update_bet(bet_id, updates)


def delete_bet(bet_id: str) -> bool:
    from backend.db import delete_bet as db_delete_bet
    return db_delete_bet(bet_id)


def get_all_bets(
    result: Optional[str] = None,
    sportsbook: Optional[str] = None,
    sport: Optional[str] = None,
) -> list[dict]:
    bets = _load()
    if result:
        bets = [b for b in bets if b.get("result") == result]
    if sportsbook:
        bets = [b for b in bets if (b.get("sportsbook") or "").lower() == sportsbook.lower()]
    if sport:
        bets = [b for b in bets if (b.get("sport") or "").lower() == sport.lower()]
    return sorted(bets, key=lambda b: b.get("date", ""), reverse=True)


# ── Stats ─────────────────────────────────────────────────────────

def get_summary_stats() -> dict:
    """Full aggregate stats for the pikkit dashboard."""
    bets    = _load()
    settled = [b for b in bets if b.get("result") in ("win", "loss", "push")]
    pending = [b for b in bets if b.get("result") == "pending"]
    wins    = [b for b in settled if b["result"] == "win"]
    losses  = [b for b in settled if b["result"] == "loss"]
    pushes  = [b for b in settled if b["result"] == "push"]

    total_staked = sum(b.get("stake") or 0 for b in settled)
    total_pnl    = sum(b.get("pnl") or 0 for b in settled)
    roi_pct      = (total_pnl / total_staked * 100) if total_staked > 0 else 0.0
    win_rate     = (len(wins) / len(settled) * 100) if settled else 0.0

    # Streak
    streak_type, streak_len = _compute_streak(settled)

    # Bankroll curve (cumulative P&L over time)
    bankroll_curve = _compute_bankroll_curve(settled)

    # By sportsbook
    by_book: dict[str, dict] = {}
    for b in settled:
        book = b.get("sportsbook", "Unknown")
        by_book.setdefault(book, {"bets": 0, "wins": 0, "pnl": 0.0, "staked": 0.0})
        by_book[book]["bets"]   += 1
        by_book[book]["pnl"]    += b.get("pnl") or 0
        by_book[book]["staked"] += b.get("stake") or 0
        if b["result"] == "win":
            by_book[book]["wins"] += 1

    for book, stats in by_book.items():
        stats["roi_pct"] = round(stats["pnl"] / stats["staked"] * 100, 2) if stats["staked"] > 0 else 0.0
        stats["win_rate"] = round(stats["wins"] / stats["bets"] * 100, 1) if stats["bets"] > 0 else 0.0
        stats["pnl"] = round(stats["pnl"], 2)

    # By sport
    by_sport: dict[str, dict] = {}
    for b in settled:
        sp = b.get("sport", "Unknown")
        by_sport.setdefault(sp, {"bets": 0, "wins": 0, "pnl": 0.0, "staked": 0.0})
        by_sport[sp]["bets"]   += 1
        by_sport[sp]["pnl"]    += b.get("pnl") or 0
        by_sport[sp]["staked"] += b.get("stake") or 0
        if b["result"] == "win":
            by_sport[sp]["wins"] += 1

    for sp, stats in by_sport.items():
        stats["roi_pct"] = round(stats["pnl"] / stats["staked"] * 100, 2) if stats["staked"] > 0 else 0.0
        stats["win_rate"] = round(stats["wins"] / stats["bets"] * 100, 1) if stats["bets"] > 0 else 0.0
        stats["pnl"] = round(stats["pnl"], 2)

    # Risk metrics: Peak & Drawdown
    peak_profit  = max((pt["cumulative"] for pt in bankroll_curve), default=0.0)
    max_drawdown = max((pt.get("drawdown", 0.0) for pt in bankroll_curve), default=0.0)
    max_dd_pct   = (max_drawdown / peak_profit * 100) if peak_profit > 0 else 0.0
    expected_pnl = bankroll_curve[-1]["expected_cumulative"] if bankroll_curve else 0.0

    return {
        "total_bets":        len(bets),
        "settled":           len(settled),
        "pending":           len(pending),
        "wins":              len(wins),
        "losses":            len(losses),
        "pushes":            len(pushes),
        "record":            f"{len(wins)}-{len(losses)}",
        "win_rate_pct":      round(win_rate, 1),
        "total_staked":      round(total_staked, 2),
        "total_pnl":         round(total_pnl, 2),
        "roi_pct":           round(roi_pct, 2),
        "peak_profit":       round(peak_profit, 2),
        "max_drawdown":      round(max_drawdown, 2),
        "max_drawdown_pct":  round(max_dd_pct, 1),
        "expected_pnl":      round(expected_pnl, 2),
        "variance_pnl":      round(total_pnl - expected_pnl, 2),
        "streak_type":       streak_type,
        "streak_len":        streak_len,
        "bankroll_curve":    bankroll_curve,
        "by_sportsbook":     by_book,
        "by_sport":          by_sport,
    }


def get_calendar_data() -> list[dict]:
    """Daily P&L for the calendar heatmap."""
    bets    = _load()
    settled = [b for b in bets if b.get("result") in ("win", "loss", "push")]

    daily: dict[str, dict] = {}
    for b in settled:
        day = b.get("date", "")[:10]
        if not day:
            continue
        daily.setdefault(day, {"date": day, "pnl": 0.0, "bets": 0, "wins": 0})
        daily[day]["pnl"]  += b.get("pnl") or 0
        daily[day]["bets"] += 1
        if b["result"] == "win":
            daily[day]["wins"] += 1

    for day in daily:
        daily[day]["pnl"] = round(daily[day]["pnl"], 2)

    return sorted(daily.values(), key=lambda d: d["date"])


# ── AI Evaluation ─────────────────────────────────────────────────

def evaluate_bets_with_ai() -> dict:
    """Run AI pattern analysis on pikkit bet history with dynamic module reload."""
    import importlib
    import backend.ai_learning
    importlib.reload(backend.ai_learning)
    bets = _load()
    return backend.ai_learning.evaluate_bet_history(bets)


# ── Internal helpers ──────────────────────────────────────────────

def _compute_streak(settled: list[dict]) -> tuple[str, int]:
    if not settled:
        return "none", 0
    ordered = sorted(settled, key=lambda b: b.get("date", ""))
    last_result = ordered[-1]["result"]
    streak = 0
    for b in reversed(ordered):
        if b["result"] == last_result:
            streak += 1
        else:
            break
    return last_result, streak


def _compute_bankroll_curve(settled: list[dict]) -> list[dict]:
    """
    Computes chronological bankroll trajectory with both:
    1. Realized cumulative P&L
    2. Theoretical +EV expected baseline (EV Edge benchmark)
    3. Peak profit & drawdown metrics
    """
    ordered = sorted(settled, key=lambda b: (b.get("date", ""), b.get("logged_at", "")))
    cumulative = 0.0
    expected_cumulative = 0.0
    peak = 0.0
    curve = []

    for b in ordered:
        pnl = b.get("pnl") or 0.0
        stake = b.get("stake") or 0.0
        cumulative += pnl

        # Calculate theoretical expected return (+EV baseline)
        if b.get("ev_pct") is not None:
            ev_gain = stake * (b["ev_pct"] / 100.0)
        else:
            # Standard quantitative sharp baseline: +4.5% target edge on turnover
            ev_gain = stake * 0.045
        expected_cumulative += ev_gain

        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative

        curve.append({
            "date":                b.get("date", ""),
            "selection":           b.get("selection") or b.get("game") or "Wager",
            "sport":               b.get("sport") or "Other",
            "market":              b.get("market") or "Moneyline",
            "odds":                b.get("odds"),
            "stake":               round(stake, 2),
            "result":              b.get("result", "pending"),
            "pnl":                 round(pnl, 2),
            "cumulative":          round(cumulative, 2),
            "expected_cumulative": round(expected_cumulative, 2),
            "peak":                round(peak, 2),
            "drawdown":            round(drawdown, 2),
        })
    return curve
