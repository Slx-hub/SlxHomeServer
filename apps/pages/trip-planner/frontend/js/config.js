/**
 * Fallback taxonomy (category icon/colour/label + rating scale), shown only
 * before any trip has loaded. Once a trip loads, the API returns its *own*
 * `categories`/`ratings` — the same defaults below, merged with whatever
 * custom types/ratings that trip added via the chat assistant's set_category/
 * set_rating tools (backend/app.py `_DEFAULT_CATEGORIES`/`_DEFAULT_RATINGS` —
 * keep these two lists in sync) — and TripMap/Filters use that per-trip copy.
 */

export const DEFAULT_CATEGORIES = {
    food:      { label: 'Food',      emoji: '🍜', color: '#ff7043' },
    activity:  { label: 'Activity',  emoji: '🎢', color: '#ab47bc' },
    monument:  { label: 'Monument',  emoji: '🏛️', color: '#8d6e63' },
    nature:    { label: 'Nature',    emoji: '🌲', color: '#66bb6a' },
    temple:    { label: 'Temple',    emoji: '⛩️', color: '#ef5350' },
    museum:    { label: 'Museum',    emoji: '🖼️', color: '#5c6bc0' },
    viewpoint: { label: 'Viewpoint', emoji: '🌅', color: '#ffa726' },
    shopping:  { label: 'Shopping',  emoji: '🛍️', color: '#ec407a' },
    lodging:   { label: 'Lodging',   emoji: '🏨', color: '#26a69a' },
    transport: { label: 'Transport', emoji: '🚆', color: '#78909c' },
    nightlife: { label: 'Nightlife', emoji: '🍸', color: '#7e57c2' },
    event:     { label: 'Event',     emoji: '🎊', color: '#ffca28' },
    other:     { label: 'Other',     emoji: '📍', color: '#90a4ae' },
};

/** Rating scale. `null`/absent means unrated. */
export const DEFAULT_RATINGS = {
    want:  { label: 'Want to do', emoji: '💚', color: '#4caf50' },
    maybe: { label: 'Maybe',      emoji: '🤔', color: '#ffc107' },
    nah:   { label: 'Nah',        emoji: '🚫', color: '#f44336' },
};

/** Pseudo-key used by the rating filter for locations with no rating yet. */
export const UNRATED = 'unrated';
