#!/usr/bin/env python3
"""
Simple authentication service for session-based access control.
Validates a token and returns a long-lived session cookie.
"""

import os
import secrets
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, make_response

app = Flask(__name__)

# Master token from environment variable
MASTER_TOKEN = os.getenv("AUTH_TOKEN", "")

if not MASTER_TOKEN:
    raise ValueError("AUTH_TOKEN environment variable not set")

# Session cookie settings
SESSION_COOKIE_NAME = "auth_session"
SESSION_COOKIE_DURATION = timedelta(days=3650)  # ~10 years
SESSION_SECRET = secrets.token_hex(32)


@app.route("/cookie", methods=["GET", "POST"])
def login():
    """
    Handle login requests. Both GET (for form display) and POST (for submission).
    """
    if request.method == "GET":
        # Return a simple HTML form
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authentication</title>
            <style>
                body { font-family: sans-serif; margin: 50px; }
                input { padding: 8px; font-size: 16px; }
                button { padding: 8px 16px; font-size: 16px; }
            </style>
        </head>
        <body>
            <form method="post">
                <label for="token">Access Token:</label><br><br>
                <input type="password" id="token" name="token" size="50" required autofocus><br><br>
                <button type="submit">Authenticate</button>
            </form>
        </body>
        </html>
        """
        return html, 200, {"Content-Type": "text/html"}

    # POST request - validate token
    token = request.form.get("token", "").strip()

    if not token:
        return """
        <!DOCTYPE html>
        <html>
        <head><title>Error</title></head>
        <body>
            <p>Token is required. <a href="/cookie">Try again</a></p>
        </body>
        </html>
        """, 400, {"Content-Type": "text/html"}

    if token != MASTER_TOKEN:
        # Always return 401, never indicate why it failed (security)
        return """
        <!DOCTYPE html>
        <html>
        <head><title>Error</title></head>
        <body>
            <p>Invalid token. <a href="/cookie">Try again</a></p>
        </body>
        </html>
        """, 401, {"Content-Type": "text/html"}

    # Token is valid - create session cookie and redirect
    redirect_url = request.referrer or "/"
    response = make_response(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authenticating...</title>
            <script>window.location.href="{redirect_url}";</script>
        </head>
        <body>
            <p>Authenticating... <a href="{redirect_url}">Click here if not redirected</a></p>
        </body>
        </html>
    """, 200)

    # Set httpOnly, Secure, SameSite cookies
    response.set_cookie(
        SESSION_COOKIE_NAME,
        value=SESSION_SECRET,
        max_age=int(SESSION_COOKIE_DURATION.total_seconds()),
        httponly=True,
        secure=True,  # Only sent over HTTPS
        samesite="Lax",
        path="/",
    )

    return response


@app.route("/verify", methods=["GET"])
def verify():
    """
    Internal endpoint for Caddy to verify session cookie validity.
    Returns 200 if valid, 401 if not.
    """
    session = request.cookies.get(SESSION_COOKIE_NAME)

    if session == SESSION_SECRET:
        return "", 200
    else:
        return "", 401


if __name__ == "__main__":
    # Bind to all interfaces, port 49999
    app.run(host="0.0.0.0", port=49999, debug=False)
