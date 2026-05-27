const bridge = window.AstrBotPluginPage;

let allCapabilities = [];
let allEvents = [];

async function init() {
  const context = await bridge.ready();
  console.log('[Anima WebUI] Context ready:', context);
  await refreshAll();
}

async function refreshAll() {
  await Promise.all([
    loadStats(),
    loadCapabilities(),
    loadEvents()
  ]);
}

async function loadStats() {
  const container = document.getElementById('stats-bar');
  try {
    const res = await bridge.apiGet('stats');
    if (res.success && res.stats) {
      const s = res.stats;
      container.innerHTML = `
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-value">${s.total_capabilities}</div>
            <div class="stat-label">总能力数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${(s.average_confidence * 100).toFixed(1)}%</div>
            <div class="stat-label">平均置信度</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${s.total_usage}</div>
            <div class="stat-label">总使用次数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${s.total_corrections}</div>
            <div class="stat-label">总修正次数</div>
          </div>
        </div>
      `;
    }
  } catch (e) {
    container.textContent = '统计加载失败';
  }
}

async function loadCapabilities() {
  const container = document.getElementById('capabilities-list');
  container.innerHTML = '<div class="no-data">加载中...</div>';

  try {
    const res = await bridge.apiGet('capabilities');
    allCapabilities = res.data?.capabilities || [];

    renderCapabilities(allCapabilities);
  } catch (e) {
    container.innerHTML = '<p style="color:#dc2626">加载失败</p>';
  }
}

function renderCapabilities(caps) {
  const container = document.getElementById('capabilities-list');
  
  if (caps.length === 0) {
    container.innerHTML = '<p class="no-data">当前还没有创造出任何个人能力。</p>';
    return;
  }

  container.innerHTML = caps.map(cap => {
    const conf = ((cap.confidence || 0) * 100).toFixed(0);
    const confClass = conf >= 75 ? 'confidence-high' : conf >= 45 ? 'confidence-medium' : 'confidence-low';
    
    let extraHtml = '';
    
    if (cap.parameters_schema) {
      extraHtml += `<div class="cap-extra"><strong>参数结构</strong><br><code style="font-size:12px">${JSON.stringify(cap.parameters_schema, null, 2).substring(0, 120)}...</code></div>`;
    }
    
    if (cap.executable_snippet) {
      extraHtml += `
        <div class="cap-extra">
          <strong>可执行代码片段</strong> 
          <span class="badge">已定义</span><br>
          <pre style="font-size:12px; margin:4px 0; white-space:pre-wrap;">${cap.executable_snippet.substring(0, 180)}${cap.executable_snippet.length > 180 ? '...' : ''}</pre>
        </div>`;
    }

    const isIndependent = cap.register_as_independent_tool ? 
      `<span class="badge" style="background:#d1fae5;color:#065f46">已注册独立工具</span>` : '';

    const correctionsHtml = (cap.corrections && cap.corrections.length > 0) ? 
      `<details style="margin-top:8px;font-size:13px">
         <summary>查看 ${cap.corrections.length} 次修正记录</summary>
         <ul style="margin:6px 0 0 16px;padding:0;font-size:12px">
           ${cap.corrections.slice(-3).map(c => `<li>${c.ts?.substring(0,10)}: ${c.what_was_wrong || '未知修正'}</li>`).join('')}
         </ul>
       </details>` : '';

    return `
      <div class="cap-card">
        <div class="cap-header">
          <h3 class="cap-name">${cap.name || '未命名能力'}</h3>
          <span class="confidence-badge ${confClass}">${conf}%</span>
        </div>
        
        <div class="cap-meta">
          <span>使用 ${cap.usage_count || 0} 次</span>
          <span>修正 ${(cap.corrections || []).length} 次</span>
          ${cap.last_updated ? `<span>最后更新: ${cap.last_updated.substring(0,10)}</span>` : ''}
          ${isIndependent}
        </div>

        <div class="cap-desc">${cap.description || '暂无描述'}</div>

        ${cap.how_to_use ? `<div class="cap-extra"><strong>使用方法</strong><br>${cap.how_to_use}</div>` : ''}
        
        ${extraHtml}
        ${correctionsHtml}
      </div>
    `;
  }).join('');
}

function filterCapabilities() {
  const search = (document.getElementById('search-input')?.value || '').toLowerCase();
  const minConf = parseInt(document.getElementById('min-conf')?.value || '0');

  const filtered = allCapabilities.filter(cap => {
    const nameMatch = (cap.name || '').toLowerCase().includes(search);
    const descMatch = (cap.description || '').toLowerCase().includes(search);
    const confMatch = (cap.confidence || 0) * 100 >= minConf;
    return (nameMatch || descMatch) && confMatch;
  });

  const container = document.getElementById('capabilities-list');
  const sorted = filtered.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
  container.innerHTML = sorted.length > 0 
    ? sorted.map(createCapabilityCard).join('') 
    : '<p class="no-data">没有匹配的能力</p>';
}

async function loadEvents() {
  const container = document.getElementById('events-list');
  container.innerHTML = '<div class="no-data">加载中...</div>';

  try {
    const res = await bridge.apiGet('events', { limit: 20 });
    const events = res.events || [];

    if (events.length === 0) {
      container.innerHTML = '<p class="no-data">暂无自主演化事件。</p>';
      return;
    }

    // Special rendering for real autonomous internal research events (the ones from the user's log)
    container.innerHTML = events.map(ev => {
      const ts = (ev.timestamp || '').substring(0, 19).replace('T', ' ');
      const trigger = ev.trigger || '';
      const isAutonomousResearch = trigger === 'self_directed_research' || trigger === 'autonomous_capability_creation';
      
      let contentHtml = `<div style="margin-top:4px;color:#444;font-size:13px">${(ev.new_content || '').substring(0, 160)}</div>`;
      
      if (isAutonomousResearch && ev.old_summary) {
        // Highlight the exact reason the user saw in the log: "长时间未见 XXX"
        contentHtml = `
          <div class="autonomous-reason">
            <span class="reason-label">内部驱动力</span>
            <span class="reason-text">${ev.old_summary}</span>
          </div>
          <div class="autonomous-result">${(ev.new_content || '').substring(0, 140)}</div>
        `;
      }
      
      const extraClass = isAutonomousResearch ? 'event-item-autonomous' : '';
      const icon = isAutonomousResearch ? '🧠 ' : '';
      
      return `
        <div class="event-item ${extraClass}">
          <div><span class="event-ts">${ts}</span> ${icon}<strong>${trigger}</strong></div>
          ${contentHtml}
        </div>
      `;
    }).join('');
  } catch (e) {
    container.innerHTML = '<p style="color:#dc2626">加载事件失败</p>';
  }
}

async function exportData() {
  try {
    const res = await bridge.apiGet('export');
    const blob = new Blob([JSON.stringify(res, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `anima_capability_tree_${new Date().toISOString().slice(0,10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) {
    alert('导出失败');
  }
}

// Tab switching
function switchTab(tabName) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  
  document.getElementById(`tab-${tabName}`).classList.add('active');
  document.querySelector(`.tab[onclick*="${tabName}"]`).classList.add('active');
}

// Initial load
init().catch(console.error);