const API = {
    base: '/api',

    async _fetch(path, options = {}) {
        const url = this.base + path;
        console.log('[API] Fetching:', url);
        const resp = await fetch(url, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options
        });
        if (!resp.ok) {
            const text = await resp.text().catch(() => '');
            throw new Error(`API错误 ${resp.status}: ${text.slice(0, 200)}`);
        }
        const data = await resp.json();
        console.log('[API] Response:', url, 'items:', Array.isArray(data) ? data.length : 'ok');
        return data;
    },

    // Config
    listConfigs() { return this._fetch('/config/api'); },
    createConfig(data) { return this._fetch('/config/api', { method: 'POST', body: JSON.stringify(data) }); },
    updateConfig(id, data) { return this._fetch(`/config/api/${id}`, { method: 'PUT', body: JSON.stringify(data) }); },
    deleteConfig(id) { return this._fetch(`/config/api/${id}`, { method: 'DELETE' }); },
    activateConfig(id) { return this._fetch(`/config/api/${id}/activate`, { method: 'POST' }); },
    testConfig(data) { return this._fetch('/config/api/test', { method: 'POST', body: JSON.stringify(data) }); },

    // Conversations
    listConversations() { return this._fetch('/conversations'); },
    createConversation(title) { return this._fetch('/conversations', { method: 'POST', body: JSON.stringify({ title }) }); },
    updateConversation(id, data) { return this._fetch(`/conversations/${id}`, { method: 'PUT', body: JSON.stringify(data) }); },
    deleteConversation(id) { return this._fetch(`/conversations/${id}`, { method: 'DELETE' }); },
    getMessages(convId, limit = 100, offset = 0) { return this._fetch(`/conversations/${convId}/messages?limit=${limit}&offset=${offset}`); },

    // Chat (streaming)
    async *streamChat(conversationId, content) {
        const resp = await fetch(this.base + '/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversation_id: conversationId, content })
        });
        if (!resp.ok) {
            const text = await resp.text().catch(() => '');
            throw new Error(`API错误 ${resp.status}: ${text.slice(0, 200)}`);
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
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
    },

    stopChat(conversationId) {
        return this._fetch(`/chat/stop?conversation_id=${conversationId}`, { method: 'POST' });
    },

    // Memory
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

    // Persona
    getPersona() { return this._fetch('/persona'); },
    updatePersona(data) { return this._fetch('/persona', { method: 'PUT', body: JSON.stringify(data) }); },
    resetPersona() { return this._fetch('/persona/reset', { method: 'POST' }); },
    getGrowthLog() { return this._fetch('/persona/growth-log'); },

    // Proactive
    getProactiveConfig() { return this._fetch('/proactive/config'); },
    updateProactiveConfig(data) { return this._fetch('/proactive/config', { method: 'PUT', body: JSON.stringify(data) }); },
    getProactivePending() { return this._fetch('/proactive/pending'); },
    getProactiveLog(limit = 20) { return this._fetch(`/proactive/log?limit=${limit}`); },
    triggerProactive() { return this._fetch('/proactive/trigger', { method: 'POST' }); }
};
