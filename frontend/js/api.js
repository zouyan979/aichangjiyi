const API = {
    base: '/api',
    _online: navigator.onLine,
    _listeners: [],
    _token: localStorage.getItem('memoria_token') || null,

    init() {
        window.addEventListener('online', () => {
            this._online = true;
            this._notify('online');
            this._flushQueue();
        });
        window.addEventListener('offline', () => {
            this._online = false;
            this._notify('offline');
        });
    },

    setToken(token) {
        this._token = token;
        if (token) {
            localStorage.setItem('memoria_token', token);
        } else {
            localStorage.removeItem('memoria_token');
        }
    },

    clearToken() {
        this._token = null;
        localStorage.removeItem('memoria_token');
    },

    onStatusChange(fn) {
        this._listeners.push(fn);
    },

    _notify(status) {
        this._listeners.forEach(fn => fn(status));
    },

    isOnline() {
        return this._online;
    },

    // ===== Request queue for offline mode =====
    _queue: [],

    _enqueue(path, options) {
        return new Promise((resolve, reject) => {
            this._queue.push({ path, options, resolve, reject });
            this._notify('queued');
        });
    },

    async _flushQueue() {
        const queue = [...this._queue];
        this._queue = [];
        for (const item of queue) {
            try {
                const result = await this._fetch(item.path, item.options, true);
                item.resolve(result);
            } catch (e) {
                item.reject(e);
            }
        }
        if (queue.length) this._notify('flushed');
    },

    getQueueSize() {
        return this._queue.length;
    },

    // ===== Core fetch with timeout + retry =====
    async _fetch(path, options = {}, _noQueue = false) {
        const url = this.base + path;
        const timeout = options.timeout || 15000;
        const maxRetries = options._retries ?? 1;
        let lastError;

        for (let attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeout);

                const headers = { 'Content-Type': 'application/json', ...options.headers };
                if (this._token) {
                    headers['Authorization'] = 'Bearer ' + this._token;
                }

                const resp = await fetch(url, {
                    ...options,
                    headers,
                    signal: controller.signal
                });
                clearTimeout(timer);

                // Handle 401 — show login screen
                if (resp.status === 401) {
                    this._notify('auth_required');
                    throw new Error('需要登录');
                }

                if (!resp.ok) {
                    const text = await resp.text().catch(() => '');
                    throw new Error(`API错误 ${resp.status}: ${text.slice(0, 200)}`);
                }
                const data = await resp.json();
                return data;
            } catch (e) {
                lastError = e;
                if (e.message === '需要登录') throw e;
                if (e.name === 'AbortError') {
                    throw new Error('请求超时，请检查网络连接');
                }
                if (e.message?.startsWith('API错误 4')) {
                    throw e;
                }
                if (attempt < maxRetries) {
                    await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
                }
            }
        }
        throw lastError;
    },

    // ===== Streaming with timeout + reconnect =====
    async *streamChat(conversationId, content) {
        const maxStreamRetries = 1;

        for (let attempt = 0; attempt <= maxStreamRetries; attempt++) {
            try {
                const controller = new AbortController();
                // 30s timeout for initial connection
                const timer = setTimeout(() => controller.abort(), 30000);

                const headers = { 'Content-Type': 'application/json' };
                if (this._token) {
                    headers['Authorization'] = 'Bearer ' + this._token;
                }
                const resp = await fetch(this.base + '/chat', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ conversation_id: conversationId, content }),
                    signal: controller.signal
                });
                clearTimeout(timer);

                if (!resp.ok) {
                    const text = await resp.text().catch(() => '');
                    throw new Error(`API错误 ${resp.status}: ${text.slice(0, 200)}`);
                }

                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let lastChunkTime = Date.now();

                // Idle timeout watchdog: 60s with no data = connection dead
                const watchdog = setInterval(() => {
                    if (Date.now() - lastChunkTime > 60000) {
                        reader.cancel();
                        clearInterval(watchdog);
                    }
                }, 10000);

                try {
                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        lastChunkTime = Date.now();
                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split('\n');
                        buffer = lines.pop() || '';
                        for (const line of lines) {
                            const trimmed = line.trim();
                            if (trimmed.startsWith('data: ')) {
                                try {
                                    yield JSON.parse(trimmed.slice(6));
                                } catch { }
                            }
                        }
                    }
                } finally {
                    clearInterval(watchdog);
                }
                return; // Success, no retry needed
            } catch (e) {
                if (e.name === 'AbortError') {
                    if (attempt < maxStreamRetries) {
                        yield { type: 'chunk', content: '\n[连接超时，正在重试...]\n' };
                        continue;
                    }
                    throw new Error('连接超时，请检查网络后重试');
                }
                if (e.message?.includes('Failed to fetch') || e.message?.includes('NetworkError')) {
                    if (attempt < maxStreamRetries) {
                        yield { type: 'chunk', content: '\n[网络中断，正在重试...]\n' };
                        await new Promise(r => setTimeout(r, 2000));
                        continue;
                    }
                    throw new Error('网络连接中断，请检查网络');
                }
                throw e;
            }
        }
    },

    stopChat(conversationId) {
        return this._fetch(`/chat/stop?conversation_id=${conversationId}`, { method: 'POST' });
    },

    // ===== Config =====
    listConfigs() { return this._fetch('/config/api'); },
    createConfig(data) { return this._fetch('/config/api', { method: 'POST', body: JSON.stringify(data) }); },
    updateConfig(id, data) { return this._fetch(`/config/api/${id}`, { method: 'PUT', body: JSON.stringify(data) }); },
    deleteConfig(id) { return this._fetch(`/config/api/${id}`, { method: 'DELETE' }); },
    activateConfig(id) { return this._fetch(`/config/api/${id}/activate`, { method: 'POST' }); },
    testConfig(data) { return this._fetch('/config/api/test', { method: 'POST', body: JSON.stringify(data) }); },

    // ===== Conversations =====
    listConversations() { return this._fetch('/conversations'); },
    createConversation(title) { return this._fetch('/conversations', { method: 'POST', body: JSON.stringify({ title }) }); },
    updateConversation(id, data) { return this._fetch(`/conversations/${id}`, { method: 'PUT', body: JSON.stringify(data) }); },
    deleteConversation(id) { return this._fetch(`/conversations/${id}`, { method: 'DELETE' }); },
    getMessages(convId, limit = 100, offset = 0) { return this._fetch(`/conversations/${convId}/messages?limit=${limit}&offset=${offset}`); },

    // ===== Memory =====
    getProfile() { return this._fetch('/memory/profile'); },
    addProfileItem(data) { return this._fetch('/memory/profile', { method: 'POST', body: JSON.stringify(data) }); },
    deleteProfileItem(category, id) { return this._fetch(`/memory/profile/${category}/${id}`, { method: 'DELETE' }); },
    getCoreFacts() { return this._fetch('/memory/core-facts'); },
    addCoreFact(data) { return this._fetch('/memory/core-facts', { method: 'POST', body: JSON.stringify(data) }); },
    updateCoreFact(id, data) { return this._fetch(`/memory/core-facts/${id}`, { method: 'PUT', body: JSON.stringify(data) }); },
    deleteCoreFact(id) { return this._fetch(`/memory/core-facts/${id}`, { method: 'DELETE' }); },
    getSummaries(convId, limit = 50) { return this._fetch(`/memory/summaries?limit=${limit}${convId ? '&conversation_id=' + convId : ''}`); },
    getStats() { return this._fetch('/memory/stats'); },
    getContextPreview(q = '你好') { return this._fetch(`/memory/context-preview?q=${encodeURIComponent(q)}`); },
    exportMemory() { return this._fetch('/memory/export'); },
    importMemory(data) { return this._fetch('/memory/import', { method: 'POST', body: JSON.stringify(data) }); },
    clearMemory() { return this._fetch('/memory/clear', { method: 'POST' }); },

    // ===== Persona =====
    getPersona() { return this._fetch('/persona'); },
    updatePersona(data) { return this._fetch('/persona', { method: 'PUT', body: JSON.stringify(data) }); },
    resetPersona() { return this._fetch('/persona/reset', { method: 'POST' }); },
    getGrowthLog() { return this._fetch('/persona/growth-log'); },

    // ===== Proactive =====
    getProactiveConfig() { return this._fetch('/proactive/config'); },
    updateProactiveConfig(data) { return this._fetch('/proactive/config', { method: 'PUT', body: JSON.stringify(data) }); },
    getProactivePending() { return this._fetch('/proactive/pending'); },
    getProactiveLog(limit = 20) { return this._fetch(`/proactive/log?limit=${limit}`); },
    triggerProactive() { return this._fetch('/proactive/trigger', { method: 'POST' }); },

    // ===== Auth =====
    authStatus() { return this._fetch('/auth/status'); },
    authLogin(password) { return this._fetch('/auth/login', { method: 'POST', body: JSON.stringify({ password }) }); },
    authSetPassword(password) { return this._fetch('/auth/set-password', { method: 'POST', body: JSON.stringify({ password }) }); },
    authRemovePassword() { return this._fetch('/auth/remove-password', { method: 'POST' }); }
};

API.init();
