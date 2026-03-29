/**
 * API client — thin wrapper around fetch for the container manager backend.
 * Uses relative paths so it works with any base path (localhost or proxied).
 */
export class Api {
    async _request(path, options = {}) {
        const res = await fetch(path, options);
        const body = await res.json();
        if (!res.ok) {
            throw new Error(body.detail || `HTTP ${res.status}`);
        }
        return body;
    }

    getProjects() {
        return this._request('api/projects');
    }

    /** Encode project name preserving path separators. */
    _encodeName(name) {
        return name.split('/').map(encodeURIComponent).join('/');
    }

    projectUp(name) {
        return this._request(`api/projects/${this._encodeName(name)}/up`, { method: 'POST' });
    }

    projectDown(name) {
        return this._request(`api/projects/${this._encodeName(name)}/down`, { method: 'POST' });
    }

    projectRestart(name) {
        return this._request(`api/projects/${this._encodeName(name)}/restart`, { method: 'POST' });
    }

    projectLogs(name, lines = 100) {
        return this._request(`api/projects/${this._encodeName(name)}/logs?lines=${lines}`);
    }

    projectRebuild(name) {
        return this._request(`api/projects/${this._encodeName(name)}/rebuild`, { method: 'POST' });
    }

    serviceStart(containerId) {
        return this._request(`api/services/${encodeURIComponent(containerId)}/start`, { method: 'POST' });
    }

    serviceStop(containerId) {
        return this._request(`api/services/${encodeURIComponent(containerId)}/stop`, { method: 'POST' });
    }

    serviceRestart(containerId) {
        return this._request(`api/services/${encodeURIComponent(containerId)}/restart`, { method: 'POST' });
    }

    serviceRebuild(containerId) {
        return this._request(`api/services/${encodeURIComponent(containerId)}/rebuild`, { method: 'POST' });
    }

    serviceLogs(containerId, lines = 100) {
        return this._request(`api/services/${encodeURIComponent(containerId)}/logs?lines=${lines}`);
    }

    getFavorites() {
        return this._request('api/favorites');
    }

    addFavorite(name) {
        return this._request(`api/favorites/${this._encodeName(name)}`, { method: 'POST' });
    }

    removeFavorite(name) {
        return this._request(`api/favorites/${this._encodeName(name)}`, { method: 'DELETE' });
    }
}
