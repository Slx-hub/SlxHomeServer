/**
 * Chat assistant panel. A launcher FAB opens a compact, mobile-first chat that
 * talks to the backend `/api/chat` agent (Gemini). The agent edits the open
 * trip via tools; on any reply we refresh the map in place. The panel also
 * shows the currently selected activity as context and a monthly "credits"
 * meter (see backend note — it's a local proxy for the free-tier rate limit).
 */
export class Chat {
    /**
     * @param {{api, getTripName:()=>string, getSelected:()=>object|null,
     *          onMutate:Function, showToast:Function}} deps
     */
    constructor(deps) {
        this.deps = deps;
        this.history = [];        // [{role:'user'|'assistant', content}]
        this.selected = null;
        this.busy = false;
        this._build();
        this._loadUsage();
    }

    // ── DOM ────────────────────────────────────────────────────────────────
    _build() {
        this.launcher = document.createElement('button');
        this.launcher.className = 'chat-fab';
        this.launcher.title = 'Trip assistant';
        this.launcher.textContent = '💬';
        this.launcher.hidden = true; // shown only once we know chat is configured
        this.launcher.addEventListener('click', () => this._toggle(true));

        this.panel = document.createElement('section');
        this.panel.className = 'chat-panel panel';
        this.panel.hidden = true;
        this.panel.innerHTML = `
            <div class="chat-head">
                <strong>Assistant</strong>
                <span class="chat-credits" title="Monthly free-tier budget remaining">–</span>
                <button class="icon-btn chat-close" title="Close">✕</button>
            </div>
            <div class="chat-context" hidden></div>
            <div class="chat-log" aria-live="polite"></div>
            <form class="chat-input">
                <input type="text" class="chat-text" autocomplete="off"
                       placeholder="Add a link, or edit a place…" />
                <button type="submit" class="chat-send" title="Send">➤</button>
            </form>`;

        document.body.append(this.launcher, this.panel);

        this.logEl = this.panel.querySelector('.chat-log');
        this.creditsEl = this.panel.querySelector('.chat-credits');
        this.contextEl = this.panel.querySelector('.chat-context');
        this.inputEl = this.panel.querySelector('.chat-text');
        this.formEl = this.panel.querySelector('.chat-input');

        this.panel.querySelector('.chat-close').addEventListener('click', () => this._toggle(false));
        this.formEl.addEventListener('submit', (e) => { e.preventDefault(); this.send(); });

        this._addMessage('assistant',
            'Hi! Paste a link to add a place, or tell me to change one (tap a pin first for “this …”).');
    }

    _toggle(open) {
        this.panel.hidden = !open;
        this.launcher.hidden = open;
        if (open) {
            this._renderContext();
            this.inputEl.focus();
            this.logEl.scrollTop = this.logEl.scrollHeight;
        }
    }

    /** Show/hide the launcher based on whether the backend has a key. */
    setConfigured(ok) {
        this.launcher.hidden = !ok || !this.panel.hidden;
        if (!ok) this.panel.hidden = true;
    }

    // ── Selection context ────────────────────────────────────────────────
    setSelected(loc) {
        this.selected = loc;
        if (!this.panel.hidden) this._renderContext();
    }

    _renderContext() {
        // getSelected() is the live source of truth (backed by the map); only
        // fall back to our cached value if the caller didn't wire one up.
        const loc = this.deps.getSelected ? this.deps.getSelected() : this.selected;
        this.selected = loc || null;
        if (loc) {
            this.contextEl.hidden = false;
            this.contextEl.innerHTML = '';
            const label = document.createElement('span');
            label.textContent = `📍 ${loc.title}`;
            const clear = document.createElement('button');
            clear.type = 'button';
            clear.className = 'chat-context-clear';
            clear.title = 'Ignore selection';
            clear.textContent = '✕';
            clear.addEventListener('click', () => {
                this.deps.clearSelected?.();
                this.selected = null;
                this.contextEl.hidden = true;
            });
            this.contextEl.append(label, clear);
        } else {
            this.contextEl.hidden = true;
        }
    }

    // ── Messages ─────────────────────────────────────────────────────────
    _addMessage(role, text) {
        const el = document.createElement('div');
        el.className = `chat-msg ${role}`;
        el.textContent = text;           // textContent → no HTML injection
        this.logEl.appendChild(el);
        this.logEl.scrollTop = this.logEl.scrollHeight;
        return el;
    }

    // ── Send ─────────────────────────────────────────────────────────────
    async send() {
        const message = this.inputEl.value.trim();
        if (!message || this.busy) return;

        this.busy = true;
        this.inputEl.value = '';
        // Snapshot prior turns *before* adding this one — the backend appends
        // `message` itself, so sending it in history too would duplicate it.
        const priorHistory = this.history.slice(-6);
        this._addMessage('user', message);
        this.history.push({ role: 'user', content: message });

        const typing = this._addMessage('assistant typing', '…');

        // Read selection fresh at send time (in case a pin was tapped after opening).
        const sel = this.deps.getSelected ? this.deps.getSelected() : this.selected;

        try {
            const res = await this.deps.api.chat({
                trip: this.deps.getTripName(),
                message,
                selected_id: sel?.id ?? null,
                history: priorHistory,
            });
            typing.remove();
            const reply = res.reply || 'Done.';
            this._addMessage('assistant', reply);
            this.history.push({ role: 'assistant', content: reply });
            if (res.usage) this._renderUsage(res.usage);
            // Anything might have changed on the map — refresh in place, and
            // (if the turn added or located a place) jump to that pin.
            await this.deps.onMutate?.(res.focus_id || null);
            this._renderContext();
        } catch (err) {
            typing.remove();
            this._addMessage('assistant error', `⚠ ${err.message}`);
        } finally {
            this.busy = false;
            if (!this.panel.hidden) this.inputEl.focus();
        }
    }

    // ── Credits meter ────────────────────────────────────────────────────
    async _loadUsage() {
        try {
            const u = await this.deps.api.chatUsage();
            this.setConfigured(u.configured);
            this._renderUsage(u);
        } catch {
            this.setConfigured(false);
        }
    }

    _renderUsage(u) {
        if (typeof u.percent_remaining !== 'number') return;
        const pct = u.percent_remaining;
        this.creditsEl.textContent = `${pct}%`;
        this.creditsEl.title =
            `${u.remaining}/${u.limit} free requests left today — resets ${u.resets || 'daily'}`;
        this.creditsEl.classList.toggle('low', pct <= 30 && pct > 10);
        this.creditsEl.classList.toggle('crit', pct <= 10);
    }
}
