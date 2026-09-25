"""
api/index.py
============
Vercel Serverless Function entry point for EV Edge / Juiced.
Guarantees a clean, uncrashable top-level Flask app instance.
"""
import os
import sys
import traceback

# Ensure project root directory is on sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from flask import Flask, jsonify, request

app = Flask(__name__)

# Diagnostic health check endpoint
@app.route("/api/health")
def api_health():
    info = {
        "status": "ok",
        "python": sys.version,
        "cwd": os.getcwd(),
        "files_in_cwd": os.listdir(os.getcwd()) if os.path.exists(os.getcwd()) else []
    }
    try:
        from config import Config
        from backend.db import get_db_mode
        info["config_loaded"] = True
        info["db_mode"] = get_db_mode()
        info["supabase_configured"] = bool(Config.SUPABASE_URL and Config.SUPABASE_KEY and "your-project" not in Config.SUPABASE_URL)
        info["admin_pin_configured"] = bool(Config.ADMIN_PIN)
    except Exception as e:
        info["config_loaded"] = False
        info["error"] = str(e)
        info["traceback"] = traceback.format_exc().splitlines()
    return jsonify(info)


# Mount backend server if possible, or provide structured diagnostics
try:
    import backend.server as bs
    app = bs.app
except Exception as _backend_err:
    _import_err_tb = traceback.format_exc()

    @app.route("/api/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def fallback_api(subpath):
        return jsonify({
            "status": "error",
            "message": "Failed to import backend.server",
            "requested_subpath": subpath,
            "error": str(_backend_err),
            "traceback": _import_err_tb.splitlines()
        }), 500

if __name__ == "__main__":
    app.run()
