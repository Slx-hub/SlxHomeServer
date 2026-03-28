#!/usr/bin/env python3
"""
Multi-role authentication service for session-based access control.

Roles are configured via AUTH_TOKEN_<ROLE> environment variables, e.g.:
    AUTH_TOKEN_ADMIN=supersecret
    AUTH_TOKEN_GUEST=guestsecret

Role hierarchy is defined in ROLE_HIERARCHY below. A role higher in the list
(lower index) satisfies requirements for all roles below it. i.e. admin can
access anything that requires guest.

Caddy routes declare which role they require:
    forward_auth auth:49999 { uri /verify?role=admin }
"""

import hashlib
import json
import os
import secrets
from datetime import timedelta
from flask import Flask, request, make_response

app = Flask(__name__)

# Ordered from most to least privileged. Admin satisfies any role requirement.
# Add new role names here when you add AUTH_TOKEN_<ROLE> to .env.
#   admin  — full access (main domain + all subdomains)
#   dev    — all subdomains only (git, stoat, ...); no main-domain private paths
#   guest  — stoat.slakxs.de only
ROLE_HIERARCHY = ["admin", "dev", "guest"]

SESSION_COOKIE_NAME = "auth_session"
SESSION_COOKIE_DURATION = timedelta(days=3650)  # ~10 years

# Load tokens and generate a unique session secret for each configured role.
_ROLE_TOKENS: dict[str, str] = {}   # role -> login token
_ROLE_SESSIONS: dict[str, str] = {} # role -> random session cookie value

for _role in ROLE_HIERARCHY:
    _token = os.getenv(f"AUTH_TOKEN_{_role.upper()}", "")
    if _token:
        _ROLE_TOKENS[_role] = _token
        # Derive a stable session secret so cookies survive service restarts.
        _ROLE_SESSIONS[_role] = hashlib.sha256(
            f"auth_session_v1:{_token}".encode()
        ).hexdigest()

if not _ROLE_TOKENS:
    raise ValueError(
        "No role tokens set. Define AUTH_TOKEN_ADMIN (and optionally "
        "AUTH_TOKEN_GUEST, etc.) in your environment."
    )


def _role_for_session(cookie_value: str) -> str | None:
    """Return the role whose session secret matches cookie_value, or None."""
    for role, session_secret in _ROLE_SESSIONS.items():
        if secrets.compare_digest(cookie_value, session_secret):
            return role
    return None


def _role_satisfies(session_role: str, required_role: str) -> bool:
    """Return True if session_role has at least the privilege of required_role."""
    try:
        return ROLE_HIERARCHY.index(session_role) <= ROLE_HIERARCHY.index(required_role)
    except ValueError:
        return False


@app.route("/cookie", methods=["GET", "POST"])
def login():
    """
    Handle login requests. Both GET (for form display) and POST (for submission).
    """
    if request.method == "GET":
        # If the visitor already holds a valid admin session, show the token dashboard.
        existing_session = request.cookies.get(SESSION_COOKIE_NAME, "")
        existing_role = _role_for_session(existing_session) if existing_session else None
        if existing_role and _role_satisfies(existing_role, "admin"):
            rows = ""
            for role in ROLE_HIERARCHY:
                token = _ROLE_TOKENS.get(role)
                if not token:
                    continue
                role_esc = role.replace("&", "&amp;").replace("<", "&lt;")
                token_esc = token.replace("&", "&amp;").replace("<", "&lt;")
                rows += f"""
                <tr>
                    <td><code>{role_esc}</code></td>
                    <td><code id="tok-{role_esc}" class="token">{token_esc}</code></td>
                    <td><button onclick="copy('{role_esc}')">Copy</button></td>
                </tr>"""
            html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Auth - Token Dashboard</title>
    <style>
        body {{ font-family: sans-serif; margin: 50px; }}
        table {{ border-collapse: collapse; }}
        th, td {{ padding: 10px 16px; border: 1px solid #ccc; text-align: left; }}
        th {{ background: #f0f0f0; }}
        code.token {{ font-size: 13px; word-break: break-all; }}
        button {{ padding: 4px 12px; cursor: pointer; }}
        .copied {{ color: green; font-size: 12px; margin-left: 8px; }}
    </style>
</head>
<body>
    <h2>Auth Token Dashboard</h2>
    <p>Logged in as <strong>admin</strong>.</p>
    <table>
        <tr><th>Role</th><th>Login Token</th><th></th></tr>
        {rows}
    </table>
    <script>
        function copy(role) {{
            var tok = document.getElementById('tok-' + role).innerText;
            navigator.clipboard.writeText(tok).then(function() {{
                var btn = event.target;
                var old = btn.innerText;
                btn.innerText = 'Copied!';
                setTimeout(function() {{ btn.innerText = old; }}, 1500);
            }});
        }}
    </script>
</body>
</html>"""
            return html, 200, {"Content-Type": "text/html"}

        # Not authenticated as admin — show the login form.
        return_url = request.args.get("return", "/")
        if not return_url.startswith("/"):
            return_url = "/"
        return_url_attr = return_url.replace('"', '&quot;')
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authentication</title>
            <style>
                body {{ font-family: sans-serif; margin: 50px; }}
                input {{ padding: 8px; font-size: 16px; }}
                button {{ padding: 8px 16px; font-size: 16px; }}
            </style>
        </head>
        <body>
            <form method="post">
                <input type="hidden" name="return" value="{return_url_attr}">
                <label for="token">Access Token:</label><br><br>
                <input type="password" id="token" name="token" size="50" required autofocus><br><br>
                <button type="submit">Authenticate</button>
            </form>
        </body>
        </html>
        """
        return html, 200, {"Content-Type": "text/html"}

    # POST request - find which role this token belongs to
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

    matched_role = None
    for role, role_token in _ROLE_TOKENS.items():
        if secrets.compare_digest(token, role_token):
            matched_role = role
            break

    if matched_role is None:
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
    # Use the ?return= field from the form, fall back to referrer, then root.
    redirect_url = request.form.get("return", "").strip() or request.referrer or "/"
    # Only allow relative paths to prevent open-redirect abuse.
    if not redirect_url.startswith("/"):
        redirect_url = "/"
    redirect_js = json.dumps(redirect_url)  # safely quoted for JS
    response = make_response(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authenticating...</title>
            <script>window.location.href={redirect_js};</script>
        </head>
        <body>
            <p>Authenticating... <a href={redirect_js}>Click here if not redirected</a></p>
        </body>
        </html>
    """, 200)

    # Domain cookie valid for all *.slakxs.de. The value is the role-specific
    # session secret, which /verify then checks against the required role.
    response.set_cookie(
        SESSION_COOKIE_NAME,
        value=_ROLE_SESSIONS[matched_role],
        max_age=int(SESSION_COOKIE_DURATION.total_seconds()),
        httponly=True,
        secure=True,
        samesite="Lax",
        path="/",
        domain=".slakxs.de",
    )

    return response


@app.route("/verify", methods=["GET"])
def verify():
    """
    Internal endpoint for Caddy forward_auth to verify session cookie validity.

    Query param:
        role=<name>  — the minimum role required for this route.
                       Omit to accept any valid session.

    Returns 200 if the session satisfies the required role, 404 otherwise
    (404 so that Caddy passes the status through and the client sees no login
    hint, matching the rest of the site's behaviour).
    """
    session = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not session:
        return "", 404

    session_role = _role_for_session(session)
    if session_role is None:
        return "", 404

    required_role = request.args.get("role", "")
    if required_role and not _role_satisfies(session_role, required_role):
        return "", 404

    return "", 200


@app.route("/healthz", methods=["GET"])
def healthz():
    """Container health endpoint for Docker HEALTHCHECK."""
    return "ok", 200


if __name__ == "__main__":
    # Bind to all interfaces, port 49999
    app.run(host="0.0.0.0", port=49999, debug=False)
