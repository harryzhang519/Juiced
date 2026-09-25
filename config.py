"""
config.py — Central configuration for EV Edge.
All values are read from environment variables (or .env file).
"""
import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path, override=True)


class Config:
    # ── The-Odds-API ──────────────────────────────────────
    ODDS_API_KEY: str = os.getenv("ODDS_API_KEY", "")
    ODDS_API_BASE: str = "https://api.the-odds-api.com/v4"

    # ── Flask ─────────────────────────────────────────────
    HOST: str = os.getenv("FLASK_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("FLASK_PORT", 5000))
    DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-in-prod")

    # ── Security / Admin ──────────────────────────────────
    ADMIN_PIN: str = os.getenv("ADMIN_PIN", "")

    # ── Database (Supabase / Postgres / Local Fallback) ───
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

    # ── Data / Cache ──────────────────────────────────────
    DATA_DIR: str = os.path.join(os.path.dirname(__file__), "data")
    CACHE_TTL_HOURS: float = float(os.getenv("CACHE_TTL_HOURS", 0.5))

    # ── Scheduler ─────────────────────────────────────────
    # Default: 9:00 AM every day
    REFRESH_CRON: str = os.getenv("REFRESH_CRON", "0 9 * * *")

    # ── Books to compare ──────────────────────────────────
    # These two books form the benchmark pair for devigging.
    BOOK_A: str = "fanduel"
    BOOK_B: str = "draftkings"
    BOOK_LABELS: dict = {
        "fanduel": "FanDuel",
        "draftkings": "DraftKings",
        "betmgm": "BetMGM",
        "caesars": "Caesars",
        "pointsbet": "PointsBet",
    }

    # ── Sports to track ───────────────────────────────────────
    # Only include sports that are currently in-season.
    # Add leagues back below as their seasons begin.
    SPORTS: dict = {
        # ── Currently Active ──────────────────────────────────
        "baseball_mlb":               {"label": "MLB",   "emoji": "⚾"},   # Active
        "basketball_wnba":            {"label": "WNBA",  "emoji": "🏀"},  # Active

        # ── Add back when season starts ───────────────────────
        # "basketball_nba":           {"label": "NBA",   "emoji": "🏀"},  # ~Oct
        # "americanfootball_nfl":     {"label": "NFL",   "emoji": "🏈"},  # ~Sep
        # "americanfootball_ncaaf":   {"label": "NCAAF", "emoji": "🏈"},  # ~Aug
        # "icehockey_nhl":            {"label": "NHL",   "emoji": "🏒"},  # ~Oct
        # "basketball_ncaab":         {"label": "NCAAB", "emoji": "🏀"},  # ~Nov
        # "soccer_epl":               {"label": "EPL",   "emoji": "⚽"},  # ~Aug
        # "mma_mixed_martial_arts":   {"label": "MMA",   "emoji": "🥊"},  # Year-round (optional)
    }

    # ── Markets to analyze ────────────────────────────────────
    MARKETS: list = ["h2h", "spreads", "totals"]

    # ── EV Grading thresholds ─────────────────────────────
    EV_GRADES: list = [
        (0.07, "A+"),
        (0.05, "A"),
        (0.03, "B+"),
        (0.01, "B"),
        (0.00, "C"),
    ]

    @classmethod
    def is_demo_mode(cls) -> bool:
        """Returns True when no API key is configured."""
        return not cls.ODDS_API_KEY or cls.ODDS_API_KEY == "your_key_here"

    @classmethod
    def get_ev_grade(cls, ev_pct: float) -> str:
        for threshold, grade in cls.EV_GRADES:
            if ev_pct >= threshold:
                return grade
        return "F"
