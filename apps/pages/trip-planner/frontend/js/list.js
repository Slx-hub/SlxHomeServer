/**
 * List view: a bottom-right drawer (closed by default) that lists the type,
 * rating and title of every pin currently visible — i.e. passing the active
 * filter AND inside the map viewport. Computation is lazy: the list is only
 * (re)built while the drawer is open, and while open it refreshes on map
 * pan/zoom (via map.onViewChange) and whenever the app calls refresh() after a
 * filter or data change.
 */
function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

export class TripList {
    /** @param {import('./map.js').TripMap} map */
    constructor(map) {
        this.map = map;
        this.open = false;
        this._build();
        // Only recompute while the drawer is open — keeps panning cheap when closed.
        this.map.onViewChange(() => { if (this.open) this.render(); });
    }

    _build() {
        this.launcher = document.createElement('button');
        this.launcher.className = 'list-fab';
        this.launcher.title = 'List visible places';
        this.launcher.textContent = '📋';
        this.launcher.addEventListener('click', () => this._toggle(true));

        this.panel = document.createElement('section');
        this.panel.className = 'list-panel panel';
        this.panel.hidden = true;
        this.panel.innerHTML = `
            <div class="list-head">
                <strong>In view</strong>
                <span class="list-count">0</span>
                <button class="icon-btn list-close" title="Close">✕</button>
            </div>
            <div class="list-body"></div>`;

        document.body.append(this.launcher, this.panel);
        this.bodyEl = this.panel.querySelector('.list-body');
        this.countEl = this.panel.querySelector('.list-count');
        this.panel.querySelector('.list-close').addEventListener('click', () => this._toggle(false));
    }

    _toggle(open) {
        this.open = open;
        this.panel.hidden = !open;
        this.launcher.hidden = open;
        if (open) this.render();
    }

    /** Rebuild the list if the drawer is open; a no-op otherwise (lazy). */
    refresh() {
        if (this.open) this.render();
    }

    render() {
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
            return (
                `<button class="list-row" data-loc="${esc(loc.id)}" type="button">` +
                    `<span class="list-type" style="--c:${c.color}" title="${esc(c.label)}">${c.emoji}</span>` +
                    `<span class="list-title">${esc(loc.title)}</span>` +
                    (r ? `<span class="list-rating" title="${esc(r.label)}">${r.emoji}</span>` : '') +
                `</button>`
            );
        }).join('');

        this.bodyEl.querySelectorAll('.list-row').forEach((btn) => {
            btn.addEventListener('click', () => this.map.openPin(btn.dataset.loc));
        });
    }
}
