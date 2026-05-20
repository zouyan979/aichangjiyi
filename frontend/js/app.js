class App {
    constructor() {
        this.activeConvId = null;
        this.chat = new ChatUI(this);
        this.memory = new MemoryPanel(this);
        this.persona = new PersonaPanel(this);
        this.settings = new SettingsModal(this);
        this.proactive = new ProactiveManager(this);

        this.$mSt = document.getElementById('mSt');
        this.$pSt = document.getElementById('pSt');
        this.$convSel = document.getElementById('convSel');

        this._bind();
        this._initTheme();
        this._init();
    }

    async _init() {
        try {
            console.log('[App] Initializing...');
            await this._loadConversations();
            console.log('[App] Conversations loaded, activeConvId:', this.activeConvId);
            this.updateStatus();
            this.proactive.start();
            console.log('[App] Init complete');
        } catch (e) {
            console.error('[App] Init error:', e);
        }
    }

    _bind() {
        document.getElementById('btnMemory').addEventListener('click', () => this.memory.open());
        document.getElementById('btnPersona').addEventListener('click', () => this.persona.open());
        document.getElementById('btnSettings').addEventListener('click', () => this.settings.open());
        document.getElementById('btnNewConv').addEventListener('click', () => this._newConversation());
        document.getElementById('btnDelConv').addEventListener('click', () => this._deleteConversation());
        document.getElementById('btnTheme').addEventListener('click', () => this._toggleTheme());

        this.$convSel?.addEventListener('change', () => {
            this.activeConvId = parseInt(this.$convSel.value);
            this.chat.loadHistory(this.activeConvId);
            this.updateStatus();
        });
    }

    // ===== Theme =====
    _initTheme() {
        const saved = localStorage.getItem('memoria_theme');
        if (saved === 'light') {
            document.documentElement.setAttribute('data-theme', 'light');
        } else if (saved === 'dark') {
            document.documentElement.removeAttribute('data-theme');
        } else {
            // Follow system
            if (window.matchMedia('(prefers-color-scheme: light)').matches) {
                document.documentElement.setAttribute('data-theme', 'light');
            }
        }
        // Listen for system theme changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
            if (!localStorage.getItem('memoria_theme')) {
                if (e.matches) {
                    document.documentElement.removeAttribute('data-theme');
                } else {
                    document.documentElement.setAttribute('data-theme', 'light');
                }
            }
        });
    }

    _toggleTheme() {
        const isLight = document.documentElement.getAttribute('data-theme') === 'light';
        // Add transition class first, wait for it to apply, then change theme
        document.documentElement.classList.add('theme-switching');
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                if (isLight) {
                    document.documentElement.removeAttribute('data-theme');
                    localStorage.setItem('memoria_theme', 'dark');
                } else {
                    document.documentElement.setAttribute('data-theme', 'light');
                    localStorage.setItem('memoria_theme', 'light');
                }
                setTimeout(() => document.documentElement.classList.remove('theme-switching'), 900);
            });
        });
    }

    // ===== Conversations =====
    async _loadConversations() {
        try {
            const convs = await API.listConversations();
            console.log('[App] Conversations:', convs.length);
            if (!convs.length) {
                await API.createConversation('默认对话');
                return this._loadConversations();
            }
            this.$convSel.innerHTML = convs.map(c =>
                `<option value="${c.id}">${this._esc(c.title)}</option>`
            ).join('');
            this.activeConvId = convs[0].id;
            this.$convSel.value = this.activeConvId;
            console.log('[App] Loading history for conv:', this.activeConvId);
            await this.chat.loadHistory(this.activeConvId);
        } catch (e) {
            console.error('[App] Load conversations error:', e);
            // Show error to user
            const hint = document.getElementById('welcomeHint');
            if (hint) hint.textContent = '无法连接到服务器: ' + e.message;
        }
    }

    async _newConversation() {
        const title = prompt('对话标题：', '新对话');
        if (!title) return;
        try {
            const result = await API.createConversation(title);
            await this._loadConversations();
            this.$convSel.value = result.id;
            this.activeConvId = result.id;
            await this.chat.loadHistory(this.activeConvId);
        } catch (e) {
            this.toast('创建失败: ' + e.message);
        }
    }

    async _deleteConversation() {
        if (!this.activeConvId) return;
        if (!confirm('确定删除当前对话？')) return;
        try {
            await API.deleteConversation(this.activeConvId);
            await this._loadConversations();
        } catch (e) {
            this.toast('删除失败: ' + e.message);
        }
    }

    getActiveConversation() {
        return this.activeConvId;
    }

    onProactiveMessage(msg) {
        this.chat.showProactiveMessage(msg);
        this.updateStatus();
    }

    async onChatComplete() {
        setTimeout(() => this.proactive.poll(), 2000);
    }

    async updateStatus() {
        try {
            const [stats, proConfig] = await Promise.all([
                API.getStats(),
                API.getProactiveConfig()
            ]);
            const on = stats.total_messages > 0 || stats.total_summaries > 0;
            this.$mSt.innerHTML = `<span class="dot ${on ? 'on' : 'off'}"></span>记忆: ${stats.total_messages}条消息 · ${stats.total_summaries}段摘要`;
            const pon = proConfig.enabled;
            this.$pSt.innerHTML = `<span class="dot ${pon ? 'on' : 'off'}"></span>主动消息: ${pon ? '每' + (proConfig.interval_minutes || 30) + '分钟' : '关闭'}`;
        } catch (e) {
            // Silent fail
        }
    }

    toast(msg, type = '') {
        const el = document.createElement('div');
        el.className = 'toast' + (type === 'ok' ? ' ok' : '');
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3000);
    }

    _esc(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    try {
        window.app = new App();
        console.log('[Memoria] Initialized');
    } catch (e) {
        console.error('[Memoria] Init failed:', e);
        document.body.innerHTML = `<div style="color:var(--err);padding:40px;text-align:center">初始化出错: ${e.message}</div>`;
    }
});
