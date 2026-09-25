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

flask_app = create_app()

class PrefixMiddleware:
    """
    WSGI middleware that normalizes incoming Vercel Serverless requests.
    Ensures that requests arriving with or without the `/api` prefix
    always match Flask's `@app.route('/api/...')` endpoints.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        # If Vercel stripped /api, or request arrived without /api:
        if not path.startswith("/api") and path not in ("", "/"):
            environ["PATH_INFO"] = "/api" + (path if path.startswith("/") else "/" + path)
        return self.wsgi_app(environ, start_response)

flask_app.wsgi_app = PrefixMiddleware(flask_app.wsgi_app)
app = flask_app

# For direct execution / testing
if __name__ == "__main__":
    app.run()
