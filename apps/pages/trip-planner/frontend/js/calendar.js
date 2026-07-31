/**
 * Calendar tab of the bottom-right drawer. Shows two months side by side on
 * desktop — starting at the month the trip begins in, so a plan straddling the
 * month border reads as one continuous stretch — and a single month on phones,
 * where two would swallow the screen. ‹ › page through the months either way.
 * The travel window is banded, and every day carries a dot per pin scheduled on
 * it, coloured by pin type. Tapping a day asks the app to isolate it on the map;
 * tapping the same day again clears it.
 *
 * Reads everything from the map on each render (travel window, locations,
 * taxonomy, isolated day); the only state it owns is how far the user has paged.
 */
import {
    addDays, fmtMonth, locSpan, monthGrid, monthRun, monthShortName, toDate, todayIso,
} from './dates.js';

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

const WEEKDAY_INITIALS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
const MAX_DOTS = 4;
// A pathological span (a hotel accidentally set to 2030) must not spin the
// day-expansion loop below; no real plan comes near this.
const MAX_SPAN_DAYS = 400;

export class TripCalendar {
    /**
     * @param {HTMLElement} el container to render into
     * @param {{map: import('./map.js').TripMap, onSelectDay: (day: string) => void}} deps
     */
    constructor(el, deps) {
        this.el = el;
        this.deps = deps;
        this.window = null;   // { start, end } of the travel window, refreshed per render
        this._offset = 0;     // months paged away from the trip's first month
        this._anchorKey = null;
    }

    /** Two months where there's room, one on a phone. */
    _monthCount() {
        return window.matchMedia('(max-width: 720px)').matches ? 1 : 2;
    }

    /**
     * The month the calendar opens on: the trip's first, else the earliest
     * scheduled pin's, else this one. Paging is an offset from here, and it
     * resets whenever the anchor moves (a trip switch, or dates being set).
     */
    _anchor(byDay) {
        const days = [...byDay.keys()].sort();
        const iso = this.window?.start || days[0] || todayIso();
        const d = toDate(iso);
        return d ? { year: d.getFullYear(), month: d.getMonth() } : null;
    }

    /** day (ISO) -> locations scheduled on it, expanding ranges day by day. */
    _byDay(locations) {
        const byDay = new Map();
        for (const loc of locations) {
            const span = locSpan(loc);
            if (!span) continue;
            let day = span.start;
            for (let i = 0; day && day <= span.end && i < MAX_SPAN_DAYS; i++) {
                if (!byDay.has(day)) byDay.set(day, []);
                byDay.get(day).push(loc);
                day = addDays(day, 1);
            }
        }
        return byDay;
    }

    /** "November 2026", or "Nov – Dec 2026" when two months are on screen. */
    _navLabel(months) {
        const first = months[0];
        const last = months[months.length - 1];
        if (first === last) return fmtMonth(first.year, first.month);
        const a = `${monthShortName(first.month)}${first.year === last.year ? '' : ` ${first.year}`}`;
        return `${a} – ${monthShortName(last.month)} ${last.year}`;
    }

    render() {
        this.window = this.deps.map.tripWindow();
        const locations = this.deps.map.locations();
        const byDay = this._byDay(locations);
        const anchor = this._anchor(byDay);

        if (!anchor || (!this.window && !byDay.size)) {
            this.el.innerHTML =
                '<p class="list-empty">No travel dates for this trip yet. Ask the '
                + 'assistant — “we fly out 28.11. and come back 13.12.” — and the '
                + 'calendar shows up here.</p>';
            return;
        }

        // A new anchor means a different trip (or dates just arrived) — start
        // back at the trip's own month rather than wherever the user had paged.
        const anchorKey = `${anchor.year}-${anchor.month}`;
        if (anchorKey !== this._anchorKey) {
            this._anchorKey = anchorKey;
            this._offset = 0;
        }

        const months = monthRun(anchor, this._offset, this._monthCount());
        const selected = this.deps.map.dayFilter();
        const today = todayIso();
        const unscheduled = locations.filter((l) => !locSpan(l)).length;

        const dow = WEEKDAY_INITIALS.map((d) => `<span>${d}</span>`).join('');
        this.el.innerHTML =
            `<div class="cal-nav">` +
                `<button class="cal-nav-btn" type="button" data-step="-1" ` +
                        `title="Previous month" aria-label="Previous month">‹</button>` +
                `<span class="cal-nav-label">${esc(this._navLabel(months))}</span>` +
                `<button class="cal-nav-btn" type="button" data-step="1" ` +
                        `title="Next month" aria-label="Next month">›</button>` +
                (this._offset
                    ? `<button class="cal-nav-btn cal-nav-home" type="button" data-step="home" ` +
                      `title="Back to the trip" aria-label="Back to the trip">⌂</button>`
                    : '') +
            `</div>` +
            months.map(({ year, month }) => (
                `<div class="cal-month">` +
                    // With one month on screen the pager label already names it.
                    (months.length > 1
                        ? `<div class="cal-month-head">${esc(fmtMonth(year, month))}</div>`
                        : '') +
                    `<div class="cal-dow">${dow}</div>` +
                    `<div class="cal-grid">` +
                        monthGrid(year, month)
                            .map((day) => this._cellHtml(day, byDay, selected, today))
                            .join('') +
                    `</div>` +
                `</div>`
            )).join('')
            + `<p class="cal-hint">Tap a day to isolate it on the map; tap it again to reset.`
            + (unscheduled
                ? ` <strong>${unscheduled}</strong> pin${unscheduled === 1 ? '' : 's'} `
                  + `${unscheduled === 1 ? 'has' : 'have'} no day yet.`
                : '')
            + `</p>`;

        this.el.querySelectorAll('.cal-nav-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                const step = btn.dataset.step;
                this._offset = step === 'home' ? 0 : this._offset + Number(step);
                this.render();
            });
        });
        this.el.querySelectorAll('.cal-day[data-day]').forEach((btn) => {
            btn.addEventListener('click', () => this.deps.onSelectDay(btn.dataset.day));
        });
    }

    _cellHtml(day, byDay, selected, today) {
        if (!day) return '<span class="cal-day pad"></span>';

        const hits = byDay.get(day) || [];
        const cls = ['cal-day'];
        if (this.window && this.window.start <= day && day <= this.window.end) {
            cls.push('trip');
            if (day === this.window.start) cls.push('trip-start');
            if (day === this.window.end) cls.push('trip-end');
        }
        if (hits.length) cls.push('has');
        if (day === selected) cls.push('sel');
        if (day === today) cls.push('today');

        const dots = hits.slice(0, MAX_DOTS).map((loc) => {
            const c = this.deps.map.categoryMeta(loc.category);
            return `<i style="--c:${c.color}"></i>`;
        }).join('');
        const title = hits.length
            ? `${hits.length} planned: ${hits.map((l) => l.title).join(', ')}`
            : 'Nothing planned yet';

        return (
            `<button class="${cls.join(' ')}" type="button" data-day="${day}" ` +
                    `title="${esc(title)}">` +
                `<span class="cal-num">${Number(day.slice(8, 10))}</span>` +
                `<span class="cal-dots">${dots}` +
                    (hits.length > MAX_DOTS ? '<i class="more"></i>' : '') +
                `</span>` +
            `</button>`
        );
    }
}
