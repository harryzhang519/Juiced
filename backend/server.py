"""
backend/server.py
=================
Flask application + REST API routes for EV Edge.

Routes:
  GET  /                           → serves frontend/index.html
  GET  /api/sports                 → list of available sports
  GET  /api/ev-bets                → top +EV bets for a sport
  GET  /api/parlays                → best parlays for a sport
  GET  /api/summary                → aggregate stats for a sport
  POST /api/refresh                → trigger manual odds refresh
  GET  /api/status                 → scheduler + quota status
"""

from __future__ import annotations
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, jsonify, request, send_from_directory, abort
from flask_cors import CORS

from config import Config
import backend.scheduler as sched_mod

log = logging.getLogger(__name__)

# ── App setup ─────────────────────────────────────────────
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR)
app.secret_key = Config.SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB max upload
CORS(app)


# ── Static / frontend ─────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ── API: Sports ───────────────────────────────────────────

@app.route("/api/sports")
def api_sports():
    """List of all tracked sports."""
    from backend.api_client import client
    sports = client.get_available_sports()
    return jsonify({"sports": sports, "demo_mode": Config.is_demo_mode()})


@app.route("/api/resolve-scores", methods=["POST", "GET"])
def tracker_score_sync():
    """
    Searches for completed game scores and automatically resolves all pending plays on the tracker.
    Updates win/loss status, calculates P&L and CLV.
    """
    from backend.tracker import auto_resolve_pending_bets
    resolve_result = auto_resolve_pending_bets()
    return jsonify({"status": "ok", "resolution": resolve_result})


# ── API: EV Bets ──────────────────────────────────────────

@app.route("/api/ev-bets")
def api_ev_bets():
    """
    Top +EV bets for a sport.

    Query params:
      sport   (str, default: baseball_mlb)
      limit   (int, default: 50)
      min_ev  (float, default: 0.0)  — minimum EV% as decimal (e.g. 0.01 = 1%)
      market  (str, default: all)    — h2h | spreads | totals | all
      book    (str, default: all)    — FanDuel | DraftKings | all
    """
    sport   = request.args.get("sport",   "baseball_mlb")
    limit   = int(request.args.get("limit",   50))
    min_ev  = float(request.args.get("min_ev", 0.0))
    market  = request.args.get("market",  "all").lower()
    book    = request.args.get("book",    "all").lower()

    if sport not in Config.SPORTS:
        abort(400, f"Unknown sport: {sport}")

    result = _get_or_refresh(sport)
    bets = result.get("bets", [])

    # Filter out games that have already commenced in the past
    now_dt = datetime.now(timezone.utc)
    def _is_upcoming(commence_str):
        if not commence_str:
            return False
        try:
            dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
            return dt >= now_dt
        except Exception:
            return True

    total_bets_in_cache = len(bets)
    bets = [b for b in bets if _is_upcoming(b.get("commence_time", ""))]
    # Detect "no upcoming games" vs "genuinely no EV bets"
    no_upcoming_games = (total_bets_in_cache > 0 and len(bets) == 0)

    # Apply filters
    if market != "all":
        bets = [b for b in bets if b["market_key"] == market]
    if book != "all":
        bets = [b for b in bets if book in b["target_book"].lower()]
    if min_ev > 0:
        bets = [b for b in bets if b["ev_pct"] >= min_ev]

    # Re-rank after filter
    for i, bet in enumerate(bets[:limit], 1):
        bet["rank"] = i

    return jsonify({
        "sport":            sport,
        "bets":             bets[:limit],
        "meta":             result.get("meta", {}),
        "filters":          {"market": market, "min_ev": min_ev, "book": book},
        "no_upcoming_games": no_upcoming_games,
        "message":          (
            "Today's slate hasn't been posted yet — the odds API typically updates after ~10 AM ET. Check back soon."
            if no_upcoming_games else None
        ),
    })


# ── API: Parlays ──────────────────────────────────────────

@app.route("/api/parlays")
def api_parlays():
    """Best parlays for a sport."""
    sport = request.args.get("sport", "baseball_mlb")
    if sport not in Config.SPORTS:
        abort(400, f"Unknown sport: {sport}")

    result = _get_or_refresh(sport)
    parlays = result.get("parlays", [])
    now_iso = datetime.now(timezone.utc).isoformat()
    valid_parlays = []
    for p in parlays:
        legs = [leg for leg in p.get("legs", []) if leg.get("commence_time", "") >= now_iso]
        if len(legs) >= 2:
            p["legs"] = legs
            valid_parlays.append(p)

    return jsonify({
        "sport":   sport,
        "parlays": valid_parlays,
        "meta":    result.get("meta", {}),
    })


# ── API: Summary ──────────────────────────────────────────

@app.route("/api/summary")
def api_summary():
    """High-level stats for a sport."""
    sport = request.args.get("sport", "baseball_mlb")
    if sport not in Config.SPORTS:
        abort(400, f"Unknown sport: {sport}")

    result = _get_or_refresh(sport)
    meta = result.get("meta", {})
    bets = result.get("bets", [])

    grade_counts: dict[str, int] = {}
    for b in bets:
        g = b.get("ev_grade", "F")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    from backend.api_client import client
    cache_info = client.get_cache_info(sport)

    return jsonify({
        "sport":       sport,
        "meta":        meta,
        "grade_dist":  grade_counts,
        "cache_info":  cache_info,
        "demo_mode":   Config.is_demo_mode(),
    })


# ── API: Refresh ──────────────────────────────────────────

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Trigger immediate odds refresh for a sport."""
    sport = request.args.get("sport", "baseball_mlb")
    if sport not in Config.SPORTS:
        abort(400, f"Unknown sport: {sport}")

    import threading
    def _do_refresh():
        sched_mod.refresh_sport(sport, force=True)

    t = threading.Thread(target=_do_refresh, daemon=True)
    t.start()

    return jsonify({
        "status":  "refresh_started",
        "sport":   sport,
        "message": f"Refreshing {Config.SPORTS[sport]['label']} odds in the background.",
    })


# ── API: Status ───────────────────────────────────────────

@app.route("/api/status")
def api_status():
    """Scheduler and quota status."""
    return jsonify(sched_mod.get_all_status())


@app.route("/api/last-refresh")
def api_last_refresh():
    """
    Lightweight poll endpoint: returns the analyzed_at timestamp and bet count
    for the current sport. Frontend polls this to know when to refetch.
    """
    sport = request.args.get("sport", "baseball_mlb")
    result = sched_mod.get_cached_result(sport)
    if not result:
        return jsonify({"analyzed_at": None, "total_bets": 0, "sport": sport})
    meta = result.get("meta", {})
    return jsonify({
        "analyzed_at": meta.get("analyzed_at"),
        "total_bets":  meta.get("total_bets", 0),
        "sport":       sport,
        "demo_mode":   Config.is_demo_mode(),
    })


# ── API: Sharp Money & RLM Intelligence ───────────────────

@app.route("/api/sharp", methods=["GET"])
def api_sharp_signals():
    """
    Get sharp money & RLM signals for a sport.
    Combines scraped bet% data from Action Network, line movements from odds cache,
    and runs sharp_engine signal classification.
    """
    sport = request.args.get("sport", "baseball_mlb")
    if sport not in Config.SPORTS:
        abort(400, f"Unknown sport: {sport}")

    from backend.sharp_scraper import get_public_betting_data, get_line_movement
    from backend.sharp_engine import analyze_sharp_signals
    from backend.api_client import client

    scraped_data = get_public_betting_data(sport)
    current_odds = client.get_odds(sport)
    movements = get_line_movement(sport, current_odds)

    # Build input list for sharp engine
    games_input = []
    
    # If scraped data exists
    if scraped_data:
        move_map = {(m["game"], m["selection"]): m for m in movements}
        for item in scraped_data:
            matchup = item["game"]
            away = item["away_team"]
            home = item["home_team"]

            # Away team side
            move_away = move_map.get((matchup, away))
            games_input.append({
                "matchup": matchup,
                "selection": away,
                "bet_pct": item["bet_pct_away"],
                "money_pct": item["money_pct_away"],
                "line_open": move_away["line_open"] if move_away else None,
                "line_current": move_away["line_current"] if move_away else None,
            })

            # Home team side
            move_home = move_map.get((matchup, home))
            games_input.append({
                "matchup": matchup,
                "selection": home,
                "bet_pct": item["bet_pct_home"],
                "money_pct": item["money_pct_home"],
                "line_open": move_home["line_open"] if move_home else None,
                "line_current": move_home["line_current"] if move_home else None,
            })

    # If no scraped data or fallback requested, create intelligent defaults from current odds
    if not games_input and current_odds:
        for g in current_odds[:8]:
            away = g.get("away_team", "Away")
            home = g.get("home_team", "Home")
            matchup = f"{away} @ {home}"
            
            # Extract moneyline or spread odds for demonstration
            for bm in g.get("bookmakers", []):
                for mkt in bm.get("markets", []):
                    if mkt["key"] in ["h2h", "spreads"]:
                        outcomes = mkt.get("outcomes", [])
                        if len(outcomes) == 2:
                            o1, o2 = outcomes[0], outcomes[1]
                            games_input.append({
                                "matchup": matchup,
                                "selection": f"{o1['name']} ({mkt['key'].upper()})",
                                "bet_pct": 68.0,
                                "money_pct": 32.0,
                                "line_open": o1.get("point", o1.get("price")) + (0.5 if o1.get("point") else 15),
                                "line_current": o1.get("point", o1.get("price")),
                            })
                            games_input.append({
                                "matchup": matchup,
                                "selection": f"{o2['name']} ({mkt['key'].upper()})",
                                "bet_pct": 32.0,
                                "money_pct": 68.0,
                                "line_open": o2.get("point", o2.get("price")) - (0.5 if o2.get("point") else 15),
                                "line_current": o2.get("point", o2.get("price")),
                            })
                        break

    signals = analyze_sharp_signals(games_input)
    return jsonify({
        "sport": sport,
        "signals": signals,
        "count": len(signals),
        "source": "automated_scraper" if scraped_data else "odds_derived"
    })


@app.route("/api/sharp/analyze", methods=["POST"])
def api_sharp_analyze():
    """
    Accepts custom betting split data from user input and evaluates sharp signals.
    Payload body:
      { "games": [ { "matchup": "NYY @ BOS", "selection": "Boston Red Sox", "bet_pct": 65, "money_pct": 30, "line_open": -3.5, "line_current": -2.5 } ] }
    """
    data = request.get_json(force=True)
    if not data or "games" not in data:
        abort(400, "JSON body with 'games' array required")

    from backend.sharp_engine import analyze_sharp_signals
    signals = analyze_sharp_signals(data["games"])
    return jsonify({"signals": signals, "count": len(signals)})


# ── API: Pikkit — Screenshot ROI Tracker ──────────────

@app.route("/api/pikkit/upload", methods=["POST"])
def pikkit_upload():
    """
    Upload a bet screenshot. Gemini Vision auto-extracts bet details.
    Returns extracted bets (may be multiple if several slips visible).
    """
    from backend.pikkit import parse_screenshot, save_upload, create_bet_from_parsed, add_bet

    if "file" not in request.files:
        abort(400, "No file uploaded — use multipart/form-data with field 'file'")

    f = request.files["file"]
    if not f.filename:
        abort(400, "Empty filename")

    image_bytes = f.read()
    stored_name = save_upload(image_bytes, f.filename)

    # Vision parse
    parsed_list, vision_err = parse_screenshot(image_bytes, f.filename)

    saved_bets = []
    if parsed_list:
        for p in parsed_list:
            bet = create_bet_from_parsed(p, screenshot_file=stored_name)
            add_bet(bet)
            saved_bets.append(bet)
    else:
        log.warning("Vision parse returned no results for %s: %s", stored_name, vision_err)

    return jsonify({
        "status":       "ok",
        "screenshot":   stored_name,
        "bets_found":   len(saved_bets),
        "bets":         saved_bets,
        "vision_ok":    len(saved_bets) > 0,
        "vision_error": vision_err,
    }), 201


@app.route("/api/pikkit/bets", methods=["GET"])
def pikkit_get_bets():
    """Return all pikkit bets with optional filters."""
    import importlib, backend.pikkit
    importlib.reload(backend.pikkit)
    result     = request.args.get("result")
    sportsbook = request.args.get("sportsbook")
    sport      = request.args.get("sport")
    return jsonify({"bets": backend.pikkit.get_all_bets(result=result, sportsbook=sportsbook, sport=sport)})


@app.route("/api/pikkit/bets", methods=["POST"])
def pikkit_add_bet():
    """Manually add a single bet (no screenshot)."""
    import importlib, backend.pikkit
    importlib.reload(backend.pikkit)
    data = request.get_json(force=True)
    if not data:
        abort(400, "JSON body required")
    bet = backend.pikkit.create_bet_from_parsed(data)
    backend.pikkit.add_bet(bet)
    return jsonify({"bet": bet}), 201


@app.route("/api/pikkit/bets/<bet_id>", methods=["PATCH"])
def pikkit_update_bet(bet_id: str):
    """Update a pikkit bet (settle result, fix odds, etc.)."""
    import importlib, backend.pikkit
    importlib.reload(backend.pikkit)
    data = request.get_json(force=True)
    bet  = backend.pikkit.update_bet(bet_id, data)
    if not bet:
        abort(404, f"Bet {bet_id} not found")
    return jsonify({"bet": bet})


@app.route("/api/pikkit/bets/<bet_id>", methods=["DELETE"])
def pikkit_delete_bet(bet_id: str):
    """Delete a pikkit bet."""
    from backend.pikkit import delete_bet
    if not delete_bet(bet_id):
        abort(404, f"Bet {bet_id} not found")
    return jsonify({"deleted": bet_id})


@app.route("/api/pikkit/calendar", methods=["GET"])
def pikkit_calendar():
    """Daily P&L data for the calendar heatmap."""
    from backend.pikkit import get_calendar_data
    return jsonify({"calendar": get_calendar_data()})


@app.route("/api/pikkit/stats", methods=["GET"])
def pikkit_stats():
    """Full aggregate stats: ROI, win rate, streak, bankroll curve, by-sportsbook."""
    import importlib, backend.pikkit
    importlib.reload(backend.pikkit)
    return jsonify(backend.pikkit.get_summary_stats())


@app.route("/api/pikkit/ai-eval", methods=["GET"])
def pikkit_ai_eval():
    """AI pattern analysis & bet chalker evaluation powered by Gemini 3.6 Flash."""
    import importlib, backend.pikkit
    importlib.reload(backend.pikkit)
    return jsonify(backend.pikkit.evaluate_bets_with_ai())


@app.route("/api/pikkit/screenshot/<filename>")
def pikkit_screenshot(filename: str):
    """Serve a stored screenshot image."""
    from flask import send_from_directory
    import os
    uploads_dir = os.path.join(Config.DATA_DIR, "uploads")
    return send_from_directory(uploads_dir, filename)


# ── API: Tracker — Bet Log ────────────────────────────────


@app.route("/api/tracker/bets", methods=["GET"])
def tracker_get_bets():
    """Return all logged bets, newest first."""
    from backend.tracker import get_bets
    sport  = request.args.get("sport")
    result = request.args.get("result")
    return jsonify({"bets": get_bets(sport=sport, result=result)})


@app.route("/api/tracker/bets", methods=["POST"])
def tracker_log_bet():
    """Log a new bet."""
    from backend.tracker import log_bet
    data = request.get_json(force=True)
    if not data:
        abort(400, "JSON body required")
    required = ["game", "selection", "offered_odds", "fair_odds"]
    missing  = [k for k in required if k not in data]
    if missing:
        abort(400, f"Missing fields: {missing}")
    bet = log_bet(data)
    return jsonify({"bet": bet}), 201


@app.route("/api/tracker/bets/<bet_id>", methods=["PATCH"])
def tracker_update_bet(bet_id: str):
    """Update a bet (add result, closing odds, recap)."""
    from backend.tracker import update_bet
    data = request.get_json(force=True)
    bet  = update_bet(bet_id, data)
    if not bet:
        abort(404, f"Bet {bet_id} not found")
    return jsonify({"bet": bet})


@app.route("/api/tracker/bets/<bet_id>", methods=["DELETE"])
def tracker_delete_bet(bet_id: str):
    """Delete a bet."""
    from backend.tracker import delete_bet
    if not delete_bet(bet_id):
        abort(404, f"Bet {bet_id} not found")
    return jsonify({"deleted": bet_id})


@app.route("/api/tracker/summary", methods=["GET"])
def tracker_summary():
    """Cumulative ROI, CLV, and win-rate stats."""
    from backend.tracker import get_summary
    return jsonify(get_summary())


# ── API: Export for LLM / Analysis ──────────────────────

@app.route("/api/export/llm", methods=["GET"])
def export_for_llm():
    """
    Run export script and return links/content for LLM processing.
    Query params:
      format (str, default: prompt) — prompt | csv | json
    """
    from scratch.export_roi_for_llm import main as run_export, EXPORT_PROMPT_MD_PATH, EXPORT_CSV_PATH, EXPORT_JSON_PATH
    run_export()

    fmt = request.args.get("format", "prompt").lower()
    if fmt == "csv":
        return send_from_directory(Config.DATA_DIR, "export_bets_history.csv", as_attachment=True)
    elif fmt == "json":
        return send_from_directory(Config.DATA_DIR, "export_full_bet_history.json", as_attachment=True)
    else:
        with open(EXPORT_PROMPT_MD_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({
            "status": "ok",
            "prompt_text": content,
            "download_urls": {
                "csv": "/api/export/llm?format=csv",
                "json": "/api/export/llm?format=json",
                "prompt": "/api/export/llm?format=prompt"
            }
        })



@app.route("/<path:filename>", methods=["GET"])
def static_files(filename):
    log.info("DEBUG STATIC FILES CALLED WITH: %s", filename)
    if filename.startswith("api/"):
        abort(404)
    target = os.path.join(FRONTEND_DIR, filename)
    if os.path.isfile(target):
        return send_from_directory(FRONTEND_DIR, filename)
    abort(404)


# ── Error handlers ────────────────────────────────────────

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e)}), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed", "url": request.url, "method": request.method}), 405

@app.errorhandler(413)
def request_too_large(e):
    return jsonify({"error": "File too large — max 20 MB"}), 413

@app.errorhandler(500)
def internal(e):
    log.exception("Internal server error")
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500

@app.errorhandler(Exception)
def handle_unexpected(e):
    log.exception("Unhandled exception")
    return jsonify({"error": "Unexpected server error", "detail": str(e)}), 500


# ── Helpers ───────────────────────────────────────────────

def _get_or_refresh(sport: str) -> dict:
    """
    Return cached EV results for a sport.
    If cache is stale or missing, triggers a synchronous refresh.
    """
    client = sched_mod._get_client()
    info = client.get_cache_info(sport)
    if not info.get("is_fresh", False):
        log.info("Cache for %s is stale — refreshing synchronously", sport)
        return sched_mod.refresh_sport(sport, force=True) or {}

    result = sched_mod.get_cached_result(sport)
    if result is None:
        log.info("No cache for %s — running first-time refresh synchronously", sport)
        result = sched_mod.refresh_sport(sport, force=True)
    return result or {}


def create_app() -> Flask:
    return app
