"""
api/index.py
============
Vercel Serverless Function entry point for EV Edge / Juiced.
Exports the Flask WSGI instance `app`.
Includes self-diagnostics so any import or runtime failure returns the exact traceback.
"""
import os
import sys
import traceback
import json

# Ensure project root directory is on sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from flask import Flask, jsonify

app = None
init_error = None

try:
    from backend.server import app as real_app
    app = real_app
except Exception as e:
    init_error = traceback.format_exc()
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    @app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def catch_all(path=""):
        return jsonify({
            "status": "initialization_failed",
            "error": str(e),
            "traceback": init_error.splitlines(),
            "cwd": os.getcwd(),
            "sys_path": sys.path,
            "root_dir_contents": os.listdir(ROOT_DIR) if os.path.exists(ROOT_DIR) else [],
            "cwd_contents": os.listdir(os.getcwd()) if os.path.exists(os.getcwd()) else []
        }), 200

if init_error is None:
    # Wrap wsgi_app to catch any runtime exception and return details instead of FUNCTION_INVOCATION_FAILED
    _orig_wsgi = app.wsgi_app

    def safe_wsgi(environ, start_response):
        try:
            return _orig_wsgi(environ, start_response)
        except Exception as run_err:
            tb = traceback.format_exc()
            body = json.dumps({
                "status": "runtime_exception",
                "error": str(run_err),
                "traceback": tb.splitlines(),
                "path_info": environ.get("PATH_INFO"),
                "forwarded_uri": environ.get("HTTP_X_FORWARDED_URI")
            }, indent=2).encode("utf-8")
            start_response("200 OK", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body)))
            ])
            return [body]

    app.wsgi_app = safe_wsgi

if __name__ == "__main__":
    app.run()
