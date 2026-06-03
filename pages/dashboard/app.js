const bridge = window.AstrBotPluginPage;

const AUTO_INTERVAL_MS = 15000;
let autoTimer = null;
let autoOn = true;

/** 统计 metric 中文标签（与 anima/ui_labels.py 保持一致） */
const METRIC_LABELS = {
  llm: {
    emotion: '情绪评分',
    monologue: '内心独白生成',
    sediment_merged: '沉淀合并调用',
    relation: '关系图谱推断',
    worldview: '世界观更新',
    stance: '主动发言生成',
    info_collection: '主动信息收集',
    mutation: '核心人格突变',
    memory_infection: '记忆感染',
    research_synthesis: '自主研究合成',
    rumination: '离线反刍',
    contradiction: '矛盾检测',
  },
  blocked: {
    monologue: '内心独白泄漏拦截',
    irrelevant: '话题不相关拦截',
    dedup: '重复发言拦截',
    low_intensity: '强度不足拦截',
    stale: '欲望过期拦截',
    sensitive: '敏感内容拦截',
    rejected: '拒答内容拦截',
  },
};

function labelMetric(name, kind) {
  const table = kind === 'blocked' ? METRIC_LABELS.blocked : METRIC_LABELS.llm;
  return table[name] || name;
}

function relabelCounts(obj, kind) {
  const out = {};
  for (const [name, v] of Object.entries(obj || {})) {
    out[labelMetric(name, kind)] = v;
  }
  return out;
}

function card(value, label, cls) {
  return `<div class="stat-card ${cls || ''}">
    <div class="stat-value">${value}</div>
    <div class="stat-label">${label}</div>
  </div>`;
}

function barList(obj, emptyText) {
  const entries = Object.entries(obj || {});
  if (entries.length === 0) {
    return `<p class="no-data">${emptyText}</p>`;
  }
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return entries
    .map(([name, v]) => {
      const pct = Math.round((v / max) * 100);
      return `<div class="bar-row">
        <span class="bar-label" title="${name}">${name}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
        <span class="bar-value">${v}</span>
      </div>`;
    })
    .join('');
}

function llmTotalFromCounts(counts) {
  if (!counts || typeof counts !== 'object') return 0;
  return Object.entries(counts).reduce(
    (sum, [k, v]) => sum + (k.startsWith('llm.') ? Number(v) || 0 : 0),
    0
  );
}

function renderHistoryChart(history, todayDate, todayTotal) {
  const container = document.getElementById('history-chart');
  const hint = document.getElementById('history-hint');
  if (!container) return;

  const rows = [];
  for (const entry of history || []) {
    const day = entry.date;
    const total = llmTotalFromCounts(entry.counts);
    if (day) rows.push({ day, total, isToday: false });
  }
  if (todayDate) {
    rows.push({ day: todayDate, total: todayTotal || 0, isToday: true });
  }

  // 近 7 天（含今日）
  const recent = rows.slice(-7);
  if (recent.length === 0) {
    container.innerHTML = '<p class="no-data">暂无历史数据。跨天后会自动开始归档，届时此处显示近 7 天 LLM 调用趋势。</p>';
    if (hint) hint.textContent = '';
    return;
  }

  const max = Math.max(...recent.map((r) => r.total), 1);
  container.innerHTML = recent
    .map((r) => {
      const pct = Math.round((r.total / max) * 100);
      const tag = r.isToday ? '（今日）' : '';
      return `<div class="history-row">
        <span class="history-date">${r.day}${tag}</span>
        <span class="history-track"><span class="history-fill" style="width:${pct}%"></span></span>
        <span class="history-value">${r.total}</span>
      </div>`;
    })
    .join('');
  if (hint) {
    hint.textContent = '柱状高度 = 当天内部 LLM 调用总次数（与 /anima_stats 趋势一致）';
  }
}

function showNotice(html, kind) {
  const body = document.getElementById('dashboard-body');
  const notice = document.getElementById('notice');
  body.style.display = 'none';
  notice.style.display = 'block';
  notice.className = 'notice notice-' + (kind || 'info');
  notice.innerHTML = html;
}

function hideNotice() {
  document.getElementById('notice').style.display = 'none';
  document.getElementById('dashboard-body').style.display = 'block';
}

function stopAuto() {
  if (autoTimer) {
    clearInterval(autoTimer);
    autoTimer = null;
  }
}

function startAuto() {
  stopAuto();
  if (autoOn) {
    autoTimer = setInterval(loadDashboard, AUTO_INTERVAL_MS);
  }
}

function toggleAuto() {
  autoOn = !autoOn;
  document.getElementById('auto-btn').textContent = '自动刷新：' + (autoOn ? '开' : '关');
  startAuto();
}

function render(s) {
  hideNotice();
  const meta = document.getElementById('meta-bar');
  const ts = new Date().toLocaleTimeString();
  meta.innerHTML = `统计日期 <strong>${s.date}</strong> · 最后刷新 ${ts}`;

  document.getElementById('llm-summary').innerHTML =
    `<span class="num">${s.llm_total}</span> <span class="num-label">今日内部 LLM 调用总次数</span>`;
  document.getElementById('llm-breakdown').innerHTML =
    barList(relabelCounts(s.llm_calls, 'llm'), '今日暂无内部 LLM 调用');

  document.getElementById('sediment-cards').innerHTML =
    card(s.sediment.run, '触发沉淀') +
    card(s.sediment.skip_low, '情绪未达阈值跳过');

  document.getElementById('desire-cards').innerHTML =
    card(s.desire.outward, 'outward 可外发') +
    card(s.desire.inward, 'inward 只内省');

  document.getElementById('stance-cards').innerHTML =
    card(s.stance.sent, '实际发出', 'ok') +
    card(s.stance.blocked_total, '被防线拦截', 'warn');
  document.getElementById('stance-blocked').innerHTML =
    Object.keys(s.stance.blocked || {}).length
      ? '<p class="hint">拦截分项：</p>' + barList(relabelCounts(s.stance.blocked, 'blocked'), '')
      : '';

  document.getElementById('store-cards').innerHTML =
    card(s.store.in, '用户消息 (in)') +
    card(s.store.out, 'bot 回复 (out)');

  renderHistoryChart(s.history, s.date, s.llm_total);
}

async function loadDashboard() {
  const btn = document.getElementById('refresh-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await bridge.apiGet('runtime_stats');
    if (res && res.disabled) {
      autoOn = false;
      stopAuto();
      document.getElementById('auto-btn').textContent = '自动刷新：关';
      showNotice(
        `<h3>运行仪表盘已禁用</h3>
         <p>当前已在插件配置中关闭「运行仪表盘」，统计数据接口与埋点均已停用。</p>
         <p>在 AstrBot WebUI → 插件 → Anima 中开启「运行仪表盘」后刷新本页即可恢复。</p>`,
        'disabled'
      );
      return;
    }
    if (!res || !res.success || !res.stats) {
      showNotice(
        `<h3>统计加载失败</h3><p>${(res && res.error) || '接口未返回有效数据'}</p>`,
        'error'
      );
      return;
    }
    render(res.stats);
  } catch (e) {
    showNotice(`<h3>无法连接数据接口</h3><p>${e}</p><p>请确认插件已正常加载。</p>`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function init() {
  await bridge.ready();
  await loadDashboard();
  startAuto();
}

window.loadDashboard = loadDashboard;
window.toggleAuto = toggleAuto;

init().catch((e) => showNotice(`<h3>初始化失败</h3><p>${e}</p>`, 'error'));
