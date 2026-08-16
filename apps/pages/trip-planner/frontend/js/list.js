/**
 * The bottom-right drawer (closed by default), with two tabs:
 *
 * - **In view** — every pin passing the active filter AND inside the map
 *   viewport, with its type, rating, schedule and title.
 * - **Calendar** — the trip's first two months (see calendar.js), for picking a
 *   day to isolate on the map.
 *
 * Computation is lazy: a tab is only (re)built while the drawer is open on it.
 * While the list tab is open it refreshes on map pan/zoom (via
 * map.onViewChange) and whenever the app calls refresh() after a filter or data
 * change.
 */
import { TripCalendar } from './calendar.js';
import { fmtSpanShort } from './dates.js';

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

export class TripList {
    /**
     * @param {import('./map.js').TripMap} map
     * @param {{onSelectDay: (day: string) => void}} deps
     */
    constructor(map, { onSelectDay } = {}) {
        this.map = map;
        this.open = false;
        this.tab = 'list';
        this._build();
        this.calendar = new TripCalendar(this.calEl, {
            map,
            onSelectDay: (day) => onSelectDay?.(day),
        });
        // Only recompute while the list tab is open — keeps panning cheap
        // otherwise, and the calendar doesn't depend on the map viewport at all.
        this.map.onViewChange(() => { if (this.open && this.tab === 'list') this.render(); });
        // The calendar shows one month or two depending on this breakpoint, so a
        // resize across it (or a rotation) has to redraw.
        window.matchMedia('(max-width: 720px)').addEventListener('change', () => {
            if (this.open && this.tab === 'cal') this.render();
        });
    }

    _build() {
        this.launcher = document.createElement('button');
        this.launcher.className = 'list-fab';
        this.launcher.title = 'Places in view & calendar';
        this.launcher.textContent = '📋';
        this.launcher.addEventListener('click', () => this._toggle(true));

        this.panel = document.createElement('section');
        this.panel.className = 'list-panel panel';
        this.panel.hidden = true;
        this.panel.innerHTML = `
            <div class="list-head">
                <div class="drawer-tabs" role="tablist">
                    <button class="drawer-tab on" data-tab="list" role="tab">📋 In view</button>
                    <button class="drawer-tab" data-tab="cal" role="tab">📅 Calendar</button>
                </div>
                <span class="list-count">0</span>
                <button class="icon-btn list-close" title="Close">✕</button>
            </div>
            <div class="list-body"></div>
            <div class="cal-body" hidden></div>`;

        document.body.append(this.launcher, this.panel);
        this.bodyEl = this.panel.querySelector('.list-body');
        this.calEl = this.panel.querySelector('.cal-body');
        this.countEl = this.panel.querySelector('.list-count');
        this.panel.querySelector('.list-close').addEventListener('click', () => this._toggle(false));
        this.panel.querySelectorAll('.drawer-tab').forEach((btn) => {
            btn.addEventListener('click', () => this._setTab(btn.dataset.tab));
        });
    }

    _toggle(open) {
        this.open = open;
        this.panel.hidden = !open;
        this.launcher.hidden = open;
        if (open) this.render();
    }

    /** Show the active tab's body and highlight its button (no re-render). */
    _applyTabState() {
        this.panel.querySelectorAll('.drawer-tab').forEach((btn) =>
            btn.classList.toggle('on', btn.dataset.tab === this.tab));
        this.bodyEl.hidden = this.tab !== 'list';
        this.calEl.hidden = this.tab !== 'cal';
        this.countEl.hidden = this.tab !== 'list';   // counts pins in view — list only
        // The calendar needs a taller drawer than the list so both months fit
        // without scrolling; see .list-panel.cal-open.
        this.panel.classList.toggle('cal-open', this.tab === 'cal');
    }

    _setTab(tab) {
        this.tab = tab;
        this._applyTabState();
        this.render();
    }

    /** Open the drawer on the calendar tab (from the isolated-day banner). */
    showCalendar() {
        this.tab = 'cal';
        this._applyTabState();
        this._toggle(true);
    }

    /** Rebuild the open tab; a no-op while the drawer is closed (lazy). */
    refresh() {
        if (this.open) this.render();
    }

    render() {
        if (this.tab === 'cal') {
            this.calendar.render();
            return;
        }

        const locs = this.map.visibleInView();
        this.countEl.textContent = String(locs.length);

        if (!locs.length) {
            this.bodyEl.innerHTML = '<p class="list-empty">No places in view.</p>';
            return;
        }

        // Sort by rating (as ordered in the trip's rating scale — best first),
        // unrated last, then alphabetically by title.
        const rank = (loc) => {
            const keys = Object.keys(this.map.ratings);
            const i = keys.indexOf(loc.rating);
            return i === -1 ? keys.length : i;
        };
        const rows = [...locs].sort((a, b) =>
            rank(a) - rank(b) || (a.title || '').localeCompare(b.title || ''));

        this.bodyEl.innerHTML = rows.map((loc) => {
            const c = this.map.categoryMeta(loc.category);
            const r = this.map.ratingMeta(loc.rating);
            const notes = (loc.notes || '').trim();
            const when = fmtSpanShort(loc);
            return (
                `<button class="list-row" data-loc="${esc(loc.id)}" type="button">` +
                    `<span class="list-type" style="--c:${c.color}" title="${esc(c.label)}">${c.emoji}</span>` +
                    `<span class="list-main">` +
                        `<span class="list-title">${esc(loc.title)}</span>` +
                        (when || notes
                            ? `<span class="list-meta">` +
                                (when ? `<span class="list-date">📅 ${esc(when)}</span>` : '') +
                                (notes ? `<span class="list-notes">${esc(notes)}</span>` : '') +
                              `</span>`
                            : '') +
                    `</span>` +
                    (loc.needs_review
                        ? `<span class="list-rating" title="${esc(loc.review_reason || 'Queued for verification.')}">🔍</span>`
                        : '') +
                    (r ? `<span class="list-rating" title="${esc(r.label)}">${r.emoji}</span>` : '') +
                `</button>`
            );
        }).join('');

        this.bodyEl.querySelectorAll('.list-row').forEach((btn) => {
            btn.addEventListener('click', () => this.map.openPin(btn.dataset.loc, { focus: false }));
        });
    }
}
