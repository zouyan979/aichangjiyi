class ChatUI {
    constructor(app) {
        this.app = app;
        this.$chat = document.getElementById('chat');
        this.$chatIn = document.getElementById('chatIn');
        this.$inp = document.getElementById('inp');
        this.$send = document.getElementById('send');
        this.$voice = document.getElementById('btnVoice');
        this.$mic = document.getElementById('btnMic');
        this.busy = false;
        this.abortController = null;
        this.voiceEnabled = false;
        this._currentAudio = null;
        this._audioCtx = null;
        this._recognition = null;
        this._recording = false;

        this._bind();
        this._initVoice();
        this._initSpeechRecognition();
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
        this.$voice.addEventListener('click', () => this._toggleVoice());
        this.$mic.addEventListener('click', () => this._toggleMic());
    }

    async _initVoice() {
        try {
            const cfg = await API.getTTSConfig();
            this.voiceEnabled = !!cfg.enabled;
            this._updateVoiceUI();
        } catch (e) { /* ignore */ }
    }

    _toggleVoice() {
        this.voiceEnabled = !this.voiceEnabled;
        this._updateVoiceUI();
        API.updateTTSConfig({ enabled: this.voiceEnabled }).catch(() => {});
    }

    _updateVoiceUI() {
        this.$voice.classList.toggle('active', this.voiceEnabled);
        const vSt = document.getElementById('vSt');
        if (vSt) {
            const dot = vSt.querySelector('.dot');
            dot.className = this.voiceEnabled ? 'dot on' : 'dot off';
            vSt.lastChild.textContent = this.voiceEnabled ? '语音: 开' : '语音: 关';
        }
    }

    _initSpeechRecognition() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            this.$mic.style.display = 'none';
            return;
        }
        // Web Speech API requires HTTPS or localhost
        const isSecure = location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
        if (!isSecure) {
            this.$mic.style.display = 'none';
            return;
        }
        this._recognition = new SR();
        this._recognition.lang = 'zh-CN';
        this._recognition.interimResults = true;
        this._recognition.continuous = true;
        this._recognition.maxAlternatives = 1;

        this._recognition.onresult = (e) => {
            let final = '', interim = '';
            for (let i = e.resultIndex; i < e.results.length; i++) {
                const t = e.results[i][0].transcript;
                if (e.results[i].isFinal) final += t;
                else interim += t;
            }
            if (final) {
                this.$inp.value = (this.$inp.value + final).trim();
                this.$inp.dispatchEvent(new Event('input'));
            }
        };

        this._recognition.onerror = (e) => {
            console.warn('[STT] Error:', e.error);
            if (e.error === 'not-allowed') {
                this._toast('麦克风权限被拒绝，请在浏览器地址栏左侧点击锁图标重新授权');
            } else if (e.error === 'audio-capture') {
                this._toast('未检测到麦克风设备');
            } else if (e.error === 'service-not-allowed') {
                this._toast('语音服务不可用，请使用 Chrome 或 Edge 浏览器');
            }
            this._stopRecording();
        };

        this._recognition.onend = () => {
            const wasRecording = this._recording;
            this._stopRecording();
            if (wasRecording) {
                const text = this.$inp.value.trim();
                if (text) this.send();
            }
        };
    }

    _toggleMic() {
        if (!this._recognition) {
            this._toast('当前浏览器不支持语音输入，请使用 Chrome 或 Edge');
            return;
        }
        if (this._recording) {
            this._recognition.stop();
        } else {
            this._startRecording();
        }
    }

    _startRecording() {
        if (this.busy) return;
        // Unlock audio context
        if (!this._audioCtx) {
            this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (this._audioCtx.state === 'suspended') this._audioCtx.resume();

        this._recording = true;
        this.$mic.classList.add('recording');
        this.$mic.title = '点击停止';
        this.$send.disabled = true;
        try {
            this._recognition.start();
        } catch (e) {
            this._stopRecording();
        }
    }

    _stopRecording() {
        this._recording = false;
        this.$mic.classList.remove('recording');
        this.$mic.title = '按住说话';
        this.$send.disabled = !this.$inp.value.trim();
    }

    _toast(msg) {
        const t = document.createElement('div');
        t.className = 'toast';
        t.textContent = msg;
        document.body.appendChild(t);
        setTimeout(() => t.remove(), 3000);
    }

    async send(textOverride) {
        const text = textOverride || this.$inp.value.trim();
        if (!text || this.busy) return;

        // Stop recording if active
        if (this._recording) {
            this._recording = false;
            this.$mic.classList.remove('recording');
            try { this._recognition.stop(); } catch (e) { /* ignore */ }
        }

        // Unlock audio context on user gesture
        if (!this._audioCtx) {
            this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (this._audioCtx.state === 'suspended') {
            this._audioCtx.resume();
        }

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
            // Trigger TTS if enabled
            if (this.voiceEnabled && fullContent && !gotError) {
                this._playVoiceForBubble(placeholder, fullContent);
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

    _playVoiceForBubble(bubbleEl, text) {
        // Stop any currently playing audio
        if (this._currentAudio) {
            this._currentAudio.pause();
            this._currentAudio = null;
        }

        // Clean text for TTS: remove markdown, code blocks, etc.
        let cleanText = text.replace(/```[\s\S]*?```/g, '').replace(/`[^`]+`/g, '');
        cleanText = cleanText.replace(/\*\*/g, '').replace(/\[代码已过滤\]/g, '').trim();
        if (!cleanText) return;

        // Truncate for TTS
        if (cleanText.length > 500) {
            const truncated = cleanText.substring(0, 500);
            const lastPunct = Math.max(truncated.lastIndexOf('。'), truncated.lastIndexOf('！'), truncated.lastIndexOf('？'), truncated.lastIndexOf('!'), truncated.lastIndexOf('?'));
            cleanText = lastPunct > 200 ? truncated.substring(0, lastPunct + 1) : truncated;
        }

        const msgC = bubbleEl.querySelector('.msgC');
        if (!msgC) return;

        // Add loading indicator
        const playerEl = document.createElement('div');
        playerEl.className = 'voice-player';
        playerEl.innerHTML = `<div class="voice-play"><svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg></div><div class="voice-bars"><div class="voice-bar" style="height:8px"></div><div class="voice-bar" style="height:12px"></div><div class="voice-bar" style="height:6px"></div><div class="voice-bar" style="height:14px"></div><div class="voice-bar" style="height:10px"></div></div><div class="voice-time">...</div>`;
        msgC.insertBefore(playerEl, msgC.querySelector('.meta'));

        API.synthesizeTTS(cleanText).then(resp => {
            if (!resp.audio) return;

            const timeEl = playerEl.querySelector('.voice-time');
            const audioCtx = this._audioCtx;

            if (audioCtx && audioCtx.state === 'running') {
                // Use AudioContext for reliable auto-play
                const raw = atob(resp.audio);
                const buf = new Uint8Array(raw.length);
                for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);

                audioCtx.decodeAudioData(buf.buffer, (decoded) => {
                    const dur = Math.round(decoded.duration);
                    timeEl.textContent = dur > 60 ? Math.floor(dur / 60) + ':' + String(dur % 60).padStart(2, '0') : dur + 's';

                    let source = null;
                    const playAudio = () => {
                        if (source) { source.stop(); source = null; playerEl.classList.remove('playing'); this._currentAudio = null; return; }
                        source = audioCtx.createBufferSource();
                        source.buffer = decoded;
                        source.connect(audioCtx.destination);
                        source.onended = () => { playerEl.classList.remove('playing'); source = null; this._currentAudio = null; };
                        source.start();
                        playerEl.classList.add('playing');
                        this._currentAudio = { pause: () => { if (source) { source.stop(); source = null; } } };
                    };

                    playerEl.addEventListener('click', playAudio);
                    // Auto-play immediately
                    playAudio();
                }, () => {
                    // Decode failed, fallback
                    timeEl.textContent = '播放失败';
                });
            } else {
                // Fallback: use Audio element
                const audio = new Audio('data:audio/wav;base64,' + resp.audio);
                this._currentAudio = audio;
                audio.addEventListener('loadedmetadata', () => {
                    const dur = Math.round(audio.duration);
                    timeEl.textContent = dur > 60 ? Math.floor(dur / 60) + ':' + String(dur % 60).padStart(2, '0') : dur + 's';
                });
                audio.addEventListener('ended', () => { playerEl.classList.remove('playing'); this._currentAudio = null; });
                playerEl.addEventListener('click', () => {
                    if (audio.paused) { audio.play(); playerEl.classList.add('playing'); }
                    else { audio.pause(); playerEl.classList.remove('playing'); }
                });
                audio.play().then(() => playerEl.classList.add('playing')).catch(() => { timeEl.textContent = '点击播放'; });
            }
        }).catch(() => {
            playerEl.remove();
        });
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
