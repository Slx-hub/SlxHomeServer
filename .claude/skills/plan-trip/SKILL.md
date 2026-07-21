---
name: plan-trip
description: Turn a batch of links (attractions, restaurants, viewpoints, etc.) into pins on the Trip Planner map at slakxs.de/trips. Fetches each page, classifies it, extracts cost + a short description, geocodes the location, adds a Google Maps navigation link, and appends it to a per-trip JSON file. Use when the user shares travel links to add to a trip, or says "plan trip", "add to my <place> trip", or "/plan-trip".
---

# Plan Trip

You funnel links the user found into the Trip Planner web app (`apps/pages/trip-planner`,
served at `slakxs.de/trips`). Each link becomes a map pin. Data is plain JSON, one file per
trip, under `/data/trip-planner/<trip>.json`.

## Inputs

The user gives you a **trip name** and one or more **links**. Examples:
- `/plan-trip japan <url> <url> …`
- "add these to my japan trip: <url>, <url>"

If no trip name is given, ask for a short one (e.g. `japan`, `portugal-2027`). Slugify it to
`[a-z0-9_-]` for the filename; keep a nicer human title (e.g. "Japan 2026") inside the file.

## Data location & file shape

- Directory: `/data/trip-planner/` — create it if missing: `mkdir -p /data/trip-planner`
- File: `/data/trip-planner/<slug>.json`. If it doesn't exist, create it:
  ```json
  { "title": "Japan 2026", "locations": [] }
  ```
  Do **not** set `center`/`zoom` — the map auto-fits to all pins when they're absent.

Each location object (the contract the web app reads):
```json
{
  "id": "teamlab-planets",
  "title": "teamLab Planets",
  "category": "activity",
  "lat": 35.6493, "lng": 139.7901,
  "cost": "¥3900",
  "description": "Immersive walk-through digital art museum; you wade through water.",
  "source_url": "https://…",
  "google_maps_url": "https://www.google.com/maps/search/?api=1&query=teamLab%20Planets%2C%20Tokyo",
  "rating": null,
  "notes": "",
  "tags": ["indoor", "rainy-day"],
  "added_at": "2026-07-21"
}
```

## Categories (pick exactly one; drives the pin icon + filter)

Built-in defaults (must match `backend/app.py` `_DEFAULT_CATEGORIES` / `frontend/js/config.js`):

`food` · `activity` · `monument` · `nature` · `temple` · `museum` · `viewpoint` ·
`shopping` · `lodging` · `transport` · `nightlife` · `event` · `other`

Trips can also have their **own** categories/ratings — a `categories`/`ratings` object at the
top of the trip file, added either by the in-app chat assistant (`set_category`/`set_rating`
tools) or by you. **Check the trip file's own `categories`/`ratings` first** — a location might
belong to a type this trip already added (e.g. `stargazing`) that isn't in the built-in list
above. If nothing built-in or already-custom fits and the user is clearly asking for a new kind
of pin (not just a one-off place — use `other` for those), add an entry yourself in the same
shape the assistant would:
```json
"categories": { "stargazing": { "label": "Stargazing", "emoji": "🌌", "color": "#3f51b5" } }
```
Pick a `color` that's visually distinct from the trip's other types.

## Currency — always store `cost` in euro

Whatever currency the page quotes, convert it to **euro** before writing `cost`. Day-accurate
rates aren't needed — a rough, well-known rate is fine. Round to a clean number and prefix `~`
to signal it's approximate, e.g. `¥3900 → "~€24"`, `$30 → "~€28"`, `£12 → "~€14"`.
Keep `"Free"` as-is, and use a range when the page gives one (`"~€15–20"`). If you're unsure of
the rate, do a quick lookup, but don't block on precision.

## Procedure

1. **Read the existing file** (if any) so you can dedupe and never clobber the user's own
   `rating`/`notes` on locations already present. Get today's date once: `date +%F`.

2. **For each link** (skip any whose `source_url` already exists in the file):
   a. `WebFetch` the page. Extract:
      - **title** — the concise place name (not the article headline). e.g. "Fushimi Inari Shrine".
      - **category** — from the list above.
      - **cost** — admission/price if stated, **always converted to euro** (see below);
        else `""`.
      - **description** — one or two sentences on what it is / why it's cool.
      - a **place string** to geocode — the most specific name + city/region you can, e.g.
        `"teamLab Planets, Toyosu, Tokyo"`.
      - optional **tags** — e.g. `indoor`/`outdoor`, `rainy-day`, `kid-friendly`, `sunset`.
   b. **Geocode** with Nominatim (free, keyless). Respect its policy: send a User-Agent and
      keep to ~1 request/second.
      ```bash
      curl -s -A "SlxTripPlanner/1.0 (slakxs.de)" \
        "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=<url-encoded place string>"
      ```
      Take `lat`/`lon` from the first result. If it returns nothing, retry with a broader query
      (drop the venue, keep city + country). If it still fails, add the location with
      `lat`/`lng` set to `null`, and flag it in your summary — the app won't pin it until the
      coordinates are fixed.
   c. **google_maps_url** — prefer a named search for good navigation:
      `https://www.google.com/maps/search/?api=1&query=` + URL-encoded `"<title>, <city>"`.
      If you have no reliable name, fall back to `…?api=1&query=<lat>,<lng>`.
   d. Build a unique **id**: slug of the title; if it collides with an existing id, append
      `-2`, `-3`, …
   e. Set `rating: null`, `notes: ""`, `added_at` = today's date, `tags` as found.

3. **Write the file back** as pretty JSON, UTF-8, **without escaping non-ASCII** (so `¥`, `ō`,
   etc. stay readable). Append new locations; leave existing ones untouched. Prefer writing via
   a small Python one-liner using `json.dump(..., ensure_ascii=False, indent=2)` so encoding and
   structure stay valid, rather than hand-editing JSON.

4. **Report** a short summary: which pins were added (title + category), any duplicates skipped,
   and any that failed geocoding and need a manual coordinate. Give the user the link:
   `https://slakxs.de/trips?trip=<slug>`.

## Notes

- The file is shared with the running container (both run as uid 1000), so your writes appear on
  the map on the next page load/refresh — no restart needed.
- Never invent coordinates. If unsure, geocode or flag it.
- Keep descriptions tight and useful for trip planning; skip marketing fluff.
