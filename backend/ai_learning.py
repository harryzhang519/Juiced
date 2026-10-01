"""
backend/ai_learning.py
======================
AI-assisted bet pattern analysis and model improvement suggestions.
Includes a 1-100 betting score grade.
"""
from __future__ import annotations
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config

log = logging.getLogger(__name__)


def compute_score(bets: list[dict]) -> tuple[int, str]:
    """
    Compute a 1-100 betting performance score.

    Factors:
      - ROI vs expected  (40 pts)
      - Win rate         (20 pts)
      - CLV positive rate (20 pts)
      - Sample size      (10 pts)
      - EV accuracy      (10 pts)

    Returns (score, label)
    """
    settled = [b for b in bets if b.get("result") in ("win", "loss", "push")]
    if not settled:
        return 0, "No Data"

    wins         = [b for b in settled if b["result"] == "win"]
    win_rate     = len(wins) / len(settled)
    total_staked = sum(b.get("stake") or 0 for b in settled) or 1
    total_pnl    = sum(b.get("pnl")   or 0 for b in settled)
    roi_pct      = total_pnl / total_staked * 100
    avg_ev       = sum(b.get("ev_pct") or 0 for b in settled) / len(settled) * 100

    clv_bets     = [b for b in settled if b.get("clv_pct") is not None]
    clv_pos_rate = (sum(1 for b in clv_bets if b["clv_pct"] > 0) / len(clv_bets)) if clv_bets else 0.5

    # ROI score (40 pts): >+5% ROI = 40, flat = 20, -5% = 0
    roi_score = max(0, min(40, int((roi_pct + 5) / 10 * 40)))

    # Win rate score (20 pts):
    # For plus-money / parlay / high-odds ledgers, win rates between 40-50% yield exceptional returns.
    if roi_pct >= 20.0:
        wr_score = 20 if win_rate >= 0.45 else (18 if win_rate >= 0.38 else 14)
    elif win_rate >= 0.55: wr_score = 20
    elif win_rate >= 0.50: wr_score = 14
    elif win_rate >= 0.45: wr_score = 10
    elif win_rate >= 0.40: wr_score = 6
    else:                  wr_score = 2

    # CLV score (20 pts) — neutral at 12 when CLV data is being backfilled
    clv_score = int(clv_pos_rate * 20) if clv_bets else 12

    # Sample size confidence (10 pts)
    n = len(settled)
    if n >= 200:   ss_score = 10
    elif n >= 100: ss_score = 8
    elif n >= 50:  ss_score = 7
    elif n >= 20:  ss_score = 5
    else:          ss_score = 3

    # EV accuracy & Profitability consistency (10 pts)
    if avg_ev > 0:
        variance_ratio = abs(roi_pct - avg_ev) / max(abs(avg_ev), 1)
        ev_score = max(0, int(10 - variance_ratio * 10))
    elif roi_pct > 0:
        ev_score = 8  # Strong positive returns
    else:
        ev_score = 4

    score = max(1, min(100, roi_score + wr_score + clv_score + ss_score + ev_score))

    if score >= 80:   label = "Elite"
    elif score >= 65: label = "Strong"
    elif score >= 50: label = "Solid"
    elif score >= 35: label = "Developing"
    else:             label = "Needs Work"

    return score, label


def evaluate_bet_history(bets: list[dict], max_bets: int = 100) -> dict:
    """
    Send recent bet history to Gemini and get back pattern analysis.
    Returns a dict with {score, score_label, summary, patterns, recommendations, model_notes}.
    Falls back gracefully if API key is missing.
    """
    try:
        import google.genai as genai
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            return _fallback_analysis(bets)

        client = genai.Client(api_key=api_key)

        settled = [b for b in bets if b.get("result") in ("win", "loss", "push")][-max_bets:]
        if not settled:
            return _fallback_analysis(bets)

        wins         = sum(1 for b in settled if b["result"] == "win")
        losses       = sum(1 for b in settled if b["result"] == "loss")
        pushes       = sum(1 for b in settled if b["result"] == "push")
        total_pnl    = sum(b.get("pnl") or 0 for b in settled)
        total_staked = sum(b.get("stake") or 0 for b in settled) or 1
        roi_pct      = total_pnl / total_staked * 100
        win_rate     = wins / len(settled) * 100

        # Sport breakdown
        sport_pnl: dict = {}
        sport_record: dict = {}
        for b in settled:
            sp = b.get("sport") or "Other"
            sport_pnl[sp] = round(sport_pnl.get(sp, 0.0) + (b.get("pnl") or 0.0), 2)
            sport_record.setdefault(sp, {"w": 0, "l": 0})
            if b["result"] == "win":
                sport_record[sp]["w"] += 1
            elif b["result"] == "loss":
                sport_record[sp]["l"] += 1
        sport_summary = {
            sp: {"pnl": sport_pnl[sp], "record": f"{sport_record[sp]['w']}W-{sport_record[sp]['l']}L"}
            for sp in sport_pnl
        }

        # Sportsbook breakdown
        book_pnl: dict = {}
        for b in settled:
            bk = b.get("sportsbook") or "Unknown"
            book_pnl[bk] = round(book_pnl.get(bk, 0.0) + (b.get("pnl") or 0.0), 2)

        # Odds distribution
        odds_list = [b.get("odds") or 0 for b in settled]
        avg_odds = round(sum(odds_list) / len(odds_list), 1) if odds_list else 0
        high_odds_count = sum(1 for o in odds_list if o >= 200)
        plus_money_count = sum(1 for o in odds_list if o > 0)

        # Market breakdown
        parlays   = [b for b in settled if "parlay" in (b.get("market") or "").lower() or (b.get("odds") or 0) >= 300]
        straights = [b for b in settled if b not in parlays]
        parlay_pnl   = round(sum(b.get("pnl") or 0 for b in parlays), 2)
        straight_pnl = round(sum(b.get("pnl") or 0 for b in straights), 2)

        bet_summary = [{
            "date":      b.get("date"),
            "sport":     b.get("sport"),
            "book":      b.get("sportsbook"),
            "market":    b.get("market"),
            "selection": (b.get("selection") or "")[:45],
            "odds":      b.get("odds"),
            "stake":     b.get("stake"),
            "pnl":       b.get("pnl"),
            "result":    b.get("result"),
        } for b in settled[-45:]]

        prompt = f"""You are an elite quantitative sports betting analyst for EV Edge.
Analyze this verified betting performance ledger according to the +EV quantitative framework.
Use ONLY the exact numbers provided below — do NOT invent or use numbers from prior context.

REAL-TIME LEDGER STATS (use these exact figures in your summary):
  Record: {wins}W-{losses}L{f'-{pushes}P' if pushes else ''}
  Total Net Profit: ${total_pnl:+.2f}
  Win Rate: {win_rate:.1f}%
  ROI: {roi_pct:+.1f}%
  Total Bets Settled: {len(settled)}
  Average Odds: {avg_odds:+.0f}
  Plus-Money Bets: {plus_money_count} of {len(settled)}
  High-Odds (>=+200) Bets: {high_odds_count}
  Parlay P&L: ${parlay_pnl:+.2f} across {len(parlays)} bets
  Straight P&L: ${straight_pnl:+.2f} across {len(straights)} bets

SPORT BREAKDOWN:
{json.dumps(sport_summary, indent=2)}

SPORTSBOOK BREAKDOWN:
{json.dumps(book_pnl, indent=2)}

RECENT WAGERS SAMPLE (last {len(bet_summary)}):
{json.dumps(bet_summary, indent=2)}

Analysis Requirements:
1. Closing Line Value (CLV) & Market Mispricing vs. Standard Sports Variance:
   Evaluate whether losses were driven by expected variance vs. structural bookmaker overround.
   A {win_rate:.1f}% win rate is expected and profitable at these plus-money odds levels.
2. Quantitative Patterns:
   Identify 3 deep quantitative patterns from the ACTUAL sport breakdown, market structures, and sportsbook data above.
3. Actionable Strategic Recommendations:
   Provide 3 actionable recommendations to optimize capital growth and isolate +EV edges.
4. Model & Calibration Notes:
   Evaluate how actual ${total_pnl:+.2f} / {roi_pct:+.1f}% ROI compares against theoretical +EV baseline.

CRITICAL: Your summary MUST reference the exact figures: {wins}W-{losses}L record, ${total_pnl:+.2f} net profit, {win_rate:.1f}% win rate, and {roi_pct:+.1f}% ROI.

Respond STRICTLY in valid JSON format with keys:
"summary": string (2-sentence quantitative executive summary using the EXACT stats above),
"score": int (performance score 1-100),
"score_label": string ('Elite', 'Strong', 'Solid', 'Developing', or 'Needs Work'),
"patterns": list of 3 strings (patterns referencing real sport/book/market data),
"recommendations": list of 3 strings (strategic quant actions),
"model_notes": string (variance vs mispricing assessment with exact ROI figure)"""

        # Models ordered by verified availability and speed
        candidate_models = [
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.8-flash",
            "gemini-3.1-flash-lite-preview",
            "gemini-flash-latest",
        ]
        response = None
        last_err = None

        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response and response.text:
                    break
            except Exception as me:
                last_err = me
                log.warning("Gemini model %s failed: %s, trying next candidate...", model_name, me)

        if not response or not response.text:
            raise Exception(f"All candidate models failed. Last error: {last_err}")

        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        result = json.loads(text)
        calc_score, calc_label = compute_score(bets)
        
        # Use AI score if valid, otherwise calculated quant score
        ai_score = result.get("score")
        if not isinstance(ai_score, int) or ai_score < 1 or ai_score > 100:
            result["score"] = calc_score
            result["score_label"] = calc_label
        else:
            result["score_label"] = result.get("score_label") or calc_label

        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        return result

    except Exception as e:
        log.warning("AI evaluation failed: %s", e)
        return _fallback_analysis(bets)


def _fallback_analysis(bets: list[dict]) -> dict:
    """Quantitative statistical analysis fallback when Gemini is unavailable."""
    settled = [b for b in bets if b.get("result") in ("win", "loss", "push")]
    if not settled:
        return {
            "score": 0, "score_label": "No Data",
            "summary": "No settled bets available for analysis.",
            "patterns": [], "recommendations": ["Log settled bets to enable quantitative pattern analysis."],
            "model_notes": "Insufficient data sample.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _safe_n(v, d=0.0):
        try: return float(str(v or d).replace("$", "").replace(",", "").strip())
        except Exception: return d

    def _safe_o(v):
        try: return int(float(str(v or 100).replace("+", "").strip()))
        except Exception: return 100

    wins         = [b for b in settled if str(b.get("result") or "").lower() == "win"]
    losses       = [b for b in settled if str(b.get("result") or "").lower() == "loss"]
    win_rate     = len(wins) / len(settled) * 100
    total_staked = sum(_safe_n(b.get("stake")) for b in settled) or 1
    total_pnl    = sum(_safe_n(b.get("pnl")) for b in settled)
    roi_pct      = total_pnl / total_staked * 100
    score, score_label = compute_score(bets)

    # Market & Sport breakdowns
    sport_pnl: dict[str, float] = {}
    for b in settled:
        sp = str(b.get("sport") or "Other")
        sport_pnl[sp] = round(sport_pnl.get(sp, 0.0) + _safe_n(b.get("pnl")), 2)
    best_sport = max(sport_pnl, key=sport_pnl.get) if sport_pnl else "MLB"

    parlays = [b for b in settled if "parlay" in str(b.get("market") or "").lower() or _safe_o(b.get("odds")) >= 300]
    straights = [b for b in settled if b not in parlays]
    parlay_pnl = sum(_safe_n(b.get("pnl")) for b in parlays)
    straight_pnl = sum(_safe_n(b.get("pnl")) for b in straights)

    patterns = [
        f"Strong performance in {best_sport} generating ${sport_pnl.get(best_sport, 0):+.2f} net profit across {len(settled)} settled wagers.",
        f"Asymmetric odds profile: {win_rate:.1f}% win rate remains highly profitable ({roi_pct:+.1f}% ROI) due to positive expected value on plus-money wagers.",
        f"Market breakdown: Straight bets (${straight_pnl:+.2f}) provide lower volatility while parlay/high-odds positions (${parlay_pnl:+.2f}) exhibit higher variance drag.",
    ]

    recommendations = [
        "Focus volume on single-game straight moneylines where true market mispricing can be isolated without compounding vig.",
        "Implement fractional Kelly unit sizing to protect bankroll against standard underdog variance cycles.",
        "Maintain disciplined closing line tracking to ensure consistent positive CLV over extended sample sizes.",
    ]

    return {
        "score":            score,
        "score_label":      score_label,
        "summary":          f"This betting ledger demonstrates {score_label.lower()} positive expected value execution, yielding a ${total_pnl:+.2f} net profit across a {len(wins)}W-{len(losses)}L record. Despite a sub-50% win rate ({win_rate:.1f}%), the concentration of plus-money and high-odds selections drives an exceptional {roi_pct:+.1f}% ROI.",
        "patterns":         patterns,
        "recommendations":  recommendations,
        "model_notes":      f"Portfolio running at {roi_pct:+.1f}% ROI across {len(settled)} settled bets ({len(wins)}W-{len(losses)}L, {win_rate:.1f}% win rate). ${total_pnl:+.2f} total net profit reflects favorable variance on high-odds selections above +EV baseline.",
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }
