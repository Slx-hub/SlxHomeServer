/**
 * App entrypoint — orchestrates fetching projects and rendering cards.
 */
import { Api } from './api.js';
import { LogModal } from './log-modal.js';
import { ProjectCard } from './project-card.js';
import { showToast } from './toast.js';

const api = new Api();
const logModal = new LogModal(api);
const appEl = document.getElementById('app');
const refreshBtn = document.getElementById('btn-refresh');

async function loadProjects() {
    appEl.innerHTML = '<div class="loading">Loading projects…</div>';
    try {
        const [data, favData] = await Promise.all([api.getProjects(), api.getFavorites()]);
        const favorites = new Set(favData.favorites);
        appEl.innerHTML = '';

        if (data.projects.length === 0) {
            appEl.innerHTML = '<div class="loading">No compose projects found.</div>';
            return;
        }

        // Favorites first, then alphabetical within each group
        const sorted = [
            ...data.projects.filter(p => favorites.has(p.name)),
            ...data.projects.filter(p => !favorites.has(p.name)),
        ];

        for (const project of sorted) {
            const card = new ProjectCard(project, api, logModal, loadProjects, favorites.has(project.name));
            appEl.appendChild(card.element);
        }
    } catch (err) {
        appEl.innerHTML = `<div class="loading">Failed to load: ${err.message}</div>`;
        showToast(`Load failed: ${err.message}`, 'error', 5000);
    }
}

refreshBtn.addEventListener('click', loadProjects);

// Initial load
loadProjects();
