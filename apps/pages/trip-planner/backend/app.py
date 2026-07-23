"""
Trip Planner API.

Serves a fullscreen Leaflet map frontend and a small file-based JSON API for
travel plans. One file per trip lives under DATA_DIR (e.g. japan.json), so new
plans anywhere in the world are created just by dropping in a new file — which
is exactly what the `plan-trip` Claude skill does.

The browser can edit two fields per location (rating + notes); everything else
is authored by the skill. Writes are atomic (temp file + os.replace) and guarded
by a process-wide lock so concurrent PATCHes don't interleave.
"""

import datetime
import ipaddress
import json
import logging
import os
import re
import socket
import threading
import time
import urllib.parse
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Trip Planner API")

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
DEFAULT_TRIP = os.getenv("DEFAULT_TRIP", "japan")

# Trip names map directly to files on disk, so keep them to a safe slug.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# A short lowercase identifier for a custom category/rating key, e.g. "stargazing".
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# Canonical defaults every trip starts with. Trips can layer their own entries
# on top (new keys, or overrides of these same keys to rename/recolor) via the
# set_category/set_rating chat tools below — those live in the trip's own
# "categories"/"ratings" dict, merged over these at read time (see
# _effective_categories/_effective_ratings). Must match frontend/js/config.js
# and the plan-trip skill.
_DEFAULT_CATEGORIES = {
    "food":      {"label": "Food",      "emoji": "🍜", "color": "#ff7043"},
    "activity":  {"label": "Activity",  "emoji": "🎢", "color": "#ab47bc"},
    "monument":  {"label": "Monument",  "emoji": "🏛️", "color": "#8d6e63"},
    "nature":    {"label": "Nature",    "emoji": "🌲", "color": "#66bb6a"},
    "temple":    {"label": "Temple",    "emoji": "⛩️", "color": "#ef5350"},
    "museum":    {"label": "Museum",    "emoji": "🖼️", "color": "#5c6bc0"},
    "viewpoint": {"label": "Viewpoint", "emoji": "🌅", "color": "#ffa726"},
    "shopping":  {"label": "Shopping",  "emoji": "🛍️", "color": "#ec407a"},
    "lodging":   {"label": "Lodging",   "emoji": "🏨", "color": "#26a69a"},
    "transport": {"label": "Transport", "emoji": "🚆", "color": "#78909c"},
    "nightlife": {"label": "Nightlife", "emoji": "🍸", "color": "#7e57c2"},
    "event":     {"label": "Event",     "emoji": "🎊", "color": "#ffca28"},
    "other":     {"label": "Other",     "emoji": "📍", "color": "#90a4ae"},
}
_DEFAULT_RATINGS = {
    "want":  {"label": "Want to do", "emoji": "💚", "color": "#4caf50"},
    "maybe": {"label": "Maybe",      "emoji": "🤔", "color": "#ffc107"},
    "nah":   {"label": "Nah",        "emoji": "🚫", "color": "#f44336"},
}


def _effective_categories(data: dict) -> dict:
    """Default categories, overlaid with this trip's own additions/overrides."""
    merged = dict(_DEFAULT_CATEGORIES)
    merged.update(data.get("categories") or {})
    return merged


def _effective_ratings(data: dict) -> dict:
    """Default ratings, overlaid with this trip's own additions/overrides."""
    merged = dict(_DEFAULT_RATINGS)
    merged.update(data.get("ratings") or {})
    return merged

# Serialising writes avoids two requests clobbering each other mid read-modify-write.
_write_lock = threading.Lock()

# ── Chat assistant config (Gemini via its OpenAI-compatible endpoint) ───────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# gemini-3.5-flash: current free-tier model (2.5-* were pulled for new keys in
# July 2026). Its free tier allows 1500 requests/day — the CHAT_DAILY_LIMIT below.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
).rstrip("/")
# Gemini's free tier is a requests-per-day cap (reset at midnight US Pacific).
# We count model calls locally against it and report % remaining for the day.
# Set this to your model's real free-tier RPD (gemini-3.5-flash = 1500).
CHAT_DAILY_LIMIT = max(1, int(os.getenv("CHAT_DAILY_LIMIT", "1500")))
SKILL_PATH = Path(os.getenv("AGENT_SKILL_PATH", "/app/agent_skill.md"))
# Per-message safety cap on model round-trips (fetch → add → confirm ≈ 3).
MAX_TOOL_ROUNDS = 6
# Non-".json" so it never shows up in the trips glob.
USAGE_PATH = DATA_DIR / "chat-usage.state"
_usage_lock = threading.Lock()

# Gemini's free-tier quota resets at midnight US Pacific — match that so the
# meter lines up with the real reset. Falls back to UTC if tzdata is missing.
try:
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - only if tzdata unavailable
    _PACIFIC = None


# ── Assistant transcript log (rolling daily, keeps N days) ──────────────────
# A human-readable trace of every chat turn: what we send to the model, what it
# sends back, its thinking, each tool call + arguments, and each tool result —
# the same shape Claude Code shows in its transcript. Rotates at local midnight
# and keeps CHAT_LOG_KEEP_DAYS files total (today + the previous days), so the
# log can't grow without bound. Defaults to /app/logs, which compose bind-mounts
# to ./logs next to the app (git-ignored), so the transcript lands in the repo
# tree without being committed.
LOG_DIR = Path(os.getenv("CHAT_LOG_DIR", "/app/logs"))
# "keeps N logs" — total files retained, so backupCount = N - 1 (current + N-1).
CHAT_LOG_KEEP_DAYS = max(1, int(os.getenv("CHAT_LOG_KEEP_DAYS", "5")))
CHAT_LOG_LEVEL = os.getenv("CHAT_LOG_LEVEL", "INFO").upper()


def _build_chat_logger() -> logging.Logger:
    logger = logging.getLogger("trip_planner.chat")
    logger.setLevel(CHAT_LOG_LEVEL)
    logger.propagate = False  # don't double-log through uvicorn's root handlers
    if logger.handlers:  # idempotent — uvicorn reload can import this module twice
        return logger
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = TimedRotatingFileHandler(
            LOG_DIR / "chat.log",
            when="midnight",
            backupCount=CHAT_LOG_KEEP_DAYS - 1,
            encoding="utf-8",
        )
    except OSError:
        # If the log dir isn't writable, fall back to stdout rather than 500ing
        # every chat request — the assistant still works, we just lose the file.
        handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


chatlog = _build_chat_logger()


def _short(value, limit: int = 800) -> str:
    """Compact a value to a single loggable string, truncating long blobs so the
    transcript stays readable and the file stays bounded."""
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = s.replace("\n", " ⏎ ") if len(s) > limit else s
    return s if len(s) <= limit else f"{s[:limit]}… (+{len(s) - limit} chars)"


# ── Helpers ──────────────────────────────────────────────────────────────


def _safe_name(name: str) -> str:
    """Validate a trip name and return it, or raise 400/404 on anything unsafe."""
    name = name.lower()
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid trip name")
    return name


def _trip_path(name: str) -> Path:
    return DATA_DIR / f"{_safe_name(name)}.json"


def _load_trip(name: str) -> dict:
    path = _trip_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Trip '{name}' not found")
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"Trip file is corrupt: {e}")


def _save_trip(name: str, data: dict) -> None:
    """Atomically write the trip file so a crash mid-write can't corrupt it."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _trip_path(name)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


# ── Models ───────────────────────────────────────────────────────────────


class LocationPatch(BaseModel):
    rating: Optional[str] = None  # one of the trip's rating keys, or "" (clears)
    notes: Optional[str] = None


# ── API routes ─────────────────────────────────────────────────────────────


@app.get("/api/healthz")
def healthz():
    """Lightweight liveness endpoint for the Docker HEALTHCHECK."""
    return {"status": "ok"}


@app.get("/api/trips")
def list_trips():
    """List available trips (one JSON file each), plus the default to open."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    trips = []
    for f in sorted(DATA_DIR.glob("*.json")):
        name = f.stem
        title = name
        try:
            title = json.loads(f.read_text()).get("title", name)
        except (json.JSONDecodeError, ValueError):
            pass  # still list it; the detail endpoint will surface the error
        trips.append({"name": name, "title": title})
    return {"trips": trips, "default": DEFAULT_TRIP}


@app.get("/api/trips/{name}")
def get_trip(name: str):
    """Return the full trip document, with categories/ratings resolved to the
    effective (defaults + this trip's own overrides) taxonomy the frontend renders."""
    data = dict(_load_trip(name))
    data["categories"] = _effective_categories(data)
    data["ratings"] = _effective_ratings(data)
    return data


@app.patch("/api/trips/{name}/locations/{loc_id}")
def patch_location(name: str, loc_id: str, patch: LocationPatch):
    """Update the browser-editable fields (rating, notes) of one location."""
    with _write_lock:
        data = _load_trip(name)
        if patch.rating:
            valid = _effective_ratings(data)
            if patch.rating not in valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"rating must be one of {sorted(valid)} or empty",
                )
        loc = next((l for l in data.get("locations", []) if l.get("id") == loc_id), None)
        if loc is None:
            raise HTTPException(status_code=404, detail=f"Location '{loc_id}' not found")
        if patch.rating is not None:
            loc["rating"] = patch.rating or None
        if patch.notes is not None:
            loc["notes"] = patch.notes
        _save_trip(name, data)
    return loc


@app.delete("/api/trips/{name}/locations/{loc_id}")
def delete_location(name: str, loc_id: str):
    """Remove a location from a trip."""
    with _write_lock:
        data = _load_trip(name)
        locs = data.get("locations", [])
        remaining = [l for l in locs if l.get("id") != loc_id]
        if len(remaining) == len(locs):
            raise HTTPException(status_code=404, detail=f"Location '{loc_id}' not found")
        data["locations"] = remaining
        _save_trip(name, data)
    return {"status": "deleted", "id": loc_id}


# ── Chat assistant ─────────────────────────────────────────────────────────
# A small tool-using agent that lets the user edit the open trip in plain
# language from the map's chat panel. It reuses the same JSON store and the
# same category/euro conventions as the plan-trip skill.


# --- Daily usage meter (tracks the free-tier requests-per-day quota) --------


def _day_key() -> str:
    now = datetime.datetime.now(_PACIFIC) if _PACIFIC else datetime.datetime.utcnow()
    return now.strftime("%Y-%m-%d")


def _read_usage() -> dict:
    """Return today's usage, rolling over automatically at the daily reset."""
    try:
        d = json.loads(USAGE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        d = {}
    if d.get("day") != _day_key():
        d = {"day": _day_key(), "used": 0}
    return d


def _usage_snapshot() -> dict:
    d = _read_usage()
    used = int(d.get("used", 0))
    remaining = max(0, CHAT_DAILY_LIMIT - used)
    return {
        "used": used,
        "limit": CHAT_DAILY_LIMIT,
        "remaining": remaining,
        "percent_remaining": round(100 * remaining / CHAT_DAILY_LIMIT),
        "day": d["day"],
        "resets": "midnight US Pacific",
        "configured": bool(GEMINI_API_KEY),
    }


def _bump_usage(n: int) -> None:
    if n <= 0:
        return
    with _usage_lock:
        d = _read_usage()
        d["used"] = int(d.get("used", 0)) + n
        tmp = USAGE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        os.replace(tmp, USAGE_PATH)


# --- Network helpers: fetch a page + geocode (with basic SSRF guard) --------

_UA = "SlxTripPlanner/1.0 (slakxs.de)"


def _is_public_url(url: str) -> bool:
    """Reject anything that isn't http(s) to a public IP (blocks SSRF to LAN/metadata)."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _strip_query(url: str) -> str:
    """Drop the query string and fragment, keeping scheme/host/path."""
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return url
    return urllib.parse.urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def _title_from_url(url: str) -> Optional[str]:
    """Best-effort human venue name from a URL slug, for when the page itself is
    blocked/empty. Booking.com and similar sites put the real name right in the
    path (e.g. /hotel/jp/villa-fontaine-grand-tokyo-ariake.de.html), and a *name*
    from a slug is safe to use — only guessing an *address* from one is unsafe.
    Returns None when the slug carries no real name (short share codes, numeric
    ids, bare hosts)."""
    try:
        path = urllib.parse.urlparse(url).path
    except ValueError:
        return None
    seg = next((s for s in reversed(path.split("/")) if s), "")
    if not seg:
        return None
    seg = seg.split(".", 1)[0].replace("_", "-")  # drop .de.html / .en-gb.html
    words = [w for w in seg.split("-") if w]
    slug = "-".join(words).lower()
    if not words or slug.startswith("share") or len(slug) < 4:
        return None
    if sum(c.isalpha() for c in slug) < 4:  # numeric/id-only slug, not a name
        return None
    return " ".join(w.capitalize() for w in words)


def _looks_blocked(title: str, text: str) -> bool:
    """True if a page came back empty or as a bot-challenge / JS-only shell —
    i.e. it carries no usable content to extract an address from."""
    text = text or ""
    if len(text) >= 400:
        return False
    blob = f"{title} {text}".lower()
    markers = ("captcha", "challenge", "are you a robot", "enable javascript",
               "access denied", "verify you are human", "aws-waf", "cf-chl")
    return not text.strip() or any(m in blob for m in markers)


def _fetch_once(url: str) -> dict:
    """One fetch attempt → {final_url, title, text} or {error}. Validates every hop."""
    cur = url
    try:
        with httpx.Client(follow_redirects=False, timeout=15,
                          headers={"User-Agent": _UA}) as client:
            for _ in range(6):
                if not _is_public_url(cur):
                    return {"error": "URL not allowed"}
                r = client.get(cur)
                if r.is_redirect and "location" in r.headers:
                    cur = str(httpx.URL(cur).join(r.headers["location"]))
                    continue
                break
            else:
                return {"error": "too many redirects"}
    except httpx.HTTPError as e:
        return {"error": f"fetch failed: {e}"}

    if r.status_code >= 400:
        return {"error": f"HTTP {r.status_code}"}
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        return {"error": f"unsupported content-type: {ctype or 'unknown'}"}

    soup = BeautifulSoup(r.text[:2_000_000], "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg", "form"]):
        tag.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    return {"final_url": str(r.url), "title": title, "text": text[:6000]}


def _fetch_page(url: str) -> dict:
    """Fetch a page. If it comes back empty or behind a bot/JS wall, retry once on
    the clean canonical URL (query string + tracking params stripped) — many sites
    (booking.com, etc.) serve real content there but a stub on the noisy link.
    If it's still blocked, say so plainly so the caller asks the user rather than
    inventing an address."""
    res = _fetch_once(url)
    if "error" in res:
        return res
    if _looks_blocked(res.get("title", ""), res.get("text", "")):
        stripped = _strip_query(res.get("final_url") or url)
        if stripped and stripped != (res.get("final_url") or url):
            retry = _fetch_once(stripped)
            if "error" not in retry and len(retry.get("text", "")) > len(res.get("text", "")):
                res = retry
    if _looks_blocked(res.get("title", ""), res.get("text", "")):
        guess = _title_from_url(res.get("final_url") or url)
        note = (
            "This page returned no readable content (bot wall or JS-only page). The URL "
            "slug still gives a reliable venue NAME but NOT a usable address — do not "
            "guess coordinates from the name. Ask the user for the street address or "
            "'lat, lng' (name the place so they know which one), then add/update the pin."
        )
        if guess:
            res["suggested_title"] = guess
            note += f' The venue name from the link is "{guess}" — use it as the title.'
        res["note"] = note
    return res


def _is_region_centroid(hit: dict) -> bool:
    """True if a Nominatim hit is a whole city/prefecture/country rather than a
    specific place. Its coordinate is an administrative *centroid* that looks
    precise but is wrong for a venue — and every unresolvable place in that city
    collapses onto the identical point (the classic 'everything lands on Tokyo'
    bug). A neighborhood ('quarter', place_rank ~20) is coarse but correct-area,
    so it is NOT treated as a centroid."""
    if hit.get("category") == "boundary" and hit.get("type") == "administrative":
        try:
            if int(hit.get("place_rank", 99)) <= 16:  # city-level or bigger
                return True
        except (ValueError, TypeError):
            pass
    bbox = hit.get("boundingbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        try:
            south, north, west, east = (float(x) for x in bbox)
            if abs(north - south) > 0.5 or abs(east - west) > 0.5:  # ~55km+ span
                return True
        except (ValueError, TypeError):
            pass
    return False


# The classic "everything lands on Tokyo" centroid — both Nominatim and Photon
# return this exact point for a bare "Tokyo, Japan". Rejected on sight.
_KNOWN_BAD_CENTROIDS = {(35.6768601, 139.7638947)}

# Photon feature types (properties.type) that are a whole admin area, not a place:
# their coordinate is a centroid. quarter/suburb/etc. are coarse-but-correct-area.
_PHOTON_ADMIN_TYPES = {"city", "county", "state", "country", "region", "province", "continent"}
_PHOTON_PRECISE_TYPES = {"house", "street"}

# Google Maps Platform key (Places API). Optional — when set, Google becomes the
# authoritative geocoder (see _geocode_google); when empty we stay fully keyless
# on Nominatim + Photon. Get a key at https://console.cloud.google.com/ with the
# "Places API (New)" enabled (needs a billing account, but the volume here is
# well inside the free monthly credit).
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# Google Places "types" that denote an administrative area / neighborhood rather
# than a specific venue. A hit tagged with one of these is coarse: it's flagged
# approximate (never "precise"), and refused outright (→ None) when its viewport
# is also region-sized (a bare city/prefecture/country centroid).
_GOOGLE_ADMIN_TYPES = {
    "country", "administrative_area_level_1", "administrative_area_level_2",
    "administrative_area_level_3", "administrative_area_level_4",
    "locality", "postal_code", "postal_town", "neighborhood",
    "sublocality", "sublocality_level_1", "sublocality_level_2",
    "sublocality_level_3", "sublocality_level_4", "sublocality_level_5",
}

_LATLNG_RE = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def _parse_latlng(query: str) -> Optional[dict]:
    """Accept a raw 'lat, lng' string directly — no geocoder needed, and no risk
    of a service mis-parsing coordinates. Returns {lat, lng, precise} or None."""
    m = _LATLNG_RE.match(query or "")
    if not m:
        return None
    lat, lng = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return {"lat": lat, "lng": lng, "precise": True}
    return None


def _is_bad_centroid(lat: float, lng: float) -> bool:
    return any(abs(lat - bl) < 1e-4 and abs(lng - bg) < 1e-4
               for bl, bg in _KNOWN_BAD_CENTROIDS)


def _geocode_google(query: str) -> Optional[dict]:
    """Google Places Text Search (New) → {lat, lng, precise} or None.

    Only runs when GOOGLE_MAPS_API_KEY is set. Unlike the OSM-based geocoders,
    Google resolves businesses/POIs *by name* using the same index that powers
    maps.google.com — so 'Villa Fontaine Grand Tokyo Ariake' lands on the exact
    pin the user sees there, where Nominatim/Photon are off by a block or miss it
    entirely. It handles plain street addresses just as well. A bare region
    ('Tokyo, Japan') comes back as a large-viewport admin hit → we return None so
    it stays an honest null instead of a confident-wrong centroid.

    `precise` is False for a neighborhood/ward-scale hit (viewport a few km) so
    the pin still gets flagged approximate; True for a specific venue/address."""
    if not GOOGLE_MAPS_API_KEY:
        return None
    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers={
                    "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                    "X-Goog-FieldMask":
                        "places.location,places.viewport,places.types",
                },
                json={"textQuery": query, "maxResultCount": 1},
            )
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return None
    places = data.get("places") if isinstance(data, dict) else None
    if not places:
        return None
    place = places[0] if isinstance(places[0], dict) else {}
    loc = place.get("location") or {}
    try:
        lat, lng = float(loc["latitude"]), float(loc["longitude"])
    except (KeyError, ValueError, TypeError):
        return None
    if _is_bad_centroid(lat, lng):
        return None
    types = set(place.get("types") or [])
    # Viewport span sizes the matched thing: a hotel is hundreds of metres
    # (<0.02°), a ward a few km, a city/prefecture much more.
    span = None
    vp = place.get("viewport") or {}
    lo, hi = vp.get("low") or {}, vp.get("high") or {}
    try:
        span = max(abs(float(hi["latitude"]) - float(lo["latitude"])),
                   abs(float(hi["longitude"]) - float(lo["longitude"])))
    except (KeyError, ValueError, TypeError):
        span = None
    # Whole-region hit (bare city/country) → honest null, leave the pin unplaced.
    if span is not None and span > 0.5:
        return None
    if (types & _GOOGLE_ADMIN_TYPES) and (span is None or span > 0.1):
        return None
    precise = not (types & _GOOGLE_ADMIN_TYPES) and (span is None or span <= 0.05)
    return {"lat": lat, "lng": lng, "precise": precise}


def _geocode_nominatim(query: str) -> tuple:
    """Nominatim (OSM) lookup → (hit, bare_region).

    `hit` is the most specific non-centroid result as {lat, lng, precise}, or None
    (`precise` is False for a neighborhood-level admin hit). `bare_region` is True
    when the *top* match is a whole city/prefecture/country centroid — i.e. the
    query denotes a bare region ("Tokyo, Japan"), not a place. The caller uses that
    to refuse a fuzzy Photon "rescue" that would drop a confident-wrong pin."""
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": _UA}) as client:
            r = client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "jsonv2", "limit": 5, "q": query},
            )
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return None, False
    if not isinstance(data, list):
        return None, False
    bare_region = False
    for i, hit in enumerate(data):  # keep the most specific non-centroid hit
        try:
            lat, lng = float(hit["lat"]), float(hit["lon"])
        except (KeyError, ValueError, TypeError):
            continue
        if _is_region_centroid(hit) or _is_bad_centroid(lat, lng):
            if i == 0:
                bare_region = True  # best match for this query is a whole region
            continue
        precise = not (hit.get("category") == "boundary"
                       and hit.get("type") == "administrative")
        return {"lat": lat, "lng": lng, "precise": precise}, bare_region
    return None, bare_region


def _geocode_photon(query: str) -> Optional[dict]:
    """Photon (komoot, keyless, OSM-based) hit → {lat, lng, precise} or None.
    Photon parses messy/romanized street addresses far better than Nominatim —
    e.g. it places 'Ariake 2-1-5, Koto-ku, Tokyo' in the right block where
    Nominatim only finds the neighborhood centroid (or nothing). Same centroid
    guard applies: a bare city still resolves to an admin centroid we must skip."""
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": _UA}) as client:
            r = client.get("https://photon.komoot.io/api",
                           params={"q": query, "limit": 5})
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return None
    for feat in (data.get("features") if isinstance(data, dict) else None) or []:
        props = feat.get("properties", {})
        coords = (feat.get("geometry") or {}).get("coordinates")
        if not (isinstance(coords, list) and len(coords) == 2):
            continue
        try:
            lng, lat = float(coords[0]), float(coords[1])  # GeoJSON is [lng, lat]
        except (ValueError, TypeError):
            continue
        ptype = props.get("type")
        if ptype in _PHOTON_ADMIN_TYPES or _is_bad_centroid(lat, lng):
            continue  # whole city/prefecture/country centroid
        extent = props.get("extent")  # [west, north, east, south]
        if isinstance(extent, list) and len(extent) == 4:
            try:
                w, n, e, s = (float(x) for x in extent)
                if abs(n - s) > 0.5 or abs(e - w) > 0.5:  # spans a whole city+
                    continue
            except (ValueError, TypeError):
                pass
        return {"lat": lat, "lng": lng, "precise": ptype in _PHOTON_PRECISE_TYPES}
    return None


def _geocode(query: str) -> Optional[dict]:
    """Geocoding. Returns {lat, lng, precise} or None.

    A raw 'lat, lng' is used as-is. If GOOGLE_MAPS_API_KEY is set, Google Places
    is authoritative — its data matches maps.google.com and resolves venues by
    name, so whatever it returns wins. Without a key (or when Google finds
    nothing) we fall back to the keyless chain: Nominatim first (strict, good at
    named/admin places), then Photon (much better at messy/romanized street
    addresses, and resolves many venues by name Nominatim can't) whenever
    Nominatim can't return a precise hit. A None here (honestly-flagged, unplaced
    pin) still beats a confident wrong centroid."""
    query = (query or "").strip()
    if not query:
        return None
    coords = _parse_latlng(query)
    if coords:
        return coords
    google = _geocode_google(query)
    if google:
        return google  # Google's data matches maps.google.com — trust it fully.
    nomi, bare_region = _geocode_nominatim(query)
    if nomi and nomi.get("precise"):
        return nomi
    # Don't let Photon "rescue" a bare region ("Tokyo, Japan") — it fuzzy-matches
    # a random POI in that city and reports it as precise, which is exactly the
    # confident-wrong pin we refuse to drop. A null pin is the honest outcome.
    if not bare_region:
        photon = _geocode_photon(query)
        if photon and photon.get("precise"):
            return photon
        if photon and not nomi:
            return photon  # coarse Photon beats nothing when Nominatim found nada
    # Neither is street-precise — return the best coarse hit we have, if any.
    return nomi


# --- Tool implementations (mutate the open trip) ----------------------------


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "loc"


def _unique_id(data: dict, base: str) -> str:
    ids = {l.get("id") for l in data.get("locations", [])}
    if base not in ids:
        return base
    i = 2
    while f"{base}-{i}" in ids:
        i += 1
    return f"{base}-{i}"


def _tool_fetch_page(name: str, args: dict) -> dict:
    return _fetch_page((args.get("url") or "").strip())


def _tool_add_location(name: str, args: dict) -> dict:
    title = (args.get("title") or "").strip()
    if not title:
        return {"error": "title is required"}
    source_url = (args.get("source_url") or "").strip()
    raw_category = (args.get("category") or "").strip()
    city = (args.get("city") or "").strip()

    # Geocode outside the write lock (it makes a network call). Try the specific
    # query, then title+city — but never a bare city, which only ever yields a
    # region centroid (see _geocode / _is_region_centroid).
    geo = None
    for q in (args.get("place_query"), f"{title}, {city}"):
        geo = _geocode(q or "")
        if geo:
            break
    lat = geo["lat"] if geo else None
    lng = geo["lng"] if geo else None

    with _write_lock:
        data = _load_trip(name)
        category = raw_category if raw_category in _effective_categories(data) else "other"
        if source_url:
            for l in data.get("locations", []):
                if l.get("source_url") == source_url:
                    return {"status": "duplicate", "id": l.get("id"), "title": l.get("title")}
        loc_id = _unique_id(data, _slugify(title))
        gmaps_q = (f"{title}, {city}".strip().strip(",")) or title
        loc = {
            "id": loc_id,
            "title": title,
            "category": category,
            "lat": lat,
            "lng": lng,
            "cost": (args.get("cost") or "").strip(),
            "description": (args.get("description") or "").strip(),
            "source_url": source_url,
            "google_maps_url": (
                "https://www.google.com/maps/search/?api=1&query="
                + urllib.parse.quote(gmaps_q)
            ),
            "rating": None,
            "notes": "",
            "tags": args.get("tags") if isinstance(args.get("tags"), list) else [],
            "added_at": datetime.date.today().strftime("%Y-%m-%d"),
            # "exact" | "approximate" (neighborhood-level) — the frontend shows a
            # badge for "approximate" so the user knows to verify the pin.
            "geo_precision": (
                "exact" if (geo and geo.get("precise", True))
                else "approximate" if geo else None
            ),
        }
        data.setdefault("locations", []).append(loc)
        _save_trip(name, data)

    result = {"status": "added", "id": loc_id, "title": title,
              "category": category, "cost": loc["cost"] or None,
              # Explicit signal for the reply guard: a null-coord pin isn't on the
              # map, so the confirmation must say so and ask for an exact location.
              "placed": lat is not None}
    if lat is None:
        result["warning"] = ("could not confidently geocode (OSM can't place venue "
                             "names or bare cities) — pin hidden until coordinates are "
                             "set. Ask the user for a street address, or update_location "
                             "with a place_query of the street/neighborhood.")
    elif not geo.get("precise", True):
        result["warning"] = ("approximate: pinned at neighborhood level, not the exact "
                             "address. Refine with a street address if you have one.")
    return result


def _tool_update_location(name: str, args: dict) -> dict:
    loc_id = (args.get("loc_id") or "").strip()
    if not loc_id:
        return {"error": "loc_id is required"}
    place_query = (args.get("place_query") or "").strip()
    geo = _geocode(place_query) if place_query else None

    with _write_lock:
        data = _load_trip(name)
        loc = next((l for l in data.get("locations", []) if l.get("id") == loc_id), None)
        if loc is None:
            return {"error": f"no location with id '{loc_id}'"}
        changed = []
        for field in ("cost", "source_url", "description", "title", "notes"):
            if isinstance(args.get(field), str):
                loc[field] = args[field] if field == "notes" else args[field].strip()
                changed.append(field)
        if isinstance(args.get("category"), str):
            loc["category"] = args["category"] if args["category"] in _effective_categories(data) else "other"
            changed.append("category")
        if isinstance(args.get("rating"), str):
            r = args["rating"].strip()
            loc["rating"] = r if r in _effective_ratings(data) else None
            changed.append("rating")
        if isinstance(args.get("tags"), list):
            loc["tags"] = args["tags"]
            changed.append("tags")
        if geo:
            loc["lat"], loc["lng"] = geo["lat"], geo["lng"]
            # refresh precision — a new exact address clears an old "approximate" badge
            loc["geo_precision"] = "exact" if geo.get("precise", True) else "approximate"
            changed.append("coords")
        if not changed:
            if place_query:  # they asked to move it but nothing usable came back
                return {"error": ("could not confidently geocode that place_query (OSM "
                                  "can't place venue names or bare cities). Try a street "
                                  "address or neighborhood, or pass raw 'lat, lng'.")}
            return {"error": "nothing to update"}
        _save_trip(name, data)
    result = {"status": "updated", "id": loc_id, "title": loc.get("title"), "changed": changed}
    if geo and not geo.get("precise", True):
        result["warning"] = "approximate: pinned at neighborhood level, not the exact address."
    return result


def _tool_delete_location(name: str, args: dict) -> dict:
    loc_id = (args.get("loc_id") or "").strip()
    with _write_lock:
        data = _load_trip(name)
        locs = data.get("locations", [])
        title = next((l.get("title") for l in locs if l.get("id") == loc_id), None)
        remaining = [l for l in locs if l.get("id") != loc_id]
        if len(remaining) == len(locs):
            return {"error": f"no location with id '{loc_id}'"}
        data["locations"] = remaining
        _save_trip(name, data)
    return {"status": "deleted", "id": loc_id, "title": title}


def _tool_focus_location(name: str, args: dict) -> dict:
    """Read-only: ask the map to pan to and open an existing pin. Changes no
    data — it just resolves the id so chat() can hand it back as focus_id."""
    loc_id = (args.get("loc_id") or "").strip()
    if not loc_id:
        return {"error": "loc_id is required"}
    data = _load_trip(name)
    loc = next((l for l in data.get("locations", []) if l.get("id") == loc_id), None)
    if not loc:
        return {"error": f"no location with id '{loc_id}'"}
    result = {"status": "focus", "id": loc_id, "title": loc.get("title")}
    if loc.get("lat") is None or loc.get("lng") is None:
        result["warning"] = "location has no coordinates; it can't be shown on the map yet"
    return result


def _upsert_taxonomy_entry(store_key: str, defaults: dict, name: str, args: dict) -> dict:
    """Shared create-or-edit logic for set_category/set_rating: creates a new
    key with label+emoji+color, or patches whichever of those fields are given
    for a key that already exists (default or custom) — that's how renaming/
    recoloring an existing type works, not just adding new ones."""
    raw_key = (args.get("key") or "").strip().lower()
    if not _KEY_RE.match(raw_key):
        return {"error": "key must be lowercase letters/digits/underscore, e.g. 'stargazing'"}
    with _write_lock:
        data = _load_trip(name)
        merged = dict(defaults)
        merged.update(data.get(store_key) or {})
        existing = merged.get(raw_key)
        entry = dict(existing) if existing else {}
        for field in ("label", "emoji", "color"):
            v = args.get(field)
            if isinstance(v, str) and v.strip():
                entry[field] = v.strip()
        if not existing:
            missing = [f for f in ("label", "emoji", "color") if f not in entry]
            if missing:
                return {"error": f"new entry needs {missing}"}
        own = dict(data.get(store_key) or {})
        own[raw_key] = entry
        data[store_key] = own
        _save_trip(name, data)
    return {"status": "updated" if existing else "created", "key": raw_key, **entry}


def _tool_set_category(name: str, args: dict) -> dict:
    return _upsert_taxonomy_entry("categories", _DEFAULT_CATEGORIES, name, args)


def _tool_set_rating(name: str, args: dict) -> dict:
    return _upsert_taxonomy_entry("ratings", _DEFAULT_RATINGS, name, args)


# Tools that change the trip file. The reply is only allowed to claim an edit
# when one of these came back with a success status this turn (see
# _reconcile_reply) — fetch_page/focus_location are read-only.
_MUTATING_TOOLS = {
    "add_location", "update_location", "delete_location", "set_category", "set_rating",
}

_TOOL_IMPL = {
    "fetch_page": _tool_fetch_page,
    "add_location": _tool_add_location,
    "update_location": _tool_update_location,
    "delete_location": _tool_delete_location,
    "set_category": _tool_set_category,
    "set_rating": _tool_set_rating,
    "focus_location": _tool_focus_location,
}

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": (
                "Fetch a web page and return its title and readable text. Call this "
                "before add_location whenever the user gives a URL, so you can classify "
                "the place and extract its cost and description."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "The page URL to fetch."}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_location",
            "description": (
                "Add a new place to the open trip. The backend geocodes place_query, "
                "builds the Google Maps link, and deduplicates by source_url."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Concise place name."},
                    "category": {
                        "type": "string",
                        "description": (
                            "One of the trip's existing pin type keys (see context block). "
                            "If none fit, call set_category first to create a new one, or "
                            "pass 'other'."
                        ),
                    },
                    "place_query": {
                        "type": "string",
                        "description": (
                            "Query to geocode. Build the fullest string you can — ideally "
                            "'venue name, street/ward, city, country' (e.g. 'Villa Fontaine "
                            "Grand Tokyo-Ariake, Ariake 2-1-5, Koto, Tokyo, Japan'). The "
                            "geocoder resolves venue NAMES as well as street addresses, so a "
                            "reliable name alone (from the page or a link slug) is a valid "
                            "query when you have no address. Raw 'lat, lng' is also accepted. "
                            "If you have neither a real name nor an address, leave this empty "
                            "rather than guessing; the pin is flagged for the user to fix."
                        ),
                    },
                    "city": {"type": "string", "description": "City/region for the Maps link."},
                    "cost": {"type": "string", "description": "Cost in EURO, e.g. '€18', '~€24', 'Free', or ''."},
                    "description": {"type": "string", "description": "One or two sentences."},
                    "source_url": {"type": "string", "description": "URL the place came from."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "category", "place_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_location",
            "description": (
                "Update fields of an existing location in the open trip. Use the "
                "selected activity's id when the user says 'this'/'here'/'it'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "loc_id": {"type": "string"},
                    "cost": {"type": "string", "description": "Cost in EURO."},
                    "source_url": {"type": "string"},
                    "description": {"type": "string"},
                    "title": {"type": "string"},
                    "category": {
                        "type": "string",
                        "description": (
                            "One of the trip's existing pin type keys (see context block). "
                            "If none fit, call set_category first to create a new one."
                        ),
                    },
                    "rating": {
                        "type": "string",
                        "description": (
                            "One of the trip's existing rating keys (see context block), "
                            "or '' to clear. If none fit, call set_rating first."
                        ),
                    },
                    "notes": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "place_query": {
                        "type": "string",
                        "description": (
                            "If set, re-geocode and move the pin. A 'venue name, street/ward, "
                            "city' string, a street address, or raw 'lat, lng' all work."
                        ),
                    },
                },
                "required": ["loc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_category",
            "description": (
                "Create a new pin type (category) for this trip, or rename/recolor/re-emoji "
                "an existing one (built-in or custom) by passing its existing key. After "
                "creating a type, use update_location to move existing pins onto it — the "
                "user often means 'reclassify these places', not just 'add an empty type'. "
                "Pick an emoji and hex color that's visually distinct from the trip's other "
                "types (see context block)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Short lowercase id, e.g. 'stargazing'. Letters/digits/underscore only.",
                    },
                    "label": {"type": "string", "description": "Display name, e.g. 'Stargazing'. Required when creating."},
                    "emoji": {"type": "string", "description": "One emoji for the pin/chip, e.g. '🌌'. Required when creating."},
                    "color": {"type": "string", "description": "Hex color for the pin/chip, e.g. '#3f51b5'. Required when creating."},
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_rating",
            "description": (
                "Create a new rating option for this trip, or rename/recolor/re-emoji an "
                "existing one (built-in or custom) by passing its existing key."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Short lowercase id, e.g. 'must_see'. Letters/digits/underscore only.",
                    },
                    "label": {"type": "string", "description": "Display name, e.g. 'Must see'. Required when creating."},
                    "emoji": {"type": "string", "description": "One emoji for the chip, e.g. '⭐'. Required when creating."},
                    "color": {"type": "string", "description": "Hex color for the chip, e.g. '#3f51b5'. Required when creating."},
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_location",
            "description": "Remove a location from the open trip.",
            "parameters": {
                "type": "object",
                "properties": {"loc_id": {"type": "string"}},
                "required": ["loc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_location",
            "description": (
                "Pan the map to an existing pin and open its card. Call this when "
                "the user asks where a place is or to show/find/take them to one "
                "(e.g. 'where is Tokyo Skytree', 'show me teamLab'). Read-only — it "
                "changes no data. Match the place by title to its id from the "
                "context block; use the selected activity's id for 'this'/'here'/'it'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"loc_id": {"type": "string"}},
                "required": ["loc_id"],
            },
        },
    },
]


# --- Prompt + per-request context ------------------------------------------

_SKILL_CACHE: Optional[str] = None


def _system_prompt() -> str:
    global _SKILL_CACHE
    if _SKILL_CACHE is None:
        try:
            _SKILL_CACHE = SKILL_PATH.read_text()
        except FileNotFoundError:
            _SKILL_CACHE = "You are a terse assistant that edits a travel map via tools."
    return _SKILL_CACHE


def _context_block(name: str, data: dict, selected_id: Optional[str]) -> str:
    locs = data.get("locations", [])
    cats = _effective_categories(data)
    ratings = _effective_ratings(data)
    lines = [
        "## Context",
        f"Open trip: {name} (title: {data.get('title', name)})",
        f"Today: {datetime.date.today():%Y-%m-%d}",
        "Pin types: " + ", ".join(f"{k} ({v['label']} {v['emoji']} {v['color']})" for k, v in cats.items()),
        "Ratings: " + ", ".join(f"{k} ({v['label']} {v['emoji']} {v['color']})" for k, v in ratings.items()),
    ]
    sel = next((l for l in locs if l.get("id") == selected_id), None) if selected_id else None
    if sel:
        lines.append(
            f'Selected activity: id={sel["id"]} | "{sel.get("title")}" | '
            f'category={sel.get("category")} | cost={sel.get("cost") or "—"} | '
            f'source={"yes" if sel.get("source_url") else "no"}'
        )
        lines.append('"this"/"here"/"it" refer to the selected activity above.')
    else:
        lines.append("No activity is currently selected.")
    lines.append(
        f"Existing locations ({len(locs)}) — use the description/notes/tags to judge "
        "thematic fit when reclassifying places into a new or different type:"
    )
    for l in locs[:200]:
        desc = (l.get("description") or "")[:160]
        notes = (l.get("notes") or "")[:100]
        lines.append(
            f'  - id={l.get("id")} | "{l.get("title")}" | category={l.get("category")} | '
            f'rating={l.get("rating") or "—"} | cost={l.get("cost") or "—"} | '
            f'tags={l.get("tags") or []} | desc="{desc}" | notes="{notes}" | '
            f'src={"y" if l.get("source_url") else "n"}'
        )
    return "\n".join(lines)


def _gemini_chat(messages: list) -> dict:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="Chat is not configured (missing GEMINI_API_KEY).")
    payload = {
        "model": GEMINI_MODEL,
        "messages": messages,
        "tools": _TOOLS,
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    # 503 UNAVAILABLE means Google is temporarily overloaded — retry a couple
    # of times with a short backoff before giving up.
    for attempt in range(3):
        try:
            with httpx.Client(timeout=45) as client:
                r = client.post(
                    f"{GEMINI_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {GEMINI_API_KEY}"},
                    json=payload,
                )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Model request failed: {e}")
        if r.status_code == 503 and attempt < 2:
            time.sleep(1.2 * (attempt + 1))
            continue
        if r.status_code == 503:
            raise HTTPException(status_code=503, detail="Model is busy right now — try again in a moment.")
        if r.status_code == 429:
            raise HTTPException(status_code=429, detail="Free-tier rate limit reached. Try again shortly.")
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Model error {r.status_code}: {r.text[:200]}")
        return r.json()


# --- Models + routes --------------------------------------------------------


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    trip: str
    message: str
    selected_id: Optional[str] = None
    history: Optional[list[ChatTurn]] = None


# The model's confirmations always open with a past-tense action verb (the
# agent_skill "Good replies" — "Added …", "Updated …", "Set cost …"). Anchoring
# to the start keeps this from firing on explanatory prose ("To add a place, …").
_CLAIM_RE = re.compile(
    r"^\s*(added|updated|set|created|deleted|removed|changed|moved|renamed|pinned|saved)\b",
    re.I,
)


def _reconcile_reply(reply: str, turn_actions: list, blocked_fetch: bool, focus_id) -> str:
    """Ground the final reply in what the tools actually did this turn.

    A weak model sometimes fabricates a confirmation ("Added …") after a tool
    errored or was never called — so no pin appears yet the chat claims success
    (exactly the Villa Fontaine case). If nothing actually changed this turn but
    the reply opens like a confirmation, replace it with the honest outcome so
    the assistant can't claim an edit it didn't make."""
    succeeded = [r for _, r in turn_actions if isinstance(r, dict) and "error" not in r]
    # A pin was recorded but has no coordinates → it is NOT on the map. Say so
    # plainly and ask for an exact location, no matter how upbeat the model was;
    # the user shouldn't have to discover it from a "no location" toast.
    unplaced = [r for r in succeeded if r.get("placed") is False]
    if unplaced:
        title = unplaced[-1].get("title") or "that place"
        return (f'Saved "{title}", but I couldn\'t place it on the map from that address — '
                f"send an exact street address or 'lat, lng' and I'll pin it.")
    if succeeded or focus_id:
        return reply  # a real, placed mutation (or a map focus) happened — trust the reply
    if not _CLAIM_RE.match(reply or ""):
        return reply  # not a success claim (a question / info reply) — leave it
    # The reply claims a change that never landed. Say what really happened.
    if blocked_fetch:
        return ("I couldn't read that page (bot wall or JS-only), so nothing was added. "
                "Paste the street address or 'lat, lng' and I'll add it.")
    errors = [r.get("error") for _, r in turn_actions
              if isinstance(r, dict) and r.get("error")]
    if errors:
        return f"That didn't go through — {errors[-1]}"
    return "I didn't change anything — tell me what you'd like me to add or edit."


@app.get("/api/chat/usage")
def chat_usage():
    """Today's usage of the chat assistant against the free-tier daily quota."""
    return _usage_snapshot()


@app.post("/api/chat")
def chat(req: ChatRequest):
    name = _safe_name(req.trip)
    data = _load_trip(name)  # 404 if the trip is gone
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message")

    messages = [{
        "role": "system",
        "content": _system_prompt() + "\n\n" + _context_block(name, data, req.selected_id),
    }]
    for turn in (req.history or [])[-6:]:
        if turn.role in ("user", "assistant") and turn.content:
            messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": message})

    chatlog.info("─" * 68)
    chatlog.info(
        "REQUEST  trip=%s  selected=%s  history=%d  model=%s",
        name, req.selected_id or "—", len(req.history or []), GEMINI_MODEL,
    )
    chatlog.info("👤 user: %s", _short(message, 2000))
    # The system prompt + full context block is large and identical-ish every
    # turn, so it's DEBUG-only — flip CHAT_LOG_LEVEL=DEBUG to capture what we
    # actually send the model.
    chatlog.debug("→ system+context:\n%s", messages[0]["content"])

    model_calls = 0
    reply = ""
    # The pin the map should jump to afterwards: the last place the turn added
    # (or matched as a duplicate), or one the model explicitly asked to show via
    # focus_location ("where is X"). Lets the frontend surface that pin instead
    # of leaving it off-screen. Plain edits/deletes don't set it, so those don't
    # yank the map around.
    focus_id = None
    # Ground truth for _reconcile_reply: every mutating tool result this turn,
    # and whether a fetch came back blocked. Lets us catch a fabricated
    # "Added …" reply when no tool actually changed anything.
    turn_actions: list = []
    blocked_fetch = False
    try:
        for round_no in range(1, MAX_TOOL_ROUNDS + 1):
            chatlog.debug("↑ round %d → model (%d messages)", round_no, len(messages))
            resp = _gemini_chat(messages)
            model_calls += 1
            choice = resp["choices"][0]["message"]
            tool_calls = choice.get("tool_calls") or []
            content = (choice.get("content") or "").strip()
            # The model's prose is either its running commentary before acting
            # (thinking, when it also calls tools) or its final answer.
            if content:
                label = "💭 assistant (thinking)" if tool_calls else "💬 assistant"
                chatlog.info("%s: %s", label, _short(content, 2000))
            assistant_msg = {"role": "assistant", "content": choice.get("content") or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if not tool_calls:
                reply = content
                break

            for tc in tool_calls:
                fn = tc.get("function", {}).get("name", "")
                raw_args = tc.get("function", {}).get("arguments") or "{}"
                try:
                    fargs = json.loads(raw_args)
                except (json.JSONDecodeError, ValueError):
                    fargs = {}
                chatlog.info("🔧 %s(%s)", fn, _short(fargs, 1000))
                impl = _TOOL_IMPL.get(fn)
                try:
                    result = impl(name, fargs) if impl else {"error": f"unknown tool '{fn}'"}
                except HTTPException as e:
                    result = {"error": e.detail}
                except Exception as e:  # keep the loop alive; let the model recover/apologise
                    result = {"error": str(e)}
                chatlog.info("   ↳ %s → %s", fn, _short(result, 1000))
                if fn in _MUTATING_TOOLS:
                    turn_actions.append((fn, result))
                elif fn == "fetch_page" and isinstance(result, dict) and result.get("note"):
                    blocked_fetch = True
                if (isinstance(result, dict)
                        and ((fn == "add_location" and result.get("status") in ("added", "duplicate"))
                             or (fn == "focus_location" and result.get("status") == "focus"))):
                    focus_id = result.get("id") or focus_id
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": json.dumps(result, ensure_ascii=False),
                })
        else:
            reply = "That needed too many steps — try rephrasing."
            chatlog.warning("⚠️ hit MAX_TOOL_ROUNDS (%d) without a final reply", MAX_TOOL_ROUNDS)
    except HTTPException as e:
        chatlog.error("❌ aborted: HTTP %s — %s", e.status_code, e.detail)
        raise
    except Exception as e:  # pragma: no cover - defensive; re-raised for FastAPI
        chatlog.exception("❌ aborted: unexpected error: %s", e)
        raise
    finally:
        _bump_usage(model_calls)

    corrected = _reconcile_reply(reply, turn_actions, blocked_fetch, focus_id)
    if corrected != reply:
        chatlog.warning(
            "🩹 reply corrected (claimed success but nothing changed): %s → %s",
            _short(reply, 300), _short(corrected, 300),
        )
        reply = corrected

    chatlog.info(
        "✅ done  model_calls=%d  focus=%s  reply=%s",
        model_calls, focus_id or "—", _short(reply or "Done.", 1500),
    )
    return {"reply": reply or "Done.", "usage": _usage_snapshot(), "focus_id": focus_id}


# ── Frontend ─────────────────────────────────────────────────────────────
# Mounted last so the /api/* routes above take precedence.
_static = StaticFiles(directory="/app/static", html=True)


@app.middleware("http")
async def _no_cache_static(request, call_next):
    """Force revalidation on every static asset load. This is a low-traffic
    personal app that gets edited and redeployed often; without this, browsers
    happily serve a stale index.html/app.js from heuristic cache after a
    redeploy (ETag/Last-Modified alone don't stop that)."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/", _static, name="static")
