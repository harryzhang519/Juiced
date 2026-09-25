"""
api/index.py
============
Vercel Serverless entry point for EV Edge.
Exposes the Flask WSGI application instance `app`.
"""
import json
import os
import sys
import traceback

# Ensure root directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
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
            try:
                path = environ.get("PATH_INFO", "")
                if not path.startswith("/api") and path not in ("", "/"):
                    environ["PATH_INFO"] = "/api" + (path if path.startswith("/") else "/" + path)
                return self.wsgi_app(environ, start_response)
            except Exception as e:
                tb = traceback.format_exc()
                print("RUNTIME ERROR IN WSGI HANDLER:", tb)
                body = json.dumps({
                    "error": "Internal server execution error",
                    "exception": str(e),
                    "traceback": tb.splitlines(),
                }, indent=2).encode("utf-8")
                start_response("500 Internal Server Error", [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body)))
                ])
                return [body]

    flask_app.wsgi_app = PrefixMiddleware(flask_app.wsgi_app)
    app = flask_app

except Exception as init_err:
    tb = traceback.format_exc()
    print("FATAL INITIALIZATION ERROR IN api/index.py:", tb)

    def app(environ, start_response):
        body = json.dumps({
            "error": "Backend initialization failed at startup",
            "exception": str(init_err),
            "traceback": tb.splitlines(),
        }, indent=2).encode("utf-8")
        start_response("500 Internal Server Error", [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body)))
        ])
        return [body]

# For direct execution / testing
if __name__ == "__main__":
    app.run()
