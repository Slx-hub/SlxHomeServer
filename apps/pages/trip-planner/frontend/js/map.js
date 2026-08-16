/**
 * Leaflet map wrapper: CARTO Voyager basemap, category-coloured pins, and a
 * per-pin popup card (cost / description / source / Google Maps link + the
 * editable rating & notes that write back to the API).
 */
import { DEFAULT_CATEGORIES, DEFAULT_RATINGS } from './config.js';
import { fmtSpan, isIso, locCoversDay, locSpan } from './dates.js';

// Every pin card is exactly this wide: passing it as both minWidth and maxWidth
// makes Leaflet skip shrink-to-fit, so cards don't resize with their text.
const CARD_WIDTH = 294;

const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const CARTO_ATTR = OSM_ATTR + ' &copy; <a href="https://carto.com/attributions">CARTO</a>';

/** Selectable basemaps. Carto = styled streets (no satellite); Esri = imagery. */
function makeBaseLayers() {
    const carto = (style, opts = {}) => L.tileLayer(
        `https://{s}.basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}{r}.png`,
        { attribution: CARTO_ATTR, subdomains: 'abcd', maxZoom: 20, ...opts },
    );
    return {
        'Voyager': carto('voyager'),
        // Same Voyager tiles, softened via a CSS filter (see .tiles-dim) — a
        // muted dusk tone between bright Voyager and the near-black Dark.
        'Voyager Dim': carto('voyager', { className: 'tiles-dim' }),
        'Light': carto('light_all'),
        'Dark': carto('dark_all'),
        'Satellite': L.tileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            { attribution: 'Imagery &copy; <a href="https://www.esri.com/">Esri</a>', maxZoom: 19 },
        ),
    };
}

/**
 * Transparent overlays drawn on top of the basemap. OpenRailwayMap renders
 * every railway from OSM data — including high-speed lines like the Shinkansen.
 */
function makeOverlays() {
    return {
        '🚄 Railways': L.tileLayer(
            'https://{s}.tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png',
            {
                attribution: 'Rail data &copy; <a href="https://www.openrailwaymap.org/">OpenRailwayMap</a>',
                subdomains: 'abc',
                minZoom: 2,
                maxZoom: 19,
                opacity: 0.85,
            },
        ),
    };
}

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function gmapsUrl(loc) {
    if (loc.google_maps_url) return loc.google_maps_url;
    return `https://www.google.com/maps/search/?api=1&query=${loc.lat},${loc.lng}`;
}

export class TripMap {
    /**
     * @param {string} elId  container element id
     * @param {{api, getTripName:()=>string, showToast:Function, onChange:Function}} deps
     */
    constructor(elId, deps) {
        this.deps = deps;
        // Overwritten per-trip in render() with the trip's own taxonomy (API
        // response merges these same defaults with any custom types/ratings).
        this.categories = DEFAULT_CATEGORIES;
        this.ratings = DEFAULT_RATINGS;
        this.map = L.map(elId, { zoomControl: true, worldCopyJump: true });

        const baseLayers = makeBaseLayers();
        const overlays = makeOverlays();
        baseLayers['Voyager Dim'].addTo(this.map);   // default basemap
        L.control.layers(baseLayers, overlays, { collapsed: true }).addTo(this.map);

        // locId -> { marker, loc, visible }
        this._entries = new Map();
        this._filter = () => true;
        // Day isolation (calendar): an ISO day, or null for "show every day".
        // AND-ed with the filter predicate above in _applyFilter.
        this._day = null;
        this._preDayView = null;   // view to restore when day isolation is cleared
        // The trip's travel window, { start, end } ISO — bounds the date inputs.
        this._window = null;
        // The last opened pin — used as context by the chat assistant ("this").
        this._selected = null;

        this.map.on('popupopen', (e) => this._wirePopup(e.popup));
        // Popup closed (tap elsewhere, ✕, or another pin taking its place) —
        // drop the chat context. popupclose always fires before the next
        // popupopen (Leaflet closes the old popup before opening a new one),
        // so this can't clobber a freshly selected pin.
        this.map.on('popupclose', () => {
            this._selected = null;
            // Tell the chat panel right away — it only re-reads getSelected()
            // on its own open/send events, so without this the label would
            // sit stale until one of those happened to fire.
            this.deps.onSelect?.(null);
        });
    }

    /** The activity whose popup was last opened (chat context), or null. */
    getSelected() {
        return this._selected;
    }

    /** Explicitly forget the current selection (chat "ignore selection"). */
    clearSelected() {
        this._selected = null;
    }

    /**
     * Rebuild all markers for a trip. By default frames all pins; pass
     * { preserveView: true } to keep the current center/zoom (used after a
     * chat edit so the map doesn't jump around).
     */
    render(trip, { preserveView = false } = {}) {
        this.categories = trip.categories || DEFAULT_CATEGORIES;
        this.ratings = trip.ratings || DEFAULT_RATINGS;
        this._window = isIso(trip.start_date)
            ? {
                start: trip.start_date,
                end: isIso(trip.end_date) && trip.end_date >= trip.start_date
                    ? trip.end_date : trip.start_date,
            }
            : null;

        const savedCenter = preserveView ? this.map.getCenter() : null;
        const savedZoom = preserveView ? this.map.getZoom() : null;

        this._entries.forEach((e) => this.map.removeLayer(e.marker));
        this._entries.clear();

        for (const loc of trip.locations || []) {
            if (loc.lat == null || loc.lng == null) continue;
            const marker = L.marker([loc.lat, loc.lng], { icon: this._icon(loc) });
            marker.bindPopup(() => this._popupHtml(this._entries.get(loc.id).loc), {
                minWidth: CARD_WIDTH,
                maxWidth: CARD_WIDTH,
                autoPanPadding: [24, 24],
            });
            // visible:false — the marker isn't on the map yet; _applyFilter()
            // below adds the ones the current filter allows.
            this._entries.set(loc.id, { marker, loc, visible: false });
        }

        this._applyFilter();

        // Keep the selected reference only if that pin still exists.
        if (this._selected && !this._entries.has(this._selected.id)) {
            this._selected = null;
        }

        if (preserveView && savedCenter) {
            this.map.setView(savedCenter, savedZoom);   // refresh in place, no jump
        } else if (Array.isArray(trip.center) && trip.center.length === 2) {
            this.map.setView(trip.center, trip.zoom || 6);
        } else {
            this.fitAll();
        }
    }

    /**
     * Center on a single pin and open its popup (deep link support, e.g.
     * `?trip=japan&pin=ninja-tokyo`). Returns false if the id isn't found.
     */
    openPin(id, { focus = true } = {}) {
        const entry = this._entries.get(id);
        if (!entry) return false;
        if (!entry.visible) {
            this.map.addLayer(entry.marker);
            entry.visible = true;
        }
        if (focus) this.map.setView(entry.marker.getLatLng(), Math.max(this.map.getZoom(), 15));
        entry.marker.openPopup();
        return true;
    }

    fitAll() {
        const pts = [...this._entries.values()].map((e) => e.marker.getLatLng());
        if (pts.length) {
            this.map.fitBounds(L.latLngBounds(pts).pad(0.15));
        } else {
            this.map.setView([20, 0], 2);
        }
    }

    /** Install a predicate `(loc) => bool`; hidden pins leave the map. */
    setFilter(fn) {
        this._filter = fn;
        this._applyFilter();
    }

    /** The trip's travel window ({ start, end } ISO) or null. */
    tripWindow() {
        return this._window;
    }

    /** The day currently isolated on the map, or null. */
    dayFilter() {
        return this._day;
    }

    /**
     * Isolate one day: only pins scheduled on it stay on the map, and the view
     * frames them. Passing null puts every pin back and returns to the view the
     * map had before the day was picked — so tapping a day twice is a clean
     * undo. `restoreView: false` skips that (trip switches, which reframe anyway).
     */
    setDayFilter(day, { restoreView = true } = {}) {
        const next = day || null;
        if (next === this._day) return;
        if (next && !this._day) {
            this._preDayView = { center: this.map.getCenter(), zoom: this.map.getZoom() };
        }
        this._day = next;
        this._applyFilter();

        if (next) {
            const pts = [...this._entries.values()]
                .filter((e) => e.visible)
                .map((e) => e.marker.getLatLng());
            // fitBounds on a single point zooms to max — set the view instead.
            if (pts.length === 1) this.map.setView(pts[0], Math.max(this.map.getZoom(), 14));
            else if (pts.length) this.map.fitBounds(L.latLngBounds(pts).pad(0.25));
        } else if (restoreView && this._preDayView) {
            this.map.setView(this._preDayView.center, this._preDayView.zoom);
        }
        if (!next) this._preDayView = null;
    }

    _applyFilter() {
        for (const e of this._entries.values()) {
            const show = this._filter(e.loc)
                && (!this._day || locCoversDay(e.loc, this._day));
            if (show && !e.visible) this.map.addLayer(e.marker);
            else if (!show && e.visible) this.map.removeLayer(e.marker);
            e.visible = show;
        }
    }

    /** Current locations (used by the filter panel to render counts). */
    locations() {
        return [...this._entries.values()].map((e) => e.loc);
    }

    /**
     * Locations that are both filter-visible AND inside the current viewport.
     * Computed on demand (cheap: one bounds check per marker) so the list view
     * can stay lazy — the app only calls this while the drawer is open.
     */
    visibleInView() {
        const bounds = this.map.getBounds();
        const out = [];
        for (const e of this._entries.values()) {
            if (e.visible && bounds.contains(e.marker.getLatLng())) out.push(e.loc);
        }
        return out;
    }

    /** Subscribe to viewport changes (pan/zoom settled). Returns an unsubscribe. */
    onViewChange(cb) {
        this.map.on('moveend zoomend', cb);
        return () => this.map.off('moveend zoomend', cb);
    }

    /** Public taxonomy lookups for the list view (category always resolves). */
    categoryMeta(key) { return this._category(key); }
    ratingMeta(key) { return this.ratings[key] || null; }

    _category(key) {
        return this.categories[key] || this.categories.other || DEFAULT_CATEGORIES.other;
    }

    _icon(loc) {
        const c = this._category(loc.category);
        const ring = loc.rating && this.ratings[loc.rating] ? this.ratings[loc.rating].color : 'transparent';
        const html =
            `<div class="pin" style="--pin-color:${c.color};--ring:${ring}">` +
            `<span class="pin-emoji">${c.emoji}</span></div>`;
        return L.divIcon({
            html,
            className: 'pin-wrap',
            iconSize: [34, 44],
            iconAnchor: [17, 42],
            popupAnchor: [0, -38],
        });
    }

    /**
     * The "when" row of a pin card: just the two date pickers — the day, and the
     * last day for something that spans several (a stay). They already render
     * the dates, so there's no separate date label. min/max bound them to the
     * trip's travel window, which also greys out every non-trip day in the
     * native picker.
     */
    _whenHtml(loc) {
        const w = this._window;
        const bounds = w ? ` min="${w.start}" max="${w.end}"` : '';
        return (
            `<div class="pop-when">` +
                `<input type="date" class="pop-date" aria-label="Day this is planned for"` +
                    ` title="Day this is planned for" value="${esc(loc.date || '')}"${bounds}>` +
                `<span class="pop-when-sep" aria-hidden="true">-</span>` +
                `<input type="date" class="pop-date-end" aria-label="Last day of a stay"` +
                    ` title="Last day — only for a multi-day stay"` +
                    ` value="${esc(loc.date_end || '')}"${bounds}>` +
            `</div>`
        );
    }

    _popupHtml(loc) {
        const c = this._category(loc.category);
        const ratingBtns = Object.entries(this.ratings)
            .map(([key, r]) => (
                `<button class="rate-btn ${loc.rating === key ? 'active' : ''}" data-rate="${key}" ` +
                `style="--rc:${r.color}" type="button">${r.emoji} ${esc(r.label)}</button>`
            ))
            .join('');

        return (
            `<div class="pop" data-loc="${esc(loc.id)}">` +
                `<div class="pop-head">` +
                    `<span class="pop-cat" style="--c:${c.color}">${c.emoji} ${esc(c.label)}</span>` +
                    (loc.cost ? `<span class="pop-cost">${esc(loc.cost)}</span>` : '') +
                `</div>` +
                `<h3 class="pop-title">${esc(loc.title)}</h3>` +
                this._whenHtml(loc) +
                (loc.description ? `<p class="pop-desc">${esc(loc.description)}</p>` : '') +
                (loc.geo_precision === 'approximate'
                    ? `<p class="pop-approx" title="This pin was placed at neighborhood level, not the exact address. Ask the assistant to refine it with a street address.">📍 Approximate location — neighborhood only</p>`
                    : '') +
                (loc.needs_review
                    ? `<p class="pop-approx" title="${esc(loc.review_reason || 'Queued for verification.')}">🔍 Unverified — queued for review</p>`
                    : '') +
                `<div class="pop-links">` +
                    `<a class="pop-link gmaps" href="${esc(gmapsUrl(loc))}" target="_blank" rel="noopener">🧭 Google Maps</a>` +
                    (loc.source_url
                        ? `<a class="pop-link src" href="${esc(loc.source_url)}" target="_blank" rel="noopener">🔗 Source</a>`
                        : '') +
                    `<button class="pop-link share" type="button" title="Copy a link to this pin">🔗 Share</button>` +
                `</div>` +
                `<div class="rate-row">${ratingBtns}</div>` +
                `<textarea class="pop-notes" rows="2" placeholder="Notes — e.g. hard to get to, rainy-day option…">${esc(loc.notes)}</textarea>` +
                `<button class="pop-delete" type="button" title="Remove this pin">🗑 Remove</button>` +
            `</div>`
        );
    }

    _wirePopup(popup) {
        const root = popup.getElement()?.querySelector('.pop');
        if (!root) return;
        const locId = root.getAttribute('data-loc');
        const entry = this._entries.get(locId);
        if (!entry) return;
        const { api, getTripName, showToast, onChange, onSelect } = this.deps;
        const trip = getTripName();

        // Remember this as the chat's "selected activity" context.
        this._selected = entry.loc;
        onSelect?.(entry.loc);

        // Rating buttons
        root.querySelectorAll('.rate-btn').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const key = btn.getAttribute('data-rate');
                const next = entry.loc.rating === key ? '' : key; // click active = clear
                try {
                    await api.patchLocation(trip, locId, { rating: next });
                    entry.loc.rating = next || null;
                    root.querySelectorAll('.rate-btn').forEach((b) =>
                        b.classList.toggle('active', b.getAttribute('data-rate') === next));
                    entry.marker.setIcon(this._icon(entry.loc));
                    onChange?.();
                } catch (err) {
                    showToast(`Save failed: ${err.message}`, 'error');
                }
            });
        });

        // Schedule: either picker saves both fields, so setting a start and an
        // end in one go can't race two half-written patches against each other.
        // (Nothing here may call popup.update() — with a function content source
        // that re-runs _popupHtml and throws away this wiring.)
        const dateEl = root.querySelector('.pop-date');
        const dateEndEl = root.querySelector('.pop-date-end');
        const saveDates = async () => {
            const patch = { date: dateEl.value, date_end: dateEndEl.value };
            if (patch.date === (entry.loc.date || '')
                && patch.date_end === (entry.loc.date_end || '')) return;
            try {
                const saved = await api.patchLocation(trip, locId, patch);
                // The backend normalises (an end before the start gets swapped, a
                // one-day range collapses) — mirror what it actually stored.
                entry.loc.date = saved.date || null;
                entry.loc.date_end = saved.date_end || null;
                dateEl.value = entry.loc.date || '';
                dateEndEl.value = entry.loc.date_end || '';
                onChange?.();
                // The pickers show the day; the toast adds the weekday and, for a
                // stay, how many nights it works out to.
                showToast(locSpan(entry.loc)
                    ? `Scheduled: ${fmtSpan(entry.loc)}`
                    : 'Unscheduled', 'ok');
            } catch (err) {
                dateEl.value = entry.loc.date || '';
                dateEndEl.value = entry.loc.date_end || '';
                showToast(`Save failed: ${err.message}`, 'error', 4000);
            }
        };
        dateEl.addEventListener('change', saveDates);
        dateEndEl.addEventListener('change', saveDates);

        // Notes autosave on blur (only if changed)
        const notes = root.querySelector('.pop-notes');
        notes.addEventListener('blur', async () => {
            if (notes.value === (entry.loc.notes || '')) return;
            try {
                await api.patchLocation(trip, locId, { notes: notes.value });
                entry.loc.notes = notes.value;
                showToast('Notes saved', 'ok');
            } catch (err) {
                showToast(`Save failed: ${err.message}`, 'error');
            }
        });

        // Share — copy a deep link that reopens this pin (?focus_location=…).
        root.querySelector('.pop-link.share').addEventListener('click', async () => {
            const url = new URL(window.location);
            url.searchParams.set('trip', trip);
            url.searchParams.set('focus_location', locId);
            const link = url.toString();
            try {
                await navigator.clipboard.writeText(link);
                showToast('Link copied to clipboard', 'ok');
            } catch {
                // Clipboard API unavailable (non-secure context / denied) —
                // fall back to a prompt so the link is still copyable.
                window.prompt('Copy this link:', link);
            }
        });

        // Delete
        root.querySelector('.pop-delete').addEventListener('click', async () => {
            if (!confirm(`Remove "${entry.loc.title}" from this trip?`)) return;
            try {
                await api.deleteLocation(trip, locId);
                this.map.removeLayer(entry.marker);
                this._entries.delete(locId);
                onChange?.();
                showToast('Pin removed', 'ok');
            } catch (err) {
                showToast(`Delete failed: ${err.message}`, 'error');
            }
        });
    }
}
