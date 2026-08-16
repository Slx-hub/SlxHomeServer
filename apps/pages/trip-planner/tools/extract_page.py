#!/usr/bin/env python3
"""Read a page as well as this machine possibly can, and print what it found as JSON.

Two strategies, tried in order:

  1. curl_cffi with a Chrome TLS fingerprint. The backend's plain httpx fetch is
     rejected by Cloudflare on both its bot User-Agent and its TLS handshake;
     impersonation clears that class of site (getyourguide, most server-rendered
     travel pages) straight from the server.

  2. The real browser on the home PC, over the CDP tunnel opened by
     tools/Start-ScrapeBrowser.ps1. Needed for sites that are either
     client-rendered (airbnb) or wall off datacenter-ish clients entirely
     (booking, tripadvisor). Only available while that tunnel is up.

JSON-LD is extracted separately from visible text and is strongly preferred by
callers: travel sites embed schema.org PostalAddress/geo/offers even when the
rendered page is a soup of nav chrome, and it needs no interpretation.

Usage:
    python extract_page.py <url> [--cdp-only] [--no-cdp] [--port 9222]

Exit codes: 0 = something usable, 1 = nothing usable (JSON still printed).
"""

import argparse
import json
import re
import sys
import time
import urllib.request

# ── Blocked-page detection ───────────────────────────────────────────────────
# Same intent as the backend's _looks_blocked: a short page, or one carrying
# challenge markers, has no content worth extracting.
_MARKERS = ("just a moment", "captcha", "are you a robot", "verify you are human",
            "enable javascript", "access denied", "aws-waf", "cf-chl", "px-captcha")


def looks_blocked(title: str, text: str) -> bool:
    text = text or ""
    if len(text) >= 400:
        return False
    blob = f"{title} {text}".lower()
    return not text.strip() or any(m in blob for m in _MARKERS)


def parse_html(html: str) -> dict:
    """Split a raw document into title, JSON-LD blocks and visible text."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html[:3_000_000], "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    # Pull JSON-LD before stripping <script>, which would take it with them.
    ld = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            ld.append(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            continue

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg", "form"]):
        tag.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    return {"title": title, "jsonld": ld, "text": text[:8000]}


# ── Strategy 1: impersonated direct fetch ────────────────────────────────────
def fetch_direct(url: str) -> dict:
    from curl_cffi import requests

    r = requests.get(url, impersonate="chrome", timeout=30, allow_redirects=True)
    if r.status_code >= 400:
        return {"error": f"HTTP {r.status_code}"}
    out = parse_html(r.text or "")
    out["final_url"] = str(r.url)
    return out


# ── Strategy 2: the real browser over the CDP tunnel ─────────────────────────
def fetch_cdp(url: str, port: int, settle: float = 4.0) -> dict:
    from websocket import create_connection

    base = f"http://127.0.0.1:{port}"
    try:
        ver = json.load(urllib.request.urlopen(f"{base}/json/version", timeout=8))
    except Exception as e:
        return {"error": f"CDP unreachable on {port} ({e}). Is the tunnel up?"}

    # suppress_origin: Chrome rejects debug sockets carrying a foreign Origin.
    ws = create_connection(ver["webSocketDebuggerUrl"], timeout=120, suppress_origin=True)
    counter = [0]

    def send(method, params=None, sid=None):
        counter[0] += 1
        msg = {"id": counter[0], "method": method, "params": params or {}}
        if sid:
            msg["sessionId"] = sid
        ws.send(json.dumps(msg))
        return counter[0]

    def wait(mid=None, event=None, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            m = json.loads(ws.recv())
            if mid and m.get("id") == mid:
                return m
            if event and m.get("method") == event:
                return m
        raise TimeoutError(f"timed out waiting for {mid or event}")

    tid = None
    try:
        tid = wait(send("Target.createTarget", {"url": "about:blank"}))["result"]["targetId"]
        sid = wait(send("Target.attachToTarget", {"targetId": tid, "flatten": True}))["result"]["sessionId"]
        send("Page.enable", sid=sid)
        send("Page.navigate", {"url": url}, sid=sid)
        try:
            wait(event="Page.loadEventFired", timeout=60)
        except TimeoutError:
            pass  # some pages never fire it; the settle below still gets content
        time.sleep(settle)

        expr = "JSON.stringify({html: document.documentElement.outerHTML, url: location.href})"
        res = wait(send("Runtime.evaluate", {"expression": expr, "returnByValue": True}, sid=sid))
        payload = json.loads(res["result"]["result"]["value"])
    finally:
        # Always close the tab, or a long batch litters the user's browser.
        if tid:
            try:
                send("Target.closeTarget", {"targetId": tid})
                time.sleep(0.2)
            except Exception:
                pass
        ws.close()

    out = parse_html(payload["html"])
    out["final_url"] = payload["url"]
    return out


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--no-cdp", action="store_true", help="direct fetch only")
    ap.add_argument("--cdp-only", action="store_true", help="skip the direct fetch")
    args = ap.parse_args()

    result = {"url": args.url, "via": None, "title": "", "jsonld": [], "text": "",
              "blocked": True, "attempts": []}

    if not args.cdp_only:
        try:
            got = fetch_direct(args.url)
        except Exception as e:
            got = {"error": f"{type(e).__name__}: {e}"}
        if "error" in got:
            result["attempts"].append({"via": "direct", "error": got["error"]})
        else:
            blocked = looks_blocked(got["title"], got["text"])
            result["attempts"].append({
                "via": "direct", "chars": len(got["text"]),
                "jsonld_blocks": len(got["jsonld"]), "blocked": blocked,
            })
            # JSON-LD alone is enough even when the visible text looks thin.
            if not blocked or got["jsonld"]:
                result.update(got, via="direct", blocked=False)

    if result["blocked"] and not args.no_cdp:
        try:
            got = fetch_cdp(args.url, args.port)
        except Exception as e:
            got = {"error": f"{type(e).__name__}: {e}"}
        if "error" in got:
            result["attempts"].append({"via": "cdp", "error": got["error"]})
        else:
            blocked = looks_blocked(got["title"], got["text"])
            result["attempts"].append({
                "via": "cdp", "chars": len(got["text"]),
                "jsonld_blocks": len(got["jsonld"]), "blocked": blocked,
            })
            if not blocked or got["jsonld"]:
                result.update(got, via="cdp", blocked=False)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
