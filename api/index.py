"""
api/index.py
============
Vercel Serverless Function entry point for EV Edge / Juiced.
Exports the Flask WSGI instance `app`.
Guarantees that ANY error returns a detailed JSON report with HTTP 200.
"""
import os
import sys
import traceback

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from flask import Flask, jsonify, request

app = None
try:
    from backend.server import app as real_app
    app = real_app
except Exception as e:
    tb = traceback.format_exc()
    app = Flask(__name__)

    @app.route("/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    @app.route("/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def fallback_api(subpath=""):
        return jsonify({
            "status": "error",
            "message": "Failed to import backend.server",
            "requested_subpath": subpath,
            "error": str(e),
            "traceback": tb.splitlines()
        }), 200

def custom_handle_exception(e):
    tb = traceback.format_exc()
    return app.make_response((
        jsonify({
            "status": "server_exception",
            "error": str(e),
            "traceback": tb.splitlines(),
        }),
        200
    ))

app.handle_exception = custom_handle_exception

if __name__ == "__main__":
    app.run()
