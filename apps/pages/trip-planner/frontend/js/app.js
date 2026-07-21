/**
 * App entrypoint: load the trip list, open the requested (or default) trip,
 * and wire the trip switcher, filter panel, and mobile controls together.
 */
import { Api } from './api.js';
import { TripMap } from './map.js';
import { Filters } from './filters.js';
import { Chat } from './chat.js';

const api = new Api();

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

const toastEl = document.getElementById('toast');
let toastTimer = null;
function showToast(msg, kind = 'ok', ms = 2200) {
    toastEl.textContent = msg;
    toastEl.className = `toast show ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.className = 'toast'; }, ms);
}

let currentTrip = null;

const filters = new Filters(document.getElementById('filter-panel-body'), {
    onChange: () => map.setFilter(filters.predicate()),
});

const map = new TripMap('map', {
    api,
    getTripName: () => currentTrip,
    showToast,
    // A rating/delete changed the data: refresh chip counts, keep toggles.
    onChange: () => {
        filters.mount(map.locations(), { reset: false });
        map.setFilter(filters.predicate());
    },
    // A pin was opened — hand it to the chat as "selected activity" context.
    onSelect: (loc) => chat.setSelected(loc),
});

const chat = new Chat({
    api,
    getTripName: () => currentTrip,
    getSelected: () => map.getSelected(),
    clearSelected: () => map.clearSelected(),
    showToast,
    // The assistant may have added/edited/removed a place: reload data and
    // re-render without moving the map, then refresh the filter chips. focusId
    // is a pin to jump to (a freshly added place, or one it was asked to show).
    onMutate: (focusId) => currentTrip && refreshTrip(currentTrip, focusId),
});

/** Re-fetch the open trip and re-render in place (used after chat edits). */
async function refreshTrip(name, focusId = null) {
    const trip = await api.getTrip(name);
    map.render(trip, { preserveView: true });
    filters.mount(map.locations(), { reset: false, categories: trip.categories, ratings: trip.ratings });
    map.setFilter(filters.predicate());
    // Jump to and open the pin the chat pointed at. openPin force-shows it even
    // if its type filter is off, and fails only when it has no coordinates.
    if (focusId && !map.openPin(focusId)) {
        showToast("That place has no coordinates yet, so it can't be shown on the map", 'ok', 4000);
    }
}

async function loadTrip(name) {
    const trip = await api.getTrip(name);
    currentTrip = name;
    document.getElementById('trip-title').textContent = trip.title || name;
    const select = document.getElementById('trip-select');
    if (select.value !== name) select.value = name;

    const url = new URL(window.location);
    url.searchParams.set('trip', name);
    history.replaceState(null, '', url);

    map.render(trip);
    filters.mount(trip.locations || [], { reset: true, categories: trip.categories, ratings: trip.ratings });
    map.setFilter(filters.predicate());
}

async function init() {
    let data;
    try {
        data = await api.listTrips();
    } catch (err) {
        showToast(`Failed to load trips: ${err.message}`, 'error', 6000);
        return;
    }

    const select = document.getElementById('trip-select');
    if (!data.trips.length) {
        document.getElementById('trip-title').textContent = 'No trips yet';
        select.innerHTML = '<option>— none —</option>';
        showToast('No trips found. Use the plan-trip skill to create one.', 'ok', 6000);
        map.render({ locations: [] });
        filters.mount([], { reset: true });
        return;
    }

    select.innerHTML = data.trips
        .map((t) => `<option value="${esc(t.name)}">${esc(t.title)}</option>`)
        .join('');
    select.addEventListener('change', () => {
        loadTrip(select.value).catch((e) => showToast(e.message, 'error', 5000));
    });

    const requested = new URLSearchParams(window.location.search).get('trip');
    const names = data.trips.map((t) => t.name);
    const target = (requested && names.includes(requested)) ? requested
        : (names.includes(data.default)) ? data.default
        : names[0];

    try {
        await loadTrip(target);
    } catch (err) {
        showToast(`Failed to load trip: ${err.message}`, 'error', 5000);
        return;
    }

    const pinId = new URLSearchParams(window.location.search).get('pin');
    if (pinId && !map.openPin(pinId)) {
        showToast(`Pin "${pinId}" not found`, 'error', 4000);
    }
}

// ── Static controls ──────────────────────────────────────────────────────
document.getElementById('btn-fit').addEventListener('click', () => map.fitAll());

const filterPanel = document.getElementById('filter-panel');
const filterToggle = document.getElementById('filter-toggle');
function setFiltersOpen(open) {
    filterPanel.hidden = !open;
    filterToggle.classList.toggle('on', open);
    filterToggle.setAttribute('aria-expanded', String(open));
}
filterToggle.addEventListener('click', () => setFiltersOpen(filterPanel.hidden));
// Expanded by default on large screens; phones stay collapsed to save space.
if (window.matchMedia('(min-width: 721px)').matches) setFiltersOpen(true);

init();
