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
        this._initNetworkBanner();
        this._init();
    }

    async _init() {
        try {
            console.log('[App] Initializing...');
            // Check auth status first
            await this._initAuth();
            await this._loadConversations();
            console.log('[App] Conversations loaded, activeConvId:', this.activeConvId);
            this.updateStatus();
            this.proactive.start();
            console.log('[App] Init complete');
        } catch (e) {
            console.error('[App] Init error:', e);
        }
    }

    async _initAuth() {
        const loginScreen = document.getElementById('loginScreen');
        const loginBtn = document.getElementById('loginBtn');
        const loginPw = document.getElementById('loginPw');
        const loginErr = document.getElementById('loginErr');

        // Check if server requires auth
        let status;
        try {
            status = await API.authStatus();
        } catch {
            return; // Can't reach server, let it fail later
        }

        if (!status.required) return; // No password set, skip

        // If we have a token, try a test request
        if (API._token) {
            try {
                await API.getStats();
                return; // Token valid
            } catch (e) {
                if (e.message !== '需要登录') return; // Other error
                API.clearToken(); // Token expired
            }
        }

        // Show login screen
        loginScreen.style.display = 'flex';

        return new Promise((resolve) => {
            const doLogin = async () => {
                const pw = loginPw.value.trim();
                if (!pw) return;
                loginErr.style.display = 'none';
                try {
                    const result = await API.authLogin(pw);
                    API.setToken(result.token);
                    loginScreen.style.display = 'none';
                    resolve();
                } catch (e) {
                    loginErr.textContent = e.message.includes('密码') ? e.message : '登录失败';
                    loginErr.style.display = 'block';
                    loginPw.select();
                }
            };
            loginBtn.onclick = doLogin;
            loginPw.onkeydown = (e) => { if (e.key === 'Enter') doLogin(); };
        });
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

    // ===== Network Status =====
    _initNetworkBanner() {
        // Create banner element
        this.$netBanner = document.createElement('div');
        this.$netBanner.className = 'net-banner';
        this.$netBanner.style.display = 'none';
        document.body.prepend(this.$netBanner);

        API.onStatusChange((status) => {
            if (status === 'auth_required') {
                API.clearToken();
                const loginScreen = document.getElementById('loginScreen');
                const loginPw = document.getElementById('loginPw');
                const loginErr = document.getElementById('loginErr');
                loginScreen.style.display = 'flex';
                loginErr.textContent = '登录已过期，请重新输入密码';
                loginErr.style.display = 'block';
                loginPw.value = '';
                loginPw.focus();
            } else if (status === 'offline') {
                this._showNetBanner('网络已断开，消息将在恢复后自动发送', 'warn');
            } else if (status === 'online') {
                this._showNetBanner('网络已恢复', 'ok');
                setTimeout(() => this._hideNetBanner(), 3000);
            } else if (status === 'queued') {
                const n = API.getQueueSize();
                if (n > 0) {
                    this._showNetBanner(`离线中，${n} 条操作待发送`, 'warn');
                }
            } else if (status === 'flushed') {
                this._showNetBanner('离线操作已同步', 'ok');
                setTimeout(() => this._hideNetBanner(), 3000);
            }
        });

        // Periodic health check (every 30s)
        this._serverDown = false;
        setInterval(async () => {
            if (!API.isOnline()) return;
            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(), 5000);
            try {
                await fetch('/api/memory/stats', { method: 'GET', signal: ctrl.signal });
                clearTimeout(timer);
                if (this._serverDown) {
                    this._serverDown = false;
                    this._hideNetBanner();
                }
            } catch {
                clearTimeout(timer);
                if (!this._serverDown) {
                    this._serverDown = true;
                    this._showNetBanner('无法连接到服务器，请检查后端是否运行', 'err');
                }
            }
        }, 30000);
    }

    _showNetBanner(msg, type) {
        this.$netBanner.textContent = msg;
        this.$netBanner.className = 'net-banner show ' + type;
        this.$netBanner.style.display = '';
    }

    _hideNetBanner() {
        this.$netBanner.classList.remove('show');
        setTimeout(() => { this.$netBanner.style.display = 'none'; }, 400);
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
        // Auto-refresh memory panel if it's open
        if (this.memory.isOpen()) {
            this.memory.render();
        }
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
