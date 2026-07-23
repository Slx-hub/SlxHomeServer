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
  "added_at": "2026-07-21",
  "geo_precision": "exact"
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
      - the **street address** — the most precise the page gives (house/block number, street
        or neighborhood, ward/district, city, postal code, country). This — *not* the venue
        name — is what you geocode. Also note the **neighborhood/ward** separately (e.g.
        `Ariake, Koto` / `Akasaka, Minato`); it's the key fallback signal.
      - any **coordinates the page itself provides** — many map-based pages embed a lat/lng in
        a map link (`?q=35.63,139.79`, `/@35.63,139.79`), a `geo:` URI, or JSON. If present and
        plausible, **use them directly** and skip geocoding — they beat anything Nominatim gives.
      - optional **tags** — e.g. `indoor`/`outdoor`, `rainy-day`, `kid-friendly`, `sunset`.

      **If the fetch comes back empty, blocked, or without a real address** — booking.com,
      Airbnb, Google Maps share links, and many hotel sites return a bot wall or a JS shell with
      *no* usable text. **Do not proceed to geocode a name you guessed from the URL slug** — that
      is exactly how pins land on the wrong spot. Instead `WebSearch` for the place's real address
      (e.g. `"<hotel name> address"`), which reliably surfaces the street + ward even when the
      page is blocked, and geocode *that*. For short share links (`booking.com/Share-…`,
      `maps.app.goo.gl/…`) that WebFetch can't follow, resolve the real destination first:
      `curl -sIL "<url>" | grep -i '^location:'`, then fetch/search the resolved page.
   b. **Geocode** with Nominatim (free, keyless). Respect its policy: send a User-Agent and
      keep to ~1 request/second. Query the **address**, most-specific first:
      ```bash
      curl -s -A "SlxTripPlanner/1.0 (slakxs.de)" \
        "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=<url-encoded address>"
      ```
      **Nominatim (OSM) does not index most venues by name** — hotels, restaurants, and shops
      usually return nothing or the wrong thing, and romanized Japanese/Asian *street* addresses
      often fail too. So geocode a **place**, not a business name, and fall back one address level
      at a time, keeping the **most specific result that resolves**:
      `full street address` → `neighborhood/ward + city + country` → `district + city + country`.
      **Stop before bare city/region** — do not fall all the way back to just `"Tokyo"` / a
      country. A city-or-larger query returns a single administrative *centroid* that looks
      precise (7 decimals) but is wrong for a specific venue, and every unresolvable place in that
      city collapses onto the identical point.

      **Reject region-centroid results.** After each query, inspect the result before accepting
      its `lat`/`lon`. Treat it as *not a real location* — and drop to the next fallback (or flag)
      — if any of these hold:
      - `class` is `boundary` and `type` is `administrative` **and** `place_rank <= 16`
        (that's city-level or bigger; a neighborhood/`quarter` is ~20 and is fine as a coarse pin);
      - the `boundingbox` spans more than ~0.5° in either dimension (a whole city/prefecture);
      - the coordinates equal (to ~4 decimals) an existing pin in this file, or the known bad
        Tokyo centroid `35.6768601, 139.7638947`.

      If nothing resolves above city level, add the location with `lat`/`lng` set to `null` and
      flag it in your summary — **a null, honestly-flagged pin is better than a confident wrong
      one.** The app won't pin it until the coordinates are fixed.
   c. **google_maps_url** — prefer a named search for good navigation:
      `https://www.google.com/maps/search/?api=1&query=` + URL-encoded `"<title>, <city>"`.
      If you have no reliable name, fall back to `…?api=1&query=<lat>,<lng>`.
   d. Build a unique **id**: slug of the title; if it collides with an existing id, append
      `-2`, `-3`, …
   e. Set `rating: null`, `notes: ""`, `added_at` = today's date, `tags` as found.
   f. Set **`geo_precision`**: `"exact"` when you pinned a specific address/building (or used
      page-provided coordinates), or `"approximate"` when you could only resolve to a
      neighborhood/ward. The map shows a badge on `"approximate"` pins so the user knows to
      refine them. (Omit or `null` when the pin is unresolved / `lat` is `null`.)

3. **Write the file back** as pretty JSON, UTF-8, **without escaping non-ASCII** (so `¥`, `ō`,
   etc. stay readable). Append new locations; leave existing ones untouched. Prefer writing via
   a small Python one-liner using `json.dump(..., ensure_ascii=False, indent=2)` so encoding and
   structure stay valid, rather than hand-editing JSON.

4. **Report** a short summary: which pins were added (title + category), any duplicates skipped,
   and any that failed geocoding and need a manual coordinate. For each pin, say **how precise**
   the coordinate is — exact (from the page or a resolved street address), approximate
   (neighborhood/ward level), or unresolved (`null`) — so the user knows which pins to trust.
   Give the user the link: `https://slakxs.de/trips?trip=<slug>`.

## Notes

- The file is shared with the running container (both run as uid 1000), so your writes appear on
  the map on the next page load/refresh — no restart needed.
- Never invent coordinates, and never accept a city/region **centroid** as a venue's location
  (see the region-centroid rejection in 2b). If unsure, geocode a more specific address, search
  for the real address, or flag with `null`.
- Keep descriptions tight and useful for trip planning; skip marketing fluff.
