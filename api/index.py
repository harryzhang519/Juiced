"""
api/index.py
============
Vercel Serverless entry point for EV Edge.
Exposes the Flask WSGI application instance `app`.
"""
import os
import sys

# Ensure root directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from backend.server import create_app

app = create_app()

# For direct execution / testing
if __name__ == "__main__":
    app.run()
