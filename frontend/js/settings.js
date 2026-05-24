class SettingsModal {
    constructor(app) {
        this.app = app;
        this.$modal = document.getElementById('setModal');
        this.$tRes = document.getElementById('tRes');
        this.$tglPro = document.getElementById('tglPro');
        this.$tglSearch = document.getElementById('tglSearch');
        this._originalKey = '';  // track the masked key as loaded
        this._originalSearchKey = '';
        this._bind();
    }

    _bind() {
        document.getElementById('setBg').addEventListener('click', () => this.close());
        document.getElementById('closeSet').addEventListener('click', () => this.close());
        this.$tglPro.addEventListener('click', () => this.$tglPro.classList.toggle('on'));
        this.$tglSearch.addEventListener('click', () => this.$tglSearch.classList.toggle('on'));
        document.getElementById('tglVoice').addEventListener('click', () => document.getElementById('tglVoice').classList.toggle('on'));
        document.getElementById('btnTest').addEventListener('click', () => this._testApi());
        document.getElementById('btnSave').addEventListener('click', () => this._save());

        // API Key toggle visibility
        document.getElementById('toggleKey').addEventListener('click', () => {
            const inp = document.getElementById('sKey');
            const icon = document.getElementById('eyeIcon');
            if (inp.type === 'password') {
                inp.type = 'text';
                icon.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
            } else {
                inp.type = 'password';
                icon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
            }
        });

        // API guide items click
        document.querySelectorAll('.apiGuideItem').forEach(el => {
            el.addEventListener('click', () => {
                document.getElementById('sUrl').value = el.dataset.url;
                document.getElementById('sModel').value = el.dataset.model;
            });
        });
    }

    async open() {
        await this._loadCurrent();
        this.$modal.classList.add('show');
    }

    close() {
        this.$modal.classList.remove('show');
        this.$tRes.style.display = 'none';
    }

    async _loadCurrent() {
        try {
            const [configs, proConfig, searchCfg, weatherCfg, ttsCfg] = await Promise.all([
                API.listConfigs(),
                API.getProactiveConfig(),
                API.getSearchConfig().catch(() => ({ enabled: false, tavily_api_key: '' })),
                API.getWeatherConfig().catch(() => ({ city: '' })),
                API.getTTSConfig().catch(() => ({ enabled: false, voice: '冰糖' }))
            ]);

            // Clear fields first
            document.getElementById('sUrl').value = '';
            document.getElementById('sKey').value = '';
            document.getElementById('sModel').value = '';
            document.getElementById('sVisionModel').value = '';
            document.getElementById('sTemp').value = '0.8';

            // Fill if active config exists
            const active = configs.find(c => c.is_active);
            if (active) {
                document.getElementById('sUrl').value = active.base_url || '';
                document.getElementById('sKey').value = active.api_key || '';
                this._originalKey = active.api_key || '';
                document.getElementById('sModel').value = active.model || '';
                document.getElementById('sVisionModel').value = active.vision_model || '';
                document.getElementById('sTemp').value = active.temperature || 0.8;
            }

            this.$tglPro.classList.toggle('on', !!proConfig.enabled);
            document.getElementById('sMaxDaily').value = proConfig.max_daily_messages || 5;
            document.getElementById('sAbsence').value = proConfig.absence_hours || 4;

            // Search config
            this.$tglSearch.classList.toggle('on', !!searchCfg.enabled);
            document.getElementById('sSearchKey').value = searchCfg.tavily_api_key || '';
            this._originalSearchKey = searchCfg.tavily_api_key || '';

            // Weather city
            document.getElementById('sCity').value = weatherCfg.city || '';

            // TTS config
            document.getElementById('tglVoice').classList.toggle('on', !!ttsCfg.enabled);
            document.getElementById('sVoice').value = ttsCfg.voice || '冰糖';
        } catch (e) {
            console.error('Load settings error:', e);
        }
    }

    async _testApi() {
        const btn = document.getElementById('btnTest');
        const url = document.getElementById('sUrl').value.trim();
        const key = document.getElementById('sKey').value.trim();
        const model = document.getElementById('sModel').value.trim();

        if (!url || !key || !model) {
            this.$tRes.className = 'tRes er';
            this.$tRes.textContent = '请填写 API 地址、Key 和模型名称';
            this.$tRes.style.display = 'block';
            return;
        }

        btn.disabled = true;
        btn.textContent = '测试中...';
        this.$tRes.style.display = 'none';

        try {
            await API.testConfig({
                base_url: url,
                api_key: key,
                model: model,
                name: 'test',
                temperature: 0.8,
                max_tokens: 2048
            });
            this.$tRes.className = 'tRes ok';
            this.$tRes.textContent = '连接成功';
            this.$tRes.style.display = 'block';
        } catch (e) {
            this.$tRes.className = 'tRes er';
            this.$tRes.textContent = e.message;
            this.$tRes.style.display = 'block';
        } finally {
            btn.disabled = false;
            btn.textContent = '测试连接';
        }
    }

    async _save() {
        const url = document.getElementById('sUrl').value.trim();
        const key = document.getElementById('sKey').value.trim();
        const model = document.getElementById('sModel').value.trim();
        const visionModel = document.getElementById('sVisionModel').value.trim();
        const temp = parseFloat(document.getElementById('sTemp').value) || 0.8;

        if (!url || !model) {
            this.app.toast('请填写 API 地址和模型名称');
            return;
        }
        // If key unchanged from the masked original, don't send it — backend keeps the original
        const keyUnchanged = key === this._originalKey;
        if (!keyUnchanged && !key) {
            this.app.toast('请填写 API Key');
            return;
        }

        try {
            await API.createConfig({
                name: 'default',
                base_url: url,
                api_key: keyUnchanged ? undefined : key,
                model: model,
                vision_model: visionModel,
                temperature: temp,
                max_tokens: 2048
            });

            await API.updateProactiveConfig({
                enabled: this.$tglPro.classList.contains('on'),
                max_daily_messages: parseInt(document.getElementById('sMaxDaily').value) || 5,
                absence_hours: parseInt(document.getElementById('sAbsence').value) || 4
            });

            // Search config
            const searchKey = document.getElementById('sSearchKey').value.trim();
            const searchKeyUnchanged = searchKey === this._originalSearchKey;
            await API.updateSearchConfig({
                enabled: this.$tglSearch.classList.contains('on'),
                ...(searchKeyUnchanged ? {} : { tavily_api_key: searchKey })
            });

            // Weather city
            const city = document.getElementById('sCity').value.trim();
            await API.updateWeatherConfig(city);

            // TTS config
            await API.updateTTSConfig({
                enabled: document.getElementById('tglVoice').classList.contains('on'),
                voice: document.getElementById('sVoice').value
            });

            this.close();
            this.app.toast('设置已保存', 'ok');
            this.app.updateStatus();
        } catch (e) {
            this.app.toast('保存失败: ' + e.message);
        }
    }
}
