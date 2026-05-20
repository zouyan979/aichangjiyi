class PersonaPanel {
    constructor(app) {
        this.app = app;
        this.$pnl = document.getElementById('perPnl');
        this.$ov = document.getElementById('perOv');
        this.$body = document.getElementById('perBody');
        this.personaData = null;

        document.getElementById('closePer').addEventListener('click', () => this.close());
        this.$ov.addEventListener('click', () => this.close());

        // Load persona data on init for code filtering
        this._loadPersonaData();
    }

    async _loadPersonaData() {
        try {
            this.personaData = await API.getPersona();
        } catch (e) {
            console.warn('[PersonaPanel] Failed to load persona data:', e);
        }
    }

    open() {
        this.$pnl.classList.add('show');
        this.$ov.classList.add('show');
        this.render();
    }

    close() {
        this.$pnl.classList.remove('show');
        this.$ov.classList.remove('show');
    }

    async render() {
        try {
            const [persona, growthLog] = await Promise.all([
                API.getPersona(),
                API.getGrowthLog()
            ]);
            this.personaData = persona;
            this.$body.innerHTML = this._buildHTML(persona, growthLog);
            this._bindActions();
        } catch (e) {
            this.$body.innerHTML = `<div style="color:var(--err)">加载失败: ${e.message}</div>`;
        }
    }

    _buildHTML(persona, growthLog) {
        let h = '';

        // Persona editor
        h += '<div class="st">AI人设</div>';
        h += `<div class="pCard">
            <div class="pf"><span class="pl">名称</span>
                <input class="fi" id="pName" value="${this._esc(persona.name || '')}"></div>
            <div class="pf"><span class="pl">核心性格</span>
                <textarea class="fi" id="pBase" rows="3">${this._esc(persona.base_persona || '')}</textarea></div>
            <div class="pf"><span class="pl">说话风格</span>
                <textarea class="fi" id="pStyle" rows="2">${this._esc(persona.speaking_style || '')}</textarea></div>
            <div class="pf"><span class="pl">背景故事</span>
                <textarea class="fi" id="pBg" rows="2">${this._esc(persona.background || '')}</textarea></div>
            <div class="pf"><span class="pl">当前关系</span>
                <textarea class="fi" id="pRel" rows="2">${this._esc(persona.relationship || '')}</textarea></div>
            <div class="pf"><span class="pl">情绪状态</span>
                <input class="fi" id="pEmo" value="${this._esc(persona.emotion_state || 'calm')}"></div>
            <div class="pf"><span class="pl">自定义规则 <span style="color:var(--accent);font-size:.65rem">（不会被成长系统覆盖）</span></span>
                <textarea class="fi" id="pRules" rows="2" placeholder="例如：不可以输出代码、不可以使用英文">${this._esc(persona.custom_rules || '')}</textarea></div>
            <div class="mA">
                <button class="btnP" data-action="save-persona">保存人设</button>
                <button class="btnS" data-action="reset-persona">重置默认</button>
            </div>
        </div>`;

        // Growth log
        h += `<div class="st">成长记录 (${growthLog.length})</div>`;
        if (growthLog.length) {
            h += '<div class="gList">';
            for (const g of [...growthLog].reverse().slice(0, 20)) {
                h += `<div class="gItem"><div class="gDate">${this._esc(g.date)}</div><div class="gText">${this._esc(g.event)}</div></div>`;
            }
            h += '</div>';
        } else {
            h += '<div style="color:var(--textM);font-size:.82rem;font-style:italic">暂无成长记录，多聊天后自动生成</div>';
        }

        return h;
    }

    _bindActions() {
        this.$body.querySelector('[data-action="save-persona"]')?.addEventListener('click', async () => {
            try {
                const updated = {
                    name: document.getElementById('pName').value,
                    base_persona: document.getElementById('pBase').value,
                    speaking_style: document.getElementById('pStyle').value,
                    background: document.getElementById('pBg').value,
                    relationship: document.getElementById('pRel').value,
                    emotion_state: document.getElementById('pEmo').value,
                    custom_rules: document.getElementById('pRules').value
                };
                await API.updatePersona(updated);
                this.personaData = { ...this.personaData, ...updated };
                this.app.toast('人设已保存', 'ok');
            } catch (e) {
                this.app.toast('保存失败: ' + e.message);
            }
        });

        this.$body.querySelector('[data-action="reset-persona"]')?.addEventListener('click', async () => {
            if (confirm('确定重置为默认人设吗？')) {
                try {
                    await API.resetPersona();
                    this.render();
                    this.app.toast('已重置为默认人设', 'ok');
                } catch (e) {
                    this.app.toast('重置失败: ' + e.message);
                }
            }
        });
    }

    _esc(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }
}
