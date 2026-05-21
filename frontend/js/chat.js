class ChatUI {
    constructor(app) {
        this.app = app;
        this.$chat = document.getElementById('chat');
        this.$chatIn = document.getElementById('chatIn');
        this.$inp = document.getElementById('inp');
        this.$send = document.getElementById('send');
        this.busy = false;
        this.abortController = null;

        this._bind();
    }

    _bind() {
        this.$inp.addEventListener('input', () => {
            this.$inp.style.height = 'auto';
            this.$inp.style.height = Math.min(this.$inp.scrollHeight, 150) + 'px';
            this.$send.disabled = !this.$inp.value.trim() || this.busy;
        });
        this.$inp.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.send(); }
        });
        this.$send.addEventListener('click', () => this.send());
    }

    async send(textOverride) {
        const text = textOverride || this.$inp.value.trim();
        if (!text || this.busy) return;

        const convId = this.app.getActiveConversation();
        if (!convId) return;

        if (!textOverride) {
            this.$inp.value = '';
            this.$inp.style.height = 'auto';
        }
        this.$send.disabled = true;
        this._hideWelcome();
        this.busy = true;

        if (!textOverride) {
            this._appendMsg({ role: 'user', content: text, created_at: new Date().toISOString() });
        }

        const placeholder = this._placeholder();
        let fullContent = '';
        let gotError = false;

        try {
            this.abortController = new AbortController();
            for await (const event of API.streamChat(convId, text)) {
                if (event.type === 'chunk') {
                    fullContent += event.content;
                    this._updateBubble(placeholder, fullContent);
                } else if (event.type === 'done') {
                    this._finalize(placeholder, fullContent, false);
                } else if (event.type === 'error') {
                    gotError = true;
                    this._finalizeWithError(placeholder, fullContent, event.message);
                }
            }
            if (fullContent && !placeholder.dataset.finalized) {
                this._finalize(placeholder, fullContent, false);
            }
            if (!fullContent && !gotError && !placeholder.dataset.finalized) {
                this._finalizeWithError(placeholder, '', '未收到任何响应，请检查网络或API配置');
            }
        } catch (e) {
            gotError = true;
            let msg = e.message;
            if (e.name === 'AbortError' || msg.includes('超时')) {
                msg = '请求超时，请检查网络连接或API配置';
            } else if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
                msg = '网络连接失败，请检查网络状态';
            }
            this._finalizeWithError(placeholder, fullContent, msg);
        } finally {
            this.busy = false;
            this.abortController = null;
            this.$send.disabled = !this.$inp.value.trim();
            this.app.updateStatus();
            this.app.onChatComplete();
        }
    }

    async loadHistory(convId) {
        console.log('[Chat] Loading history for convId:', convId);
        // Clear all children
        while (this.$chatIn.firstChild) {
            this.$chatIn.removeChild(this.$chatIn.firstChild);
        }
        // Re-add welcome element
        this.$chatIn.innerHTML = `<div class="welcome" id="welcome">
            <h2>你好，我是 Memoria</h2>
            <div class="aline"></div>
            <p>一个有长期记忆的 AI 伙伴。我会记住我们的每一次对话，越来越了解你。</p>
            <p class="hint">点击右上角齿轮配置 API，然后开始聊天。</p>
        </div>`;

        try {
            const messages = await API.getMessages(convId, 200);
            console.log('[Chat] Loaded messages:', messages.length);
            if (messages.length > 0) {
                this._hideWelcome();
                for (const m of messages) {
                    this._appendMsg(m, false);
                }
            }
        } catch (e) {
            console.error('[Chat] Load history error:', e);
            // Show error in chat area
            const welcome = document.getElementById('welcome');
            if (welcome) {
                welcome.querySelector('.hint').textContent = '加载历史记录失败: ' + e.message;
            }
        }
    }

    _hideWelcome() {
        const el = document.getElementById('welcome');
        if (el) el.style.display = 'none';
    }

    showProactiveMessage(msg) {
        this._hideWelcome();
        this._appendMsg({
            role: 'assistant',
            content: msg.content,
            is_proactive: true,
            created_at: msg.created_at || new Date().toISOString()
        });
    }

    _appendMsg(msg, anim = true) {
        const el = document.createElement('div');
        const type = msg.role === 'user' ? 'user' : msg.is_proactive ? 'pro' : 'ai';
        el.className = 'msg ' + type;
        if (!anim) { el.style.animation = 'none'; el.style.opacity = '1'; }

        const time = this._formatTime(msg.created_at);
        const displayContent = msg.role === 'assistant' ? this._filterCode(msg.content) : msg.content;
        el.innerHTML = `<div class="msgC"><div class="bub">${this._esc(displayContent)}</div>` +
            `<div class="meta">${msg.is_proactive ? '<span class="tag">主动消息</span>' : ''}<span>${time}</span></div></div>`;

        this.$chatIn.appendChild(el);
        this._scroll();
    }

    _placeholder() {
        const el = document.createElement('div');
        el.className = 'msg ai';
        el.innerHTML = `<div class="msgC"><div class="bub"><div class="typing"><span></span><span></span><span></span></div></div></div>`;
        this.$chatIn.appendChild(el);
        this._scroll();
        return el;
    }

    _updateBubble(el, txt) {
        el.querySelector('.bub').innerHTML = this._fmt(this._filterCode(txt));
        this._scroll();
    }

    _finalize(el, txt, isProactive) {
        el.dataset.finalized = '1';
        const bub = el.querySelector('.bub');
        bub.innerHTML = this._fmt(this._filterCode(txt));
        const c = el.querySelector('.msgC');
        const time = this._formatTime(new Date().toISOString());
        c.innerHTML += `<div class="meta">${isProactive ? '<span class="tag">主动消息</span>' : ''}<span>${time}</span></div>`;
        this._scroll();
    }

    _finalizeWithError(el, partialContent, errorMsg) {
        el.dataset.finalized = '1';
        el.dataset.error = '1';
        const bub = el.querySelector('.bub');
        let html = '';
        if (partialContent) {
            html += `<div style="opacity:.7;margin-bottom:8px">${this._fmt(this._filterCode(partialContent))}</div>`;
        }
        html += `<div style="color:var(--err);font-size:.85rem">⚠ ${this._esc(errorMsg)}</div>`;
        html += `<button class="btnO retryBtn" style="margin-top:6px;font-size:.8rem;padding:3px 12px">重试</button>`;
        bub.innerHTML = html;
        // Bind retry
        const retryBtn = bub.querySelector('.retryBtn');
        if (retryBtn) {
            retryBtn.addEventListener('click', () => {
                el.remove();
                // Find the last user message in chat
                const msgs = this.$chatIn.querySelectorAll('.msg.user');
                const lastUserMsg = msgs[msgs.length - 1];
                if (lastUserMsg) {
                    const text = lastUserMsg.querySelector('.bub').textContent;
                    this.send(text);
                }
            });
        }
        const c = el.querySelector('.msgC');
        const time = this._formatTime(new Date().toISOString());
        c.innerHTML += `<div class="meta"><span>${time}</span></div>`;
        this._scroll();
    }

    _filterCode(txt) {
        // Check if custom rules explicitly allow code output
        const rules = (this.app.persona?.personaData?.custom_rules || '').toLowerCase();
        const allowKeywords = ['可以输出代码', '允许代码', '可以显示代码', '代码可以', 'allow code', 'show code'];
        const explicitlyAllowed = allowKeywords.some(k => rules.includes(k));
        if (explicitlyAllowed) return txt;

        // Default: strip fenced code blocks (```...```)
        let filtered = txt.replace(/```[\s\S]*?```/g, '\n[代码已过滤]\n');
        // Handle incomplete code block during streaming (opening ``` without closing)
        filtered = filtered.replace(/```[\s\S]*$/, '\n[代码生成中...]');
        return filtered;
    }

    _sumIndicator() {
        const el = document.createElement('div');
        el.className = 'sumInd';
        el.innerHTML = '🧠 正在整理记忆...<span class="d"><span>.</span><span>.</span><span>.</span></span>';
        this.$chatIn.appendChild(el);
        this._scroll();
        return el;
    }

    _formatTime(isoStr) {
        try {
            const d = new Date(isoStr);
            return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        } catch {
            return '';
        }
    }

    _esc(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    _fmt(t) {
        return this._esc(t)
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/`(.*?)`/g, '<code style="background:var(--surface2);padding:1px 5px;border-radius:3px;font-family:var(--fm);font-size:.85em">$1</code>');
    }

    _scroll() {
        requestAnimationFrame(() => { this.$chat.scrollTop = this.$chat.scrollHeight; });
    }
}
