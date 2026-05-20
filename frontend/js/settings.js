class SettingsModal {
    constructor(app) {
        this.app = app;
        this.$modal = document.getElementById('setModal');
        this.$tRes = document.getElementById('tRes');
        this.$tglPro = document.getElementById('tglPro');
        this._bind();
    }

    _bind() {
        document.getElementById('setBg').addEventListener('click', () => this.close());
        document.getElementById('closeSet').addEventListener('click', () => this.close());
        this.$tglPro.addEventListener('click', () => this.$tglPro.classList.toggle('on'));
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
            const [configs, proConfig] = await Promise.all([
                API.listConfigs(),
                API.getProactiveConfig()
            ]);

            // Clear fields first
            document.getElementById('sUrl').value = '';
            document.getElementById('sKey').value = '';
            document.getElementById('sModel').value = '';
            document.getElementById('sTemp').value = '0.8';

            // Fill if active config exists
            const active = configs.find(c => c.is_active);
            if (active) {
                document.getElementById('sUrl').value = active.base_url || '';
                document.getElementById('sKey').value = active.api_key || '';
                document.getElementById('sModel').value = active.model || '';
                document.getElementById('sTemp').value = active.temperature || 0.8;
            }

            this.$tglPro.classList.toggle('on', !!proConfig.enabled);
            document.getElementById('sInt').value = proConfig.interval_minutes || 30;
            document.getElementById('sAbsence').value = proConfig.absence_hours || 4;
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
        const temp = parseFloat(document.getElementById('sTemp').value) || 0.8;

        if (!url || !key || !model) {
            this.app.toast('请填写 API 地址、Key 和模型名称');
            return;
        }

        try {
            await API.createConfig({
                name: 'default',
                base_url: url,
                api_key: key,
                model: model,
                temperature: temp,
                max_tokens: 2048
            });

            await API.updateProactiveConfig({
                enabled: this.$tglPro.classList.contains('on'),
                interval_minutes: parseInt(document.getElementById('sInt').value) || 30,
                absence_hours: parseInt(document.getElementById('sAbsence').value) || 4
            });

            this.close();
            this.app.toast('设置已保存', 'ok');
            this.app.updateStatus();
        } catch (e) {
            this.app.toast('保存失败: ' + e.message);
        }
    }
}
