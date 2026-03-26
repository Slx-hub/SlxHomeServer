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
        const data = await api.getProjects();
        appEl.innerHTML = '';

        if (data.projects.length === 0) {
            appEl.innerHTML = '<div class="loading">No compose projects found.</div>';
            return;
        }

        for (const project of data.projects) {
            const card = new ProjectCard(project, api, logModal, loadProjects);
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
