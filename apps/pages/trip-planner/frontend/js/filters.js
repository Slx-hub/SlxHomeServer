/**
 * Filter panel: toggle chips for category (type) and rating. Emits a change
 * whenever the active set shifts; the app turns `predicate()` into a map filter.
 */
import { DEFAULT_CATEGORIES, DEFAULT_RATINGS, UNRATED } from './config.js';

export class Filters {
    constructor(panelEl, { onChange }) {
        this.el = panelEl;
        this.onChange = onChange;
        this.activeCats = new Set();
        this.activeRatings = new Set();
        // Overwritten per-trip in mount() with the trip's own taxonomy.
        this.categories = DEFAULT_CATEGORIES;
        this.ratings = DEFAULT_RATINGS;
    }

    _normCat(loc) {
        return this.categories[loc.category] ? loc.category : 'other';
    }

    _normRating(loc) {
        return loc.rating && this.ratings[loc.rating] ? loc.rating : UNRATED;
    }

    _ratingKeys() {
        return [...Object.keys(this.ratings), UNRATED];
    }

    /**
     * (Re)build the panel. `reset` re-enables everything (use on trip switch);
     * otherwise the current toggles are preserved and only counts refresh.
     * Pass `categories`/`ratings` (from the trip's API response) on trip
     * load/refresh; omitted, the previous ones (or the defaults) carry over.
     */
    mount(locations, { reset = false, categories, ratings } = {}) {
        this.categories = categories || this.categories;
        this.ratings = ratings || this.ratings;
        this._lastLocations = locations;
        const catCounts = {};
        const ratingCounts = {};
        for (const key of this._ratingKeys()) ratingCounts[key] = 0;
        for (const loc of locations) {
            const c = this._normCat(loc);
            catCounts[c] = (catCounts[c] || 0) + 1;
            ratingCounts[this._normRating(loc)]++;
        }

        const presentCats = Object.keys(this.categories).filter((k) => catCounts[k]);

        if (reset) {
            this.activeCats = new Set(presentCats);
            this.activeRatings = new Set(this._ratingKeys());
        }

        const catChips = presentCats.map((key) => {
            const c = this.categories[key];
            const on = this.activeCats.has(key);
            return (
                `<button class="chip ${on ? 'on' : ''}" data-kind="cat" data-key="${key}" ` +
                `style="--chip:${c.color}" type="button">${c.emoji} ${c.label}` +
                `<span class="chip-count">${catCounts[key]}</span></button>`
            );
        }).join('');

        const ratingMeta = {
            ...this.ratings,
            [UNRATED]: { label: 'Unrated', emoji: '⚪', color: '#90a4ae' },
        };
        const ratingChips = this._ratingKeys().map((key) => {
            const r = ratingMeta[key];
            const on = this.activeRatings.has(key);
            return (
                `<button class="chip ${on ? 'on' : ''}" data-kind="rating" data-key="${key}" ` +
                `style="--chip:${r.color}" type="button">${r.emoji} ${r.label}` +
                `<span class="chip-count">${ratingCounts[key]}</span></button>`
            );
        }).join('');

        this.el.innerHTML =
            `<div class="filter-group">` +
                `<div class="filter-head"><span>Rating</span>` +
                    `<button class="mini" data-all="rating" type="button">all</button></div>` +
                `<div class="chips">${ratingChips}</div>` +
            `</div>` +
            `<div class="filter-group">` +
                `<div class="filter-head"><span>Type</span>` +
                    `<button class="mini" data-all="cat" type="button">all</button></div>` +
                `<div class="chips">${catChips || '<span class="muted">No pins yet</span>'}</div>` +
            `</div>`;

        this._wire(presentCats);
    }

    _wire(presentCats) {
        this.el.querySelectorAll('.chip').forEach((btn) => {
            btn.addEventListener('click', () => {
                const set = btn.dataset.kind === 'cat' ? this.activeCats : this.activeRatings;
                const key = btn.dataset.key;
                if (set.has(key)) set.delete(key); else set.add(key);
                btn.classList.toggle('on');
                this.onChange();
            });
        });
        this.el.querySelectorAll('.mini').forEach((btn) => {
            btn.addEventListener('click', () => {
                if (btn.dataset.all === 'cat') {
                    const allOn = presentCats.every((k) => this.activeCats.has(k));
                    this.activeCats = allOn ? new Set() : new Set(presentCats);
                } else {
                    const keys = this._ratingKeys();
                    const allOn = keys.every((k) => this.activeRatings.has(k));
                    this.activeRatings = allOn ? new Set() : new Set(keys);
                }
                this.mount(this._lastLocations, { reset: false });
                this.onChange();
            });
        });
    }

    predicate() {
        return (loc) =>
            this.activeCats.has(this._normCat(loc)) &&
            this.activeRatings.has(this._normRating(loc));
    }
}
