/**
 * Log modal controller.
 * Handles opening, closing, reloading logs for projects and services.
 */
import { escapeHtml } from './utils.js';

export class LogModal {
    constructor(api) {
        this.api = api;
        this.modal = document.getElementById('log-modal');
        this.title = document.getElementById('log-modal-title');
        this.output = document.getElementById('log-output');
        this.linesInput = document.getElementById('log-lines');
        this.currentLoader = null; // function to reload current logs

        document.getElementById('log-close').addEventListener('click', () => this.close());
        document.getElementById('log-reload').addEventListener('click', () => this.reload());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });
    }

    async openProject(projectName) {
        this.title.textContent = `Logs — ${projectName}`;
        this.currentLoader = async () => {
            const lines = parseInt(this.linesInput.value) || 100;
            const data = await this.api.projectLogs(projectName, lines);
            return data.logs;
        };
        this.modal.classList.remove('hidden');
        await this.reload();
    }

    async openService(containerId, serviceName) {
        this.title.textContent = `Logs — ${serviceName}`;
        this.currentLoader = async () => {
            const lines = parseInt(this.linesInput.value) || 100;
            const data = await this.api.serviceLogs(containerId, lines);
            return data.logs;
        };
        this.modal.classList.remove('hidden');
        await this.reload();
    }

    async reload() {
        if (!this.currentLoader) return;
        this.output.textContent = 'Loading logs…';
        try {
            const logs = await this.currentLoader();
            this.output.textContent = logs || '(no output)';
            this.output.scrollTop = this.output.scrollHeight;
        } catch (err) {
            this.output.textContent = `Error: ${err.message}`;
        }
    }

    close() {
        this.modal.classList.add('hidden');
        this.currentLoader = null;
        this.output.textContent = '';
    }
}
