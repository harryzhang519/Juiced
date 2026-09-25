"""
backend/props_engine.py
=======================
Player props EV analysis engine.

Fetches alternate market odds for player props (pitcher strikeouts,
batter hits/RBI, etc.) and runs the same devigging + EV calculation
as the main engine, but per-player across bookmakers.

Only runs when PROPS_ENABLED=true in config (uses extra API credits).
"""
from __future__ import annotations
import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config

log = logging.getLogger(__name__)

# ── Prop markets by sport ─────────────────────────────────────────

PROP_MARKETS: dict[str, list[str]] = {
    "baseball_mlb": [
        "batter_hits", "batter_total_bases", "batter_rbis",
        "batter_runs_scored", "batter_home_runs",
        "pitcher_strikeouts", "pitcher_outs",
    ],
    "basketball_nba": [
        "player_points", "player_rebounds", "player_assists",
        "player_threes", "player_blocks", "player_steals",
        "player_points_rebounds_assists",
    ],
    "basketball_wnba": [
        "player_points", "player_rebounds", "player_assists",
        "player_threes",
    ],
    "americanfootball_nfl": [
        "player_pass_yds", "player_pass_tds", "player_rush_yds",
        "player_reception_yds", "player_receptions",
        "player_anytime_td",
    ],
    "icehockey_nhl": [
        "player_points", "player_goals", "player_assists",
        "player_shots_on_goal",
    ],
}


def get_props_ev(sport_key: str) -> list[dict]:
    """
    Fetch player prop markets for all today's games in a sport
    and return +EV prop bets.

    Returns [] when PROPS_ENABLED is false or no data available.
    """
    props_enabled = os.getenv("PROPS_ENABLED", "false").lower() == "true"
    if not props_enabled:
        log.debug("Props disabled (PROPS_ENABLED=false)")
        return []

    markets = PROP_MARKETS.get(sport_key, [])
    if not markets:
        log.debug("No prop markets configured for %s", sport_key)
        return []

    from backend.api_client import client
    from backend.devig import american_to_implied, american_to_decimal, calc_ev

    # Get current game list
    odds_list = client.get_odds(sport_key)
    if not odds_list:
        return []

    all_prop_bets = []

    for game in odds_list[:10]:   # Limit to first 10 games to save quota
        event_id = game.get("id")
        if not event_id:
            continue

        event_data = client.get_event_props(sport_key, event_id, markets)
        if not event_data:
            continue

        game_label = f"{game.get('away_team', '')} @ {game.get('home_team', '')}"
        prop_bets  = _analyze_event_props(event_data, game_label, game.get("commence_time"))
        all_prop_bets.extend(prop_bets)

    all_prop_bets.sort(key=lambda b: b["ev_pct"], reverse=True)
    for i, b in enumerate(all_prop_bets, 1):
        b["rank"] = i

    log.info("Props analysis for %s: %d +EV props found", sport_key, len(all_prop_bets))
    return all_prop_bets


def _analyze_event_props(event: dict, game_label: str, commence_time: Optional[str]) -> list[dict]:
    """Find +EV prop bets across bookmakers for a single event."""
    from backend.devig import american_to_implied, american_to_decimal, calc_ev

    results = []
    bookmakers = event.get("bookmakers", [])
    if len(bookmakers) < 2:
        return results

    # Index by bookmaker key → market key → player name → {over/under: price}
    bm_data: dict[str, dict] = {}
    for bm in bookmakers:
        bm_key = bm.get("key", "")
        bm_data[bm_key] = {}
        for mkt in bm.get("markets", []):
            mkt_key = mkt.get("key", "")
            bm_data[bm_key][mkt_key] = {}
            for outcome in mkt.get("outcomes", []):
                player_name = outcome.get("description", outcome.get("name", ""))
                side        = outcome.get("name", "").lower()   # "Over" or "Under"
                price       = outcome.get("price")
                point       = outcome.get("point")
                if player_name and price:
                    bm_data[bm_key][mkt_key].setdefault(player_name, {})[side] = {
                        "price": price, "point": point
                    }

    bm_keys = list(bm_data.keys())

    # Compare each pair of bookmakers
    for i in range(len(bm_keys)):
        for j in range(i + 1, len(bm_keys)):
            bm_a_key = bm_keys[i]
            bm_b_key = bm_keys[j]
            bm_a = bm_data[bm_a_key]
            bm_b = bm_data[bm_b_key]

            common_markets = set(bm_a) & set(bm_b)
            for mkt_key in common_markets:
                mkt_a = bm_a[mkt_key]
                mkt_b = bm_b[mkt_key]
                common_players = set(mkt_a) & set(mkt_b)

                for player in common_players:
                    sides_a = mkt_a[player]
                    sides_b = mkt_b[player]

                    over_a  = sides_a.get("over", {}).get("price")
                    under_a = sides_a.get("under", {}).get("price")
                    over_b  = sides_b.get("over", {}).get("price")
                    under_b = sides_b.get("under", {}).get("price")
                    point   = sides_a.get("over", {}).get("point") or sides_b.get("over", {}).get("point")

                    if None in (over_a, under_a, over_b, under_b):
                        continue

                    # Devig book A → fair probs
                    impl_over_a  = american_to_implied(over_a)
                    impl_under_a = american_to_implied(under_a)
                    total_impl_a = impl_over_a + impl_under_a
                    fp_over  = impl_over_a / total_impl_a
                    fp_under = impl_under_a / total_impl_a

                    # EV on Book B
                    ev_over  = calc_ev(fp_over,  american_to_decimal(over_b))
                    ev_under = calc_ev(fp_under, american_to_decimal(under_b))

                    point_str = f" {point:+g}" if point is not None else ""

                    for side_label, ev_pct, offered_price, bench_price in [
                        ("Over",  ev_over,  over_b,  over_a),
                        ("Under", ev_under, under_b, under_a),
                    ]:
                        if ev_pct > 0.005:   # >0.5% EV threshold for props
                            results.append({
                                "game":           game_label,
                                "commence_time":  commence_time,
                                "market_key":     mkt_key,
                                "market_label":   _prop_label(mkt_key),
                                "selection":      f"{player} {side_label}{point_str}",
                                "player":         player,
                                "target_book":    bm_b_key,
                                "bench_book":     bm_a_key,
                                "offered_odds":   offered_price,
                                "fair_odds":      bench_price,
                                "point":          point,
                                "ev_pct":         round(ev_pct, 6),
                                "ev_pct_display": f"{ev_pct * 100:+.2f}%",
                                "ev_grade":       _grade(ev_pct),
                                "rank":           0,
                                "prop":           True,
                            })

    return results


def _grade(ev: float) -> str:
    for threshold, g in Config.EV_GRADES:
        if ev >= threshold:
            return g
    return "F"


def _prop_label(mkt_key: str) -> str:
    labels = {
        "batter_hits":                    "Batter Hits",
        "batter_total_bases":             "Total Bases",
        "batter_rbis":                    "Batter RBIs",
        "batter_home_runs":               "Home Run",
        "pitcher_strikeouts":             "Pitcher Ks",
        "pitcher_outs":                   "Pitcher Outs",
        "player_points":                  "Points",
        "player_rebounds":                "Rebounds",
        "player_assists":                 "Assists",
        "player_threes":                  "3-Pointers",
        "player_blocks":                  "Blocks",
        "player_steals":                  "Steals",
        "player_points_rebounds_assists": "PRA",
        "player_pass_yds":                "Pass Yards",
        "player_pass_tds":                "Pass TDs",
        "player_rush_yds":                "Rush Yards",
        "player_reception_yds":           "Rec Yards",
        "player_receptions":              "Receptions",
        "player_anytime_td":              "Anytime TD",
        "player_shots_on_goal":           "Shots on Goal",
        "player_goals":                   "Goals",
    }
    return labels.get(mkt_key, mkt_key.replace("_", " ").title())
