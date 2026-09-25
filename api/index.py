"""
api/index.py
============
Vercel Serverless Function entry point for EV Edge / Juiced.
Exports the Flask WSGI application instance `app`.
"""
import os
import sys

# Ensure project root directory is on sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.server import app

# Top-level application assignment for Vercel's Python runtime detector
app = app

if __name__ == "__main__":
    app.run()
