/**
 * ProjectCard — renders a single compose project as a card with overview + details tabs.
 */
import { el, formatUptime, escapeHtml } from './utils.js';
import { showToast } from './toast.js';

export class ProjectCard {
    constructor(project, api, logModal, onRefresh, isFavorite = false) {
        this.project = project;
        this.api = api;
        this.logModal = logModal;
        this.onRefresh = onRefresh;
        this.isFavorite = isFavorite;
        this.element = this._render();
    }

    _render() {
        const p = this.project;

        const card = el('div', {
            className: 'project-card',
            dataset: { health: p.health },
        });

        card.appendChild(this._renderHeader(p));
        card.appendChild(this._renderActions(p));
        card.appendChild(this._renderTabs(p));

        return card;
    }

    _renderHeader(p) {
        const badge = el('span', { className: `status-badge ${p.status}` }, p.status);
        const titleGroup = el('div', { className: 'title-group' },
            el('h2', {}, p.name),
            badge,
        );
        const starBtn = el('button', {
            className: `btn-star${this.isFavorite ? ' active' : ''}`,
            title: this.isFavorite ? 'Remove from favorites' : 'Add to favorites',
            onClick: async () => {
                try {
                    if (this.isFavorite) {
                        await this.api.removeFavorite(p.name);
                    } else {
                        await this.api.addFavorite(p.name);
                    }
                    this.onRefresh();
                } catch (err) {
                    showToast(`Error: ${err.message}`, 'error', 4000);
                }
            },
        }, this.isFavorite ? '★' : '☆');
        return el('div', { className: 'card-header' }, titleGroup, starBtn);
    }

    _renderActions(p) {
        const actions = el('div', { className: 'card-actions' });

        if (p.status === 'stopped') {
            actions.appendChild(this._actionBtn('▶ Start', 'btn-success', () => this._exec(() => this.api.projectUp(p.name), 'Starting…')));
        } else {
            actions.appendChild(this._actionBtn('■ Stop', 'btn-danger', () => this._exec(() => this.api.projectDown(p.name), 'Stopping…')));
            actions.appendChild(this._actionBtn('↻ Restart', '', () => this._exec(() => this.api.projectRestart(p.name), 'Restarting…')));
            actions.appendChild(this._actionBtn('📋 Logs', '', () => this.logModal.openProject(p.name)));
        }
        const rebuildBtn = this._actionBtn('⟳ Rebuild', 'btn-muted', () => {
            if (!confirm('Rebuild from scratch?\n\nThis will run compose build followed by compose up. Containers will be recreated — any data not stored in a bind mount or named volume may be lost.')) return;
            this._exec(() => this.api.projectRebuild(p.name), 'Rebuilding… (this may take a while)');
        });
        rebuildBtn.title = 'Rebuild images from scratch and restart — may cause data loss';
        actions.appendChild(rebuildBtn);

        return actions;
    }

    _renderTabs(p) {
        const wrapper = document.createElement('div');

        // Tab bar
        const tabBar = el('div', { className: 'tab-bar' });
        const overviewBtn = el('button', { className: 'tab-btn active' }, 'Overview');
        const detailsBtn = el('button', { className: 'tab-btn' }, 'Details');
        tabBar.append(overviewBtn, detailsBtn);

        // Tab panels
        const overviewPanel = el('div', { className: 'tab-panel active' });
        this._fillOverview(overviewPanel, p);

        const detailsPanel = el('div', { className: 'tab-panel' });
        this._fillDetails(detailsPanel, p);

        // Tab switching
        overviewBtn.addEventListener('click', () => {
            overviewBtn.classList.add('active');
            detailsBtn.classList.remove('active');
            overviewPanel.classList.add('active');
            detailsPanel.classList.remove('active');
        });
        detailsBtn.addEventListener('click', () => {
            detailsBtn.classList.add('active');
            overviewBtn.classList.remove('active');
            detailsPanel.classList.add('active');
            overviewPanel.classList.remove('active');
        });

        wrapper.append(tabBar, overviewPanel, detailsPanel);
        return wrapper;
    }

    _fillOverview(panel, p) {
        const svcCount = p.services.length;
        const running = p.services.filter(s => s.running).length;
        panel.appendChild(this._overviewLine('Services', `${running}/${svcCount} running`));
        panel.appendChild(this._overviewLine('Health', p.health));
        panel.appendChild(this._overviewLine('Compose dir', p.name));

        // Uptime of first running service
        const firstRunning = p.services.find(s => s.running);
        if (firstRunning) {
            panel.appendChild(this._overviewLine('Uptime', formatUptime(firstRunning.uptime_seconds)));
        }
    }

    _fillDetails(panel, p) {
        if (p.services.length === 0) {
            panel.appendChild(el('div', { className: 'service-meta' }, 'No containers found (project may be stopped)'));
            return;
        }

        for (const svc of p.services) {
            const row = el('div', { className: 'service-row' });

            const dot = el('span', { className: `health-dot ${svc.status}` });
            const info = el('div', { className: 'service-info' },
                dot,
                el('div', {},
                    el('div', { className: 'service-name' }, svc.service),
                    el('div', { className: 'service-image' }, svc.image),
                    el('div', { className: 'service-meta' },
                        svc.running ? `Up ${formatUptime(svc.uptime_seconds)}` : svc.status,
                        svc.health !== 'none' ? ` · ${svc.health}` : '',
                        svc.ports ? ` · ${svc.ports}` : '',
                    ),
                ),
            );

            const actions = el('div', { className: 'service-actions' });

            if (svc.running) {
                actions.appendChild(this._actionBtn('■', 'btn-danger btn-sm', () => this._exec(() => this.api.serviceStop(svc.id), `Stopping ${svc.service}…`)));
                actions.appendChild(this._actionBtn('↻', 'btn-sm', () => this._exec(() => this.api.serviceRestart(svc.id), `Restarting ${svc.service}…`)));
                actions.appendChild(this._actionBtn('📋', 'btn-sm', () => this.logModal.openService(svc.id, svc.service)));
            } else {
                actions.appendChild(this._actionBtn('▶', 'btn-success btn-sm', () => this._exec(() => this.api.serviceStart(svc.id), `Starting ${svc.service}…`)));
            }
            const svcRebuildBtn = this._actionBtn('⟳', 'btn-muted btn-sm', () => {
                if (!confirm(`Rebuild ${svc.service} from scratch?\n\nThis will run compose build and compose up for this service. Any data not stored in a bind mount or named volume may be lost.`)) return;
                this._exec(() => this.api.serviceRebuild(svc.id), `Rebuilding ${svc.service}… (this may take a while)`);
            });
            svcRebuildBtn.title = 'Rebuild image from scratch and restart — may cause data loss';
            actions.appendChild(svcRebuildBtn);

            row.append(info, actions);
            panel.appendChild(row);
        }
    }

    _overviewLine(label, value) {
        return el('div', { className: 'overview-line' },
            el('span', { className: 'label' }, label),
            el('span', {}, value || '—'),
        );
    }

    _actionBtn(text, extraClass, onClick) {
        const btn = el('button', { className: `btn ${extraClass}`.trim(), onClick }, text);
        return btn;
    }

    async _exec(action, toastMsg) {
        showToast(toastMsg, 'info');
        try {
            await action();
            showToast('Done', 'success', 2000);
        } catch (err) {
            showToast(`Error: ${err.message}`, 'error', 5000);
        }
        // Refresh after action
        if (this.onRefresh) this.onRefresh();
    }
}
