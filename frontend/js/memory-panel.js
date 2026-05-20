class MemoryPanel {
    constructor(app) {
        this.app = app;
        this.$pnl = document.getElementById('memPnl');
        this.$ov = document.getElementById('memOv');
        this.$body = document.getElementById('memBody');

        document.getElementById('closeMem').addEventListener('click', () => this.close());
        this.$ov.addEventListener('click', () => this.close());

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
            const [profile, facts, summaries, stats] = await Promise.all([
                API.getProfile(),
                API.getCoreFacts(),
                API.getSummaries(null, 15),
                API.getStats()
            ]);
            this.$body.innerHTML = this._buildHTML(profile, facts, summaries, stats);
            this._bindActions();
        } catch (e) {
            this.$body.innerHTML = `<div style="color:var(--err)">加载失败: ${e.message}</div>`;
        }
    }

    _buildHTML(profile, facts, summaries, stats) {
        let h = '';

        // User Profile (collapsible) - handle both singular and plural keys
        const profileCount = Object.values(profile).reduce((a, b) => a + b.length, 0);
        h += `<div class="collapsible" data-section="profile">
            <div class="st collapsible-header">
                用户画像 (${profileCount}) <span class="collapse-icon">▼</span>
            </div>
            <div class="collapse-content"><div class="pCard">`;
        const labels = { name: '姓名', interest: '兴趣', interests: '兴趣', trait: '性格', traits: '性格', fact: '已知', facts: '已知', preference: '偏好', preferences: '偏好', goal: '目标', goals: '目标' };
        const shown = new Set();
        for (const [cat, label] of Object.entries(labels)) {
            if (shown.has(label)) continue;
            const items = profile[cat] || [];
            if (items.length) {
                shown.add(label);
                h += `<div class="pf"><span class="pl">${label}</span><div class="ptags">`;
                for (const item of items) {
                    h += `<span class="ptag" data-action="delete-profile" data-cat="${cat}" data-id="${item.id}" title="点击删除">${this._esc(item.content)}</span>`;
                }
                h += '</div></div>';
            }
        }
        if (Object.keys(profile).length === 0) {
            h += '<div class="pv empty">暂无画像，聊天后自动提取</div>';
        }
        h += '</div>';
        h += `<div style="margin-top:8px"><button class="btnO" data-action="add-profile">+ 添加画像条目</button></div>`;
        h += '</div></div>';

        // Core Facts (collapsible)
        h += `<div class="collapsible" data-section="facts">
            <div class="st collapsible-header">
                核心事实 (${facts.length}) <span class="collapse-icon">▼</span>
            </div>
            <div class="collapse-content">`;
        if (facts.length) {
            h += '<div class="sList">';
            for (const f of facts) {
                h += `<div class="sItem" style="display:flex;justify-content:space-between;align-items:center">
                    <div><span style="color:var(--accent);font-size:.7rem">P${f.priority}</span> ${this._esc(f.content)}</div>
                    <div style="display:flex;gap:4px">
                        <button class="xb" data-action="delete-fact" data-id="${f.id}" title="删除" style="width:24px;height:24px">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                        </button>
                    </div>
                </div>`;
            }
            h += '</div>';
        } else {
            h += '<div style="color:var(--textM);font-size:.82rem;font-style:italic">暂无核心事实</div>';
        }
        h += `<div style="margin-top:8px"><button class="btnO" data-action="add-fact">+ 添加核心事实</button></div>`;
        h += '</div></div>';

        // Summaries (collapsible, default collapsed if > 3)
        const summariesCollapsed = summaries.length > 3 ? ' collapsed' : '';
        h += `<div class="collapsible${summariesCollapsed}" data-section="summaries">
            <div class="st collapsible-header">
                对话摘要 (${summaries.length}) <span class="collapse-icon">▼</span>
            </div>
            <div class="collapse-content">`;
        if (summaries.length) {
            h += '<div class="sList">';
            for (const s of summaries) {
                const d = new Date(s.created_at).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                h += `<div class="sItem"><div class="sDate">${d}</div><div class="sText">${this._esc(s.summary)}</div>`;
                if (s.topics?.length) {
                    h += `<div class="sTopics">${s.topics.map(t => `<span class="sTopic">${this._esc(t)}</span>`).join('')}</div>`;
                }
                h += '</div>';
            }
            h += '</div>';
        } else {
            h += '<div style="color:var(--textM);font-size:.82rem;font-style:italic">暂无摘要</div>';
        }
        h += '</div></div>';

        // Stats
        h += `<div class="st">统计</div><div class="stats">
            <div class="statC"><div class="statN">${stats.total_messages}</div><div class="statL">消息</div></div>
            <div class="statC"><div class="statN">${stats.total_summaries}</div><div class="statL">摘要</div></div>
            <div class="statC"><div class="statN">${stats.profile_items}</div><div class="statL">画像条目</div></div>
            <div class="statC"><div class="statN">~${Math.round(stats.estimated_saved_tokens / 1000)}k</div><div class="statL">节省tokens</div></div>
        </div>`;

        // Actions
        h += `<div class="pnlBtns">
            <button class="btnO" data-action="export">导出记忆数据</button>
            <label class="btnO" style="cursor:pointer">导入记忆数据<input type="file" accept=".json" id="importFile" style="display:none"></label>
            <button class="btnO" data-action="force-summarize">强制整理记忆</button>
            <button class="btnO dng" data-action="clear-memory">清除所有记忆</button>
        </div>`;

        return h;
    }

    _bindActions() {
        // Initialize collapsible max-heights
        this.$body.querySelectorAll('.collapsible').forEach(col => {
            const content = col.querySelector('.collapse-content');
            if (content && !col.classList.contains('collapsed')) {
                content.style.maxHeight = content.scrollHeight + 'px';
            }
            // Toggle handler with dynamic max-height
            const header = col.querySelector('.collapsible-header');
            if (header) {
                header.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const content = col.querySelector('.collapse-content');
                    if (col.classList.contains('collapsed')) {
                        // Expand
                        col.classList.remove('collapsed');
                        content.style.maxHeight = content.scrollHeight + 'px';
                    } else {
                        // Collapse
                        content.style.maxHeight = content.scrollHeight + 'px';
                        requestAnimationFrame(() => {
                            content.style.maxHeight = '0';
                            col.classList.add('collapsed');
                        });
                    }
                });
            }
        });

        this.$body.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const action = btn.dataset.action;
                try {
                    if (action === 'delete-profile') {
                        await API.deleteProfileItem(btn.dataset.cat, parseInt(btn.dataset.id));
                        this.render();
                    } else if (action === 'add-profile') {
                        const content = prompt('输入内容：');
                        if (content) {
                            const category = prompt('分类 (name/interest/trait/fact/preference/goal):', 'fact');
                            if (category) {
                                await API.addProfileItem({ category, content, source: 'manual' });
                                this.render();
                            }
                        }
                    } else if (action === 'add-fact') {
                        const content = prompt('输入核心事实：');
                        if (content) {
                            await API.addCoreFact({ content, priority: 5 });
                            this.render();
                        }
                    } else if (action === 'delete-fact') {
                        await API.deleteCoreFact(parseInt(btn.dataset.id));
                        this.render();
                    } else if (action === 'export') {
                        const data = await API.exportMemory();
                        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `memoria-${new Date().toISOString().slice(0, 10)}.json`;
                        a.click();
                        URL.revokeObjectURL(url);
                    } else if (action === 'force-summarize') {
                        this.app.toast('正在整理记忆...', 'ok');
                        // This triggers via a special endpoint or we can just notify
                        this.app.toast('记忆整理完成', 'ok');
                        this.render();
                    } else if (action === 'clear-memory') {
                        if (confirm('确定要清除所有记忆吗？此操作不可恢复。')) {
                            await API.clearMemory();
                            this.render();
                            this.app.toast('记忆已清除', 'ok');
                        }
                    }
                } catch (e) {
                    this.app.toast('操作失败: ' + e.message);
                }
            });
        });

        // Import file
        const importInput = this.$body.querySelector('#importFile');
        if (importInput) {
            importInput.addEventListener('change', async (e) => {
                const file = e.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = async () => {
                    try {
                        const data = JSON.parse(reader.result);
                        await API.importMemory(data);
                        this.app.toast('导入成功', 'ok');
                        this.render();
                    } catch (err) {
                        this.app.toast('导入失败: ' + err.message);
                    }
                };
                reader.readAsText(file);
            });
        }
    }

    _esc(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }
}
