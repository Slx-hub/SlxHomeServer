---
name: review-pins
description: Work through Trip Planner pins flagged needs_review — re-read each source page with the full toolchain (Chrome-impersonating fetch, then the real browser over the CDP tunnel), correct the pin's fields, and clear the flag. Use when the user says "review pins", "fix the review items", "/review-pins", or asks to clean up pins the in-app assistant couldn't place properly.
---

# Review Pins

Pins land in the Trip Planner the moment someone drops a link — that low barrier is
deliberate and must stay. The cost of an unreadable page is paid *here* instead: when the
in-app assistant can't read a source page, or can only geocode it vaguely, it flags the pin
**`needs_review: true`** rather than inventing an address. This skill drains that queue.

`needs_review` is not a rating. The user's `rating` (want/maybe/nah) is their opinion of the
place; this flag is a fact about the data behind the pin. **Never touch the rating** while
reviewing — a pin can be "want to do" and still unverified.

You have tools on the server the in-app assistant does not. That asymmetry is the whole
point of the split.

## Do the work yourself — never via the in-app assistant

**Do not call `/api/chat`.** That endpoint is the Gemini agent embedded in the map, and it
is what produced these pins in the first place: it fetches with a bot User-Agent, gives up
on a 403, and has a daily request quota. Routing a review through it re-runs the exact
failure you are here to fix.

Read and write the trip JSON directly, and use `tools/extract_page.py` for fetching. Every
step below is yours to run.

## The data

- One file per trip: `/data/trip-planner/<trip>.json` (default trip: `japan`).
- Review items are locations with `"needs_review": true`. Most carry a `review_reason`
  saying which failure put them there — read it, it tells you what to fix.
- The backend re-reads the file on every request, so a direct write shows up immediately —
  no container restart.
- Writes must be atomic (`tmp` + `os.replace`), matching `_save_trip` in the backend, so a
  crash mid-write can't corrupt the trip.

List the queue first:

```bash
python3 -c "
import json
d=json.load(open('/data/trip-planner/japan.json'))
for l in d['locations']:
    if l.get('needs_review'):
        print(l['id'], '|', l['title'], '|', l.get('review_reason','?'), '|', l.get('source_url','')[:60])
"
```

## Reading the page

```bash
apps/pages/trip-planner/tools/extract.sh "<url>"
```

It tries a Chrome-TLS-impersonating fetch first, then falls back to the real browser on the
home PC over the CDP tunnel. Output is JSON: `via`, `blocked`, `title`, `jsonld`, `text`,
`attempts`.

**Prefer `jsonld` over `text`.** Travel sites embed schema.org `PostalAddress`, `geo` and
`offers` even when the visible text is nav chrome — it's structured, unambiguous, and needs
no interpretation. Fall back to `text` only when there's no usable JSON-LD.

**But never take the first `PostalAddress` you find.** Pages carry an `Organization` block
for the *publisher* alongside the one for the venue. GetYourGuide pages embed their own
Berlin HQ — `Sonnenburger Str. 73` — and a naive walk grabs it, which geocodes nine Tokyo
pins into Germany. Only trust an address hanging off a place-ish `@type` (`Hotel`,
`Restaurant`, `TouristAttraction`, `LocalBusiness`, `Place`); ignore `Organization`,
`WebSite`, `WebPage`, `BreadcrumbList`. Then sanity-check the country before geocoding — a
result outside Japan is a bug, not a discovery.

**Geocode by venue name, not by street address, for named venues.** An address query returns
whatever premise sits on that lot, which for hotels is routinely the building next door —
that produced five false "errors" of 180–520 m in one pass. Use the address only when the
name is too generic to search.

The CDP fallback needs the tunnel from `tools/Start-ScrapeBrowser.ps1` running on the home
PC. Check before a batch, and if it's down, say so — sites like booking.com and airbnb.com
simply cannot be read without it, and those pins should stay in review rather than be
guessed at:

```bash
curl -s --max-time 5 http://127.0.0.1:9222/json/version || echo "CDP tunnel is down"
```

## Fixing a pin

Fill from what the page actually said. Never from the URL slug — that mistake is why the
pin is in this queue.

| Field | From |
| --- | --- |
| `title` | the venue name, not the article headline |
| `category` | one of the trip's existing keys; `other` if nothing fits |
| `description` | one or two useful sentences, no marketing copy |
| `cost` | **always euro** — `"€136"` exact, `"~€24"` converted, `"Free"`, `""` unknown |
| `lat`/`lng` | geocode the address from JSON-LD (below) |
| `geo_precision` | `"exact"` for a building match, `"approximate"` for neighborhood level |
| `google_maps_url` | `https://www.google.com/maps/search/?api=1&query=<urlencoded address>` |
| `notes` | **never overwrite a non-empty note** — that's the user's own text. Append. |

### Geocoding

Google Places resolves venue names and Japanese block addresses that Nominatim misses:

```bash
cd apps/pages/trip-planner && set -a && . ./.env && set +a && curl -4 -s \
  -X POST "https://places.googleapis.com/v1/places:searchText" \
  -H "Content-Type: application/json" -H "X-Goog-Api-Key: $GOOGLE_MAPS_API_KEY" \
  -H "X-Goog-FieldMask: places.displayName,places.formattedAddress,places.location" \
  -d '{"textQuery":"<venue, street, city>","maxResultCount":1}'
```

`curl -4` is required: the key is IP-restricted to the server's IPv4 address, and an IPv6
request fails with `API_KEY_IP_ADDRESS_BLOCKED`.

Sanity-check the result before writing it. If the returned `formattedAddress` is a
district or city rather than the venue, that's a centroid — mark `geo_precision`
`"approximate"`, or leave the pin in review if it's badly off.

### Clearing the flag

Set `"needs_review": false` and delete any `review_reason`. **Leave `rating` exactly as it
is** — it's the user's judgement, and nothing you did here informs it. Only clear when the
pin is genuinely verified.

## When to leave a pin flagged

Clearing the flag says "this is trustworthy now". Don't say that unless it is. Leave it,
and report why, when:

- the page is unreadable and the CDP tunnel is down (retry when it's up)
- the page loads but never states a location — e.g. GetYourGuide hides per-activity meeting
  points behind the availability widget, so no fetch will ever surface one
- geocoding returns only a city/district centroid
- the source URL is dead or now points somewhere unrelated

If a page gives a reliable venue *name* but no address, it's fine to improve the title and
description while leaving the flag set for its coordinates — update `review_reason` to say
what's still missing. Partial progress beats a false clear.

## Reporting

One compact table at the end: pin, what changed, cleared or still flagged with the reason.
Give the counts (`n cleared, m still in review`). If you moved a pin more than a kilometre,
say so explicitly with the distance — that's the class of error this queue exists to catch,
and the user should see it rather than find it in Tokyo.
