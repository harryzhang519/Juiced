"""
run.py — EV Edge entry point.
Starts the APScheduler background refresh, then launches the Flask server.

Usage:
    python run.py
"""
import logging
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

from config import Config
from backend.scheduler import start_scheduler, stop_scheduler
from backend.server import create_app


def main():
    log.info("=" * 60)
    log.info("  EV EDGE — Sports Betting Analytics Dashboard")
    log.info("=" * 60)
    log.info("Demo mode : %s", Config.is_demo_mode())
    log.info("Host/Port : %s:%d", Config.HOST, Config.PORT)
    log.info("Cache TTL : %d hours", Config.CACHE_TTL_HOURS)
    log.info("Refresh   : %s (cron)", Config.REFRESH_CRON)
    if Config.is_demo_mode():
        log.warning(
            "No ODDS_API_KEY found — running in DEMO MODE with mock data.\n"
            "  -> Copy .env.example to .env and add your key from https://the-odds-api.com"
        )
    log.info("=" * 60)

    # Start background scheduler
    scheduler = start_scheduler()

    app = create_app()

    try:
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=Config.DEBUG,
            use_reloader=False,   # Reloader conflicts with APScheduler
        )
    finally:
        stop_scheduler()


if __name__ == "__main__":
    main()
