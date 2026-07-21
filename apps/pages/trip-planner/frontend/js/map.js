/**
 * Leaflet map wrapper: CARTO Voyager basemap, category-coloured pins, and a
 * per-pin popup card (cost / description / source / Google Maps link + the
 * editable rating & notes that write back to the API).
 */
import { DEFAULT_CATEGORIES, DEFAULT_RATINGS } from './config.js';

const TILE_URL = 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
const TILE_ATTR =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors ' +
    '&copy; <a href="https://carto.com/attributions">CARTO</a>';

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
        L.tileLayer(TILE_URL, {
            attribution: TILE_ATTR,
            subdomains: 'abcd',
            maxZoom: 20,
        }).addTo(this.map);

        // locId -> { marker, loc, visible }
        this._entries = new Map();
        this._filter = () => true;
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

        const savedCenter = preserveView ? this.map.getCenter() : null;
        const savedZoom = preserveView ? this.map.getZoom() : null;

        this._entries.forEach((e) => this.map.removeLayer(e.marker));
        this._entries.clear();

        for (const loc of trip.locations || []) {
            if (loc.lat == null || loc.lng == null) continue;
            const marker = L.marker([loc.lat, loc.lng], { icon: this._icon(loc) });
            marker.bindPopup(() => this._popupHtml(this._entries.get(loc.id).loc), {
                maxWidth: 320,
                minWidth: 260,
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
    openPin(id) {
        const entry = this._entries.get(id);
        if (!entry) return false;
        if (!entry.visible) {
            this.map.addLayer(entry.marker);
            entry.visible = true;
        }
        this.map.setView(entry.marker.getLatLng(), Math.max(this.map.getZoom(), 15));
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

    _applyFilter() {
        for (const e of this._entries.values()) {
            const show = this._filter(e.loc);
            if (show && !e.visible) this.map.addLayer(e.marker);
            else if (!show && e.visible) this.map.removeLayer(e.marker);
            e.visible = show;
        }
    }

    /** Current locations (used by the filter panel to render counts). */
    locations() {
        return [...this._entries.values()].map((e) => e.loc);
    }

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
                (loc.description ? `<p class="pop-desc">${esc(loc.description)}</p>` : '') +
                `<div class="pop-links">` +
                    `<a class="pop-link gmaps" href="${esc(gmapsUrl(loc))}" target="_blank" rel="noopener">🧭 Google Maps</a>` +
                    (loc.source_url
                        ? `<a class="pop-link src" href="${esc(loc.source_url)}" target="_blank" rel="noopener">🔗 Source</a>`
                        : '') +
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
