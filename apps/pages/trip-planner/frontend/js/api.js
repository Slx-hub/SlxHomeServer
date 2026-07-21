/**
 * API client — thin fetch wrapper. Uses relative paths so it works both when
 * proxied under /trips (via the dynamic <base>) and on direct :50004 access.
 */
export class Api {
    async _request(path, options = {}) {
        const res = await fetch(path, {
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        const body = res.status === 204 ? null : await res.json();
        if (!res.ok) {
            throw new Error((body && body.detail) || `HTTP ${res.status}`);
        }
        return body;
    }

    listTrips() {
        return this._request('api/trips');
    }

    getTrip(name) {
        return this._request(`api/trips/${encodeURIComponent(name)}`);
    }

    /** Update the browser-editable fields (rating, notes) of one location. */
    patchLocation(trip, locId, patch) {
        return this._request(
            `api/trips/${encodeURIComponent(trip)}/locations/${encodeURIComponent(locId)}`,
            { method: 'PATCH', body: JSON.stringify(patch) },
        );
    }

    deleteLocation(trip, locId) {
        return this._request(
            `api/trips/${encodeURIComponent(trip)}/locations/${encodeURIComponent(locId)}`,
            { method: 'DELETE' },
        );
    }

    /** Send a message to the chat assistant; returns { reply, usage }. */
    chat(payload) {
        return this._request('api/chat', { method: 'POST', body: JSON.stringify(payload) });
    }

    /** Monthly usage of the chat assistant (proxy for free-tier credits). */
    chatUsage() {
        return this._request('api/chat/usage');
    }
}
