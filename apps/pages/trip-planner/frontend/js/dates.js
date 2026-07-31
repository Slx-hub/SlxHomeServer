/**
 * Date helpers for the time-aware plan. Every date in a trip file is a plain
 * "YYYY-MM-DD" string, so all comparisons here are *string* comparisons
 * (lexicographic order == chronological order) — no Date arithmetic, and no
 * timezone that could shift a day. Date objects are built only for formatting
 * and calendar layout, always at local noon so a DST jump can't roll them over.
 */

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];
const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKDAYS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;

export function isIso(s) {
    return typeof s === 'string' && ISO_RE.test(s);
}

/** "YYYY-MM-DD" → Date at local noon, or null if it isn't a real date. */
export function toDate(iso) {
    if (!isIso(iso)) return null;
    const [y, m, d] = iso.split('-').map(Number);
    const dt = new Date(y, m - 1, d, 12);
    // Rejects 2026-02-30 & co, which JS would silently roll into March.
    return (dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d)
        ? dt : null;
}

/** Date → "YYYY-MM-DD" using local fields (toISOString() would shift the day). */
export function toIso(dt) {
    const p = (n) => String(n).padStart(2, '0');
    return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`;
}

export function todayIso() {
    return toIso(new Date());
}

export function addDays(iso, n) {
    const dt = toDate(iso);
    if (!dt) return null;
    dt.setDate(dt.getDate() + n);
    return toIso(dt);
}

/** Whole days from `a` to `b` (negative if b is earlier). */
export function daysBetween(a, b) {
    const da = toDate(a);
    const db = toDate(b);
    if (!da || !db) return 0;
    return Math.round((db - da) / 86_400_000);
}

/**
 * A location's scheduled span as { start, end } ISO strings, or null when it
 * isn't scheduled yet. Single-day pins get end === start, so callers never have
 * to special-case the range form.
 */
export function locSpan(loc) {
    const start = isIso(loc?.date) ? loc.date : null;
    if (!start) return null;
    const end = isIso(loc?.date_end) && loc.date_end > start ? loc.date_end : start;
    return { start, end };
}

/** True if `day` ("YYYY-MM-DD") falls inside this location's scheduled span. */
export function locCoversDay(loc, day) {
    const span = locSpan(loc);
    return !!span && span.start <= day && day <= span.end;
}

/** "Sat 28 Nov", or "28 Nov" with { weekday: false }. */
export function fmtDay(iso, { weekday = true } = {}) {
    const dt = toDate(iso);
    if (!dt) return '';
    const core = `${dt.getDate()} ${MONTHS_SHORT[dt.getMonth()]}`;
    return weekday ? `${WEEKDAYS_SHORT[dt.getDay()]} ${core}` : core;
}

export function fmtMonth(year, monthIdx) {
    return `${MONTHS[monthIdx]} ${year}`;
}

export function monthShortName(monthIdx) {
    return MONTHS_SHORT[monthIdx];
}

/**
 * The schedule line for a pin's card: "Sat 5 Dec", or for a span
 * "Sat 28 Nov – Thu 3 Dec · 5 nights" (nights for lodging, days for anything
 * else — a 3-night stay covers 4 days, and both readings are useful).
 */
export function fmtSpan(loc) {
    const span = locSpan(loc);
    if (!span) return '';
    if (span.start === span.end) return fmtDay(span.start);
    const nights = daysBetween(span.start, span.end);
    const length = loc.category === 'lodging'
        ? `${nights} night${nights === 1 ? '' : 's'}`
        : `${nights + 1} days`;
    return `${fmtDay(span.start)} – ${fmtDay(span.end)} · ${length}`;
}

/** Compact form for list rows: "5 Dec" / "28 Nov–3 Dec". */
export function fmtSpanShort(loc) {
    const span = locSpan(loc);
    if (!span) return '';
    const short = (d) => fmtDay(d, { weekday: false });
    return span.start === span.end
        ? short(span.start)
        : `${short(span.start)}–${short(span.end)}`;
}

/**
 * One month as a Monday-first grid of ISO day strings, padded with nulls so it
 * fills whole weeks (the calendar renders those as empty cells).
 */
export function monthGrid(year, monthIdx) {
    const first = new Date(year, monthIdx, 1, 12);
    const lead = (first.getDay() + 6) % 7;                       // Mon = 0
    const length = new Date(year, monthIdx + 1, 0, 12).getDate();
    const cells = new Array(lead).fill(null);
    for (let d = 1; d <= length; d++) cells.push(toIso(new Date(year, monthIdx, d, 12)));
    while (cells.length % 7) cells.push(null);
    return cells;
}

/** `count` consecutive months as {year, month}, starting `offset` from the anchor. */
export function monthRun({ year, month }, offset, count) {
    const out = [];
    for (let i = 0; i < count; i++) {
        const d = new Date(year, month + offset + i, 1, 12);
        out.push({ year: d.getFullYear(), month: d.getMonth() });
    }
    return out;
}
