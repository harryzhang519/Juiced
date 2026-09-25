"""
backend/devig.py
================
Core EV math: odds conversion, devigging, EV calculation, and parlay builder.
"""
from __future__ import annotations
from typing import Optional


# ── Odds Conversion ──────────────────────────────────────────────

def american_to_implied(american: int | float) -> float:
    """Convert American odds to implied probability (includes vig)."""
    american = float(american)
    if american >= 0:
        return 100.0 / (american + 100.0)
    else:
        return abs(american) / (abs(american) + 100.0)


def american_to_decimal(american: int | float) -> float:
    """Convert American odds to decimal odds (includes stake)."""
    american = float(american)
    if american >= 0:
        return (american / 100.0) + 1.0
    else:
        return (100.0 / abs(american)) + 1.0


def decimal_to_american(decimal: float) -> int:
    """Convert decimal odds back to nearest American odds."""
    if decimal >= 2.0:
        return round((decimal - 1) * 100)
    else:
        return round(-100 / (decimal - 1))


def implied_to_american(prob: float) -> int:
    """Convert a true probability to American odds."""
    if prob <= 0 or prob >= 1:
        raise ValueError(f"Probability must be between 0 and 1, got {prob}")
    if prob >= 0.5:
        return round(-prob / (1 - prob) * 100)
    else:
        return round((1 - prob) / prob * 100)


# ── Devigging ─────────────────────────────────────────────────────

def devig_proportional(odds_a: int | float, odds_b: int | float) -> tuple[float, float]:
    """
    Remove vig from a 2-way market using the proportional method.
    Returns (fair_prob_a, fair_prob_b) where sum == 1.0.
    """
    imp_a = american_to_implied(odds_a)
    imp_b = american_to_implied(odds_b)
    total = imp_a + imp_b
    return imp_a / total, imp_b / total


def calc_ev(fair_prob: float, offered_decimal: float) -> float:
    """
    EV% = (fair_prob × offered_decimal) - 1
    Positive = edge in our favor.
    """
    return (fair_prob * offered_decimal) - 1.0


# ── Cross-Book EV ─────────────────────────────────────────────────

def find_ev_bets(
    game: dict,
    book_a_key: str = "fanduel",
    book_b_key: str = "draftkings",
    min_ev: float = 0.0,
    ev_grades: Optional[list] = None,
) -> list[dict]:
    """
    Given a game dict from The-Odds-API, compare book_a vs book_b line-by-line.
    Returns list of +EV bet opportunities.
    """
    if ev_grades is None:
        ev_grades = [
            (0.07, "A+"), (0.05, "A"), (0.03, "B+"), (0.01, "B"), (0.00, "C"),
        ]

    results = []

    bookmakers = {bm["key"]: bm for bm in game.get("bookmakers", [])}
    bm_a = bookmakers.get(book_a_key)
    bm_b = bookmakers.get(book_b_key)

    if not bm_a or not bm_b:
        return results

    markets_a = {m["key"]: m for m in bm_a.get("markets", [])}
    markets_b = {m["key"]: m for m in bm_b.get("markets", [])}

    common_markets = set(markets_a) & set(markets_b)

    for mkt_key in common_markets:
        mkt_a = markets_a[mkt_key]
        mkt_b = markets_b[mkt_key]

        outcomes_a = {o["name"]: o for o in mkt_a.get("outcomes", [])}
        outcomes_b = {o["name"]: o for o in mkt_b.get("outcomes", [])}

        common_outcomes = set(outcomes_a) & set(outcomes_b)
        if len(common_outcomes) < 2:
            continue

        outcome_names = list(common_outcomes)

        # For 2-way markets (h2h, spreads) — standard devig
        if len(outcome_names) == 2:
            name_a_side, name_b_side = outcome_names[0], outcome_names[1]

            o_a_side_a = outcomes_a[name_a_side].get("price")
            o_a_side_b = outcomes_a[name_b_side].get("price")
            o_b_side_a = outcomes_b[name_a_side].get("price")
            o_b_side_b = outcomes_b[name_b_side].get("price")

            if None in (o_a_side_a, o_a_side_b, o_b_side_a, o_b_side_b):
                continue

            # Book A as benchmark: fair probs from book A line
            fp_a, fp_b = devig_proportional(o_a_side_a, o_a_side_b)

            # EV of betting side A on Book B
            ev_ba = calc_ev(fp_a, american_to_decimal(o_b_side_a))
            # EV of betting side B on Book B
            ev_bb = calc_ev(fp_b, american_to_decimal(o_b_side_b))

            # Book B as benchmark: fair probs from book B line
            fp_ba, fp_bb = devig_proportional(o_b_side_a, o_b_side_b)

            # EV of betting side A on Book A
            ev_aa = calc_ev(fp_ba, american_to_decimal(o_a_side_a))
            # EV of betting side B on Book A
            ev_ab = calc_ev(fp_bb, american_to_decimal(o_a_side_b))

            candidates = [
                (name_a_side, ev_ba, o_b_side_a, o_a_side_a, book_b_key, book_a_key),
                (name_b_side, ev_bb, o_b_side_b, o_a_side_b, book_b_key, book_a_key),
                (name_a_side, ev_aa, o_a_side_a, o_b_side_a, book_a_key, book_b_key),
                (name_b_side, ev_ab, o_a_side_b, o_b_side_b, book_a_key, book_b_key),
            ]

            for selection, ev_pct, offered_odds, fair_ref_odds, target_book, bench_book in candidates:
                if ev_pct < min_ev:
                    continue

                grade = "F"
                for threshold, g in ev_grades:
                    if ev_pct >= threshold:
                        grade = g
                        break

                # Point/spread label
                outcome_obj = outcomes_b.get(selection) if target_book == book_b_key else outcomes_a.get(selection)
                point = outcome_obj.get("point") if outcome_obj else None
                selection_label = f"{selection} ({point:+g})" if point is not None else selection

                results.append({
                    "game":          f"{game.get('away_team', '')} @ {game.get('home_team', '')}",
                    "commence_time": game.get("commence_time"),
                    "sport_key":     game.get("sport_key", ""),
                    "market_key":    mkt_key,
                    "market_label":  _market_label(mkt_key),
                    "selection":     selection_label,
                    "target_book":   target_book,
                    "bench_book":    bench_book,
                    "offered_odds":  offered_odds,
                    "fair_odds":     implied_to_american(
                        american_to_implied(fair_ref_odds) / (
                            american_to_implied(fair_ref_odds) + american_to_implied(
                                outcomes_b.get(name_b_side if selection == name_a_side else name_a_side, {}).get("price", -110)
                                if target_book == book_b_key else
                                outcomes_a.get(name_b_side if selection == name_a_side else name_a_side, {}).get("price", -110)
                            )
                        ) * (
                            american_to_implied(fair_ref_odds) + american_to_implied(
                                outcomes_b.get(name_b_side if selection == name_a_side else name_a_side, {}).get("price", -110)
                                if target_book == book_b_key else
                                outcomes_a.get(name_b_side if selection == name_a_side else name_a_side, {}).get("price", -110)
                            )
                        )
                    ) if False else fair_ref_odds,  # simplified: use raw fair ref odds
                    "ev_pct":        round(ev_pct, 6),
                    "ev_pct_display": f"{ev_pct * 100:+.2f}%",
                    "ev_grade":      grade,
                    "rank":          0,
                })

        # For 3-way markets (soccer h2h with draw) — iterate each side
        elif len(outcome_names) >= 3:
            total_impl_a = sum(american_to_implied(outcomes_a[n]["price"]) for n in outcome_names if n in outcomes_a)
            total_impl_b = sum(american_to_implied(outcomes_b[n]["price"]) for n in outcome_names if n in outcomes_b)

            for sel_name in outcome_names:
                if sel_name not in outcomes_a or sel_name not in outcomes_b:
                    continue
                o_price_a = outcomes_a[sel_name]["price"]
                o_price_b = outcomes_b[sel_name]["price"]

                # Fair prob from book A
                fp = american_to_implied(o_price_a) / total_impl_a

                ev_b = calc_ev(fp, american_to_decimal(o_price_b))
                if ev_b >= min_ev:
                    grade = "F"
                    for threshold, g in ev_grades:
                        if ev_b >= threshold:
                            grade = g
                            break
                    results.append({
                        "game":           f"{game.get('away_team', '')} @ {game.get('home_team', '')}",
                        "commence_time":  game.get("commence_time"),
                        "sport_key":      game.get("sport_key", ""),
                        "market_key":     mkt_key,
                        "market_label":   _market_label(mkt_key),
                        "selection":      sel_name,
                        "target_book":    book_b_key,
                        "bench_book":     book_a_key,
                        "offered_odds":   o_price_b,
                        "fair_odds":      o_price_a,
                        "ev_pct":         round(ev_b, 6),
                        "ev_pct_display": f"{ev_b * 100:+.2f}%",
                        "ev_grade":       grade,
                        "rank":           0,
                    })

    results.sort(key=lambda x: x["ev_pct"], reverse=True)
    for i, r in enumerate(results, 1):
        r["rank"] = i

    return results


# ── Parlay Builder ─────────────────────────────────────────────────

def build_parlays(ev_bets: list[dict], n_legs: int = 3, top_n: int = 5) -> list[dict]:
    """
    Greedy parlay builder:
    - Max 1 leg per game (independence requirement)
    - All legs from the same sportsbook
    - Selects highest EV legs first
    Returns top_n parlays ranked by combined EV.
    """
    from itertools import combinations

    # Group by book
    by_book: dict[str, list[dict]] = {}
    for b in ev_bets:
        key = b["target_book"]
        by_book.setdefault(key, []).append(b)

    parlays = []

    for book, bets in by_book.items():
        # Deduplicate: 1 leg per game (highest EV leg per game)
        seen_games: dict[str, dict] = {}
        for b in sorted(bets, key=lambda x: x["ev_pct"], reverse=True):
            game = b["game"]
            if game not in seen_games:
                seen_games[game] = b

        pool = list(seen_games.values())

        if len(pool) < n_legs:
            continue

        # Try all combinations of n_legs from pool (capped at top 15 for performance)
        top_pool = pool[:15]
        best_ev = -999
        best_combo = None

        for combo in combinations(top_pool, n_legs):
            combined_ev = 1.0
            for leg in combo:
                fp = american_to_implied(leg["fair_odds"]) if leg.get("fair_odds") else american_to_implied(leg["offered_odds"])
                dec = american_to_decimal(leg["offered_odds"])
                combined_ev *= fp * dec
            combined_ev -= 1.0
            if combined_ev > best_ev:
                best_ev = combined_ev
                best_combo = combo

        if best_combo:
            combined_decimal = 1.0
            for leg in best_combo:
                combined_decimal *= american_to_decimal(leg["offered_odds"])

            parlays.append({
                "book":        book,
                "legs":        list(best_combo),
                "n_legs":      n_legs,
                "combined_ev": round(best_ev, 6),
                "combined_ev_display": f"{best_ev * 100:+.2f}%",
                "combined_decimal": round(combined_decimal, 2),
                "combined_american": decimal_to_american(combined_decimal),
            })

    parlays.sort(key=lambda x: x["combined_ev"], reverse=True)
    return parlays[:top_n]


# ── Helpers ───────────────────────────────────────────────────────

def _market_label(key: str) -> str:
    return {"h2h": "Moneyline", "spreads": "Spread", "totals": "Total"}.get(key, key.title())
