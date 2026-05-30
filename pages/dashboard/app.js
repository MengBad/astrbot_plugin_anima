const bridge = window.AstrBotPluginPage;

const AUTO_INTERVAL_MS = 15000;
let autoTimer = null;
let autoOn = true;

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
    barList(s.llm_calls, '今日暂无内部 LLM 调用');

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
      ? '<p class="hint">拦截分项：</p>' + barList(s.stance.blocked, '')
      : '';

  document.getElementById('store-cards').innerHTML =
    card(s.store.in, '用户消息 (in)') +
    card(s.store.out, 'bot 回复 (out)');
}

async function loadDashboard() {
  const btn = document.getElementById('refresh-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await bridge.apiGet('runtime_stats');
    if (res && res.disabled) {
      // dashboard_enabled=false：禁用提示，停止轮询
      autoOn = false;
      stopAuto();
      document.getElementById('auto-btn').textContent = '自动刷新：关';
      showNotice(
        `<h3>运行仪表盘已禁用</h3>
         <p>当前配置 <code>dashboard_enabled = false</code>，统计数据接口与埋点均已停用。</p>
         <p>在 AstrBot WebUI 的 Anima 插件配置里开启 <code>dashboard_enabled</code> 后刷新本页即可恢复。</p>`,
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

// 暴露给 onclick
window.loadDashboard = loadDashboard;
window.toggleAuto = toggleAuto;

init().catch((e) => showNotice(`<h3>初始化失败</h3><p>${e}</p>`, 'error'));
