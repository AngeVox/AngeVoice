let lastData = null;
let lastConfigPayload = null;
let activeGroup = 'quality';
let activeAdminTab = 'overview';
const adminSubtabs = {
  config: [
    { key: 'config.runtime', label: '运行配置' },
    { key: 'config.quality', label: '音频质量' },
  ],
  security: [
    { key: 'security.auth', label: '鉴权与访问' },
    { key: 'security.deploy', label: '部署预设' },
  ],
  api: [
    { key: 'api.diagnostics', label: '诊断与导出' },
    { key: 'api.raw', label: '原始状态' },
  ],
};
const activeSubtab = { config: 'config.runtime', security: 'security.auth', api: 'api.diagnostics' };

const $ = id => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function toast(message, isError = false) {
  const el = $('admin-toast');
  el.textContent = message;
  el.classList.toggle('error', Boolean(isError));
  el.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove('show'), 2400);
}

function renderAdminTab() {
  document.querySelectorAll('[data-admin-panel]').forEach(panel => {
    panel.classList.toggle('hidden-panel', panel.dataset.adminPanel !== activeAdminTab);
  });
  document.querySelectorAll('[data-admin-tab]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.adminTab === activeAdminTab);
  });
  renderAdminSubnav();
}

function renderAdminSubnav() {
  const holder = $('admin-subnav');
  const tabs = adminSubtabs[activeAdminTab] || [];
  if (!tabs.length) {
    holder.innerHTML = '';
    holder.classList.remove('show');
    document.querySelectorAll('[data-admin-subpanel]').forEach(el => el.classList.remove('hidden-panel'));
    return;
  }
  holder.classList.add('show');
  holder.innerHTML = tabs.map(tab => `<button class="admin-subnav-btn ${activeSubtab[activeAdminTab] === tab.key ? 'active' : ''}" data-admin-subtab="${escapeHtml(tab.key)}" type="button">${escapeHtml(tab.label)}</button>`).join('');
  document.querySelectorAll('[data-admin-subpanel]').forEach(el => {
    const key = el.dataset.adminSubpanel;
    if (!key.startsWith(`${activeAdminTab}.`)) return;
    el.classList.toggle('hidden-panel', key !== activeSubtab[activeAdminTab]);
  });
}

function metricCard(title, value, tone = '') {
  return `<article class="metric-card admin-metric ${tone}"><span>${escapeHtml(title)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></article>`;
}

function formatBytes(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = n;
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) { size /= 1024; idx += 1; }
  return `${size.toFixed(idx ? 1 : 0)} ${units[idx]}`;
}

function shortNumber(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n)) return '-';
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(Math.round(n * 100) / 100);
}

function renderHealth(models) {
  const pill = $('admin-health-pill');
  const unhealthy = (models || []).filter(item => item.loaded && item.healthy === false);
  pill.classList.toggle('ok', unhealthy.length === 0);
  pill.classList.toggle('error', unhealthy.length > 0);
  pill.querySelector('b').textContent = unhealthy.length ? `${unhealthy.length} 个异常` : '运行正常';
}

function renderMetrics(data) {
  const models = data.models || [];
  const stats = data.stats || {};
  const loaded = models.filter(m => m.loaded).length;
  const busy = models.reduce((sum, m) => sum + Number(m.active_count || 0), 0);
  const currentModel = models.find(m => m.current) || {};
  const quality = currentModel.last_output_quality || {};
  const ok = Number(stats.requests_ok || 0);
  const avg = ok ? Number(stats.synthesis_seconds_total || 0) / ok : 0;
  $('admin-metrics').innerHTML = [
    metricCard('当前模型', data.current_model || '-'),
    metricCard('已加载', loaded),
    metricCard('活跃请求', busy, busy ? 'warn' : ''),
    metricCard('缓存', `${data.cache_items ?? 0} / ${formatBytes(data.cache_bytes || 0)}`),
    metricCard('成功/失败', `${stats.requests_ok || 0}/${stats.requests_error || 0}`),
    metricCard('平均耗时', avg ? `${avg.toFixed(2)}s` : '-'),
    metricCard('最大静音', quality.max_silence_ms != null ? `${quality.max_silence_ms}ms` : '-'),
    metricCard('削波比例', quality.clip_ratio ?? '-')
  ].join('');
  renderHealth(models);
}

function modelCard(m) {
  const state = m.loaded ? (m.healthy === false ? '异常' : '已加载') : (m.idle_unloaded ? '休眠' : '未加载');
  const active = Number(m.active_count || 0);
  const provider = m.actual_provider || m.device || m.provider || '-';
  const isolation = m.process_isolated ? `隔离 ${m.process_alive ? '在线' : '未启动'}` : '线程内';
  const quality = m.last_output_quality || {};
  const id = escapeHtml(m.id);
  return `<article class="model-card ${m.current ? 'current' : ''}">
    <div class="model-card-main">
      <div>
        <h3>${escapeHtml(m.name || m.id)} ${m.current ? '<b class="badge">当前</b>' : ''}</h3>
        <p>${id} · ${escapeHtml(provider)} · ${escapeHtml(isolation)}</p>
      </div>
      <span class="model-state ${m.healthy === false ? 'bad' : ''}">${escapeHtml(state)}${active ? ` · busy=${active}` : ''}</span>
    </div>
    <div class="model-facts">
      <span>缓存 ${m.loaded ? '已占用' : '空'}</span>
      <span>模式 ${(m.modes || []).join(', ') || '-'}</span>
      <span>长静音 ${quality.long_silence_count ?? '-'}</span>
      <span>超时 ${m.consecutive_timeouts ?? 0}</span>
      <span>${m.pending_rebuild ? '待重建' : (m.low_vram_mode ? '低显存' : '显存正常')}</span>
    </div>
    <div class="button-row compact">
      <button class="ghost-button small" data-load="${id}" type="button">加载</button>
      <button class="ghost-button small" data-switch="${id}" type="button">切换</button>
      <button class="ghost-button small" data-unload="${id}" type="button">释放</button>
      <button class="danger-button small" data-force-unload="${id}" type="button">强制</button>
    </div>
  </article>`;
}

function renderModels(data) {
  $('models-body').innerHTML = (data.models || []).map(modelCard).join('') || '<p class="empty-state">没有可用模型</p>';
}

function fieldBadge(field) {
  if (field.restart) return '<b class="badge">重启</b>';
  if (field.rebuild_moss) return '<b class="badge">重建</b>';
  return '<b class="badge">即时</b>';
}

function fieldInput(field, value) {
  const key = escapeHtml(field.key);
  if (field.type === 'bool') {
    return `<label class="config-toggle">
      <input data-config-field="${key}" type="checkbox" ${value ? 'checked' : ''}>
      <span>${escapeHtml(field.label)} ${fieldBadge(field)}</span>
    </label>`;
  }
  if (field.type === 'choice') {
    const options = (field.choices || [])
      .map(choice => `<option value="${escapeHtml(choice.value)}" ${String(value) === String(choice.value) ? 'selected' : ''}>${escapeHtml(choice.label)}</option>`)
      .join('');
    return `<label class="config-field">
      <span>${escapeHtml(field.label)} ${fieldBadge(field)}</span>
      <select data-config-field="${key}">${options}</select>
      ${field.help ? `<small>${escapeHtml(field.help)}</small>` : ''}
    </label>`;
  }
  const type = field.type === 'int' || field.type === 'float' ? 'number' : 'text';
  const min = field.min != null ? ` min="${escapeHtml(field.min)}"` : '';
  const max = field.max != null ? ` max="${escapeHtml(field.max)}"` : '';
  const step = field.step != null ? ` step="${escapeHtml(field.step)}"` : '';
  return `<label class="config-field">
    <span>${escapeHtml(field.label)} ${fieldBadge(field)}</span>
    <input data-config-field="${key}" type="${type}" value="${escapeHtml(value)}"${min}${max}${step}>
    ${field.help ? `<small>${escapeHtml(field.help)}</small>` : ''}
  </label>`;
}

function renderConfigTabs(schema) {
  const tabs = (schema.groups || []).filter(group => group.key !== 'advanced');
  if (!tabs.some(group => group.key === activeGroup)) activeGroup = tabs[0]?.key || 'quality';
  $('config-tabs').innerHTML = tabs.map(group => (
    `<button class="${group.key === activeGroup ? 'active' : ''}" data-config-group="${escapeHtml(group.key)}" type="button">${escapeHtml(group.label)}</button>`
  )).join('');
}

function renderConfigForms(payload) {
  const schema = payload.schema || {};
  const values = payload.values || {};
  const runtime = payload.runtime_config || {};
  const note = $('runtime-config-note');
  if (note) {
    const count = Number(runtime.field_count || 0);
    note.innerHTML = runtime.exists
      ? `当前有 <b>${count}</b> 项 Admin 持久化配置覆盖 ENV：<code>${escapeHtml(runtime.path || '')}</code>`
      : `当前没有 Admin 持久化配置，主要使用 ENV / 默认值。`;
    note.classList.toggle('warn', runtime.exists && count > 0);
  }
  renderConfigTabs(schema);
  const fields = schema.fields || [];
  $('config-form').innerHTML = fields
    .filter(field => !field.advanced && field.group === activeGroup)
    .map(field => fieldInput(field, values[field.key] ?? field.default))
    .join('');
  $('advanced-config-form').innerHTML = fields
    .filter(field => field.advanced || field.group === 'advanced')
    .map(field => fieldInput(field, values[field.key] ?? field.default))
    .join('');
}

function renderProfiles(payload) {
  const profiles = payload.schema?.profiles || [];
  const tuningProfiles = profiles.filter(profile => !String(profile.key).startsWith('deploy_'));
  $('profile-grid').innerHTML = tuningProfiles.map(profile => `<button class="profile-card" data-profile="${escapeHtml(profile.key)}" type="button">
    <b>${escapeHtml(profile.label)}</b>
    <span>${escapeHtml(profile.description)}</span>
  </button>`).join('');
  const deployProfiles = profiles.filter(profile => String(profile.key).startsWith('deploy_'));
  $('deploy-profile-grid').innerHTML = deployProfiles.map(profile => `<button class="profile-card" data-profile="${escapeHtml(profile.key)}" type="button">
    <b>${escapeHtml(profile.label)}</b>
    <span>${escapeHtml(profile.description)}</span>
  </button>`).join('');
}

function renderSecurity(data) {
  const security = data.security || {};
  const config = data.config || {};
  const keyState = security.api_key_enabled ? '已启用' : '未启用';
  const source = security.api_key_auto_generated ? '自动生成' : '手动/环境变量';
  $('api-key-status').textContent = `API Key：${keyState} · ${source} · ${security.api_key_preview || '-'}`;
  $('security-summary').innerHTML = [
    ['后台允许 API Key', config.admin_allow_api_key ? '是' : '否'],
    ['公开模型列表', config.public_status_endpoints ? '是' : '否'],
    ['信任反代 IP', config.trust_proxy_headers ? '是' : '否'],
    ['下载源', config.model_source_effective || config.model_source || 'auto'],
    ['配置文件', config.runtime_config_file || '-'],
    ['持久化覆盖', config.runtime_config?.exists ? `${config.runtime_config.field_count || 0} 项` : '无']
  ].map(([k, v]) => `<div><span>${escapeHtml(k)}</span><b>${escapeHtml(v)}</b></div>`).join('');
}

function renderQuality(data) {
  const currentModel = (data.models || []).find(m => m.current) || {};
  const quality = currentModel.last_output_quality || {};
  const vram = currentModel.vram || {};
  const items = [
    ['显存剩余', vram.free_mb != null ? `${vram.free_mb}/${vram.total_mb || '-'} MB` : '-'],
    ['显存模式', currentModel.low_vram_mode ? '低显存保护' : (currentModel.full_decode_disabled ? '解码保护' : '正常')],
    ['长静音', quality.long_silence_count ?? '-'],
    ['最大静音', quality.max_silence_ms != null ? `${quality.max_silence_ms}ms` : '-'],
    ['静音占比', quality.silence_ratio != null ? `${(Number(quality.silence_ratio) * 100).toFixed(1)}%` : '-'],
    ['削波', quality.clip_ratio != null ? `${(Number(quality.clip_ratio) * 100).toFixed(3)}%` : '-'],
    ['修复尖峰', quality.repaired_impulses ?? '-'],
    ['峰值', quality.max_abs_after ?? '-']
  ];
  $('quality-grid').innerHTML = items.map(([k, v]) => `<div><span>${escapeHtml(k)}</span><b>${escapeHtml(v)}</b></div>`).join('');
}

function renderRequests(data) {
  const requests = [...(data.active_requests || [])].sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0)).slice(0, 6);
  $('request-list').innerHTML = requests.map(req => {
    const label = req.error ? `${req.status} · ${req.error}` : req.status;
    return `<article class="request-item">
      <b>${escapeHtml(req.model || '-')} · ${escapeHtml(req.voice || '-')}</b>
      <span>${escapeHtml(label || '-')}</span>
      <small>${escapeHtml(req.chars || 0)} 字 · ${escapeHtml(req.elapsed_seconds || '-')}s</small>
    </article>`;
  }).join('') || '<p class="empty-state">暂无请求记录</p>';
}

function collectConfigValues() {
  const body = {};
  const fields = lastConfigPayload?.schema?.fields || [];
  const byKey = Object.fromEntries(fields.map(field => [field.key, field]));
  document.querySelectorAll('[data-config-field]').forEach(input => {
    const key = input.dataset.configField;
    const field = byKey[key];
    if (!field) return;
    if (field.type === 'bool') {
      body[key] = input.checked;
    } else if (field.type === 'int') {
      body[key] = Number.parseInt(input.value, 10);
    } else if (field.type === 'float') {
      body[key] = Number.parseFloat(input.value);
    } else {
      body[key] = input.value;
    }
  });
  return body;
}

async function refresh() {
  const [status, configPayload] = await Promise.all([
    api('/admin/api/status'),
    api('/admin/api/config')
  ]);
  lastData = status;
  lastConfigPayload = configPayload;
  renderMetrics(status);
  renderModels(status);
  renderProfiles(configPayload);
  renderConfigForms(configPayload);
  renderSecurity(status);
  renderQuality(status);
  renderRequests(status);
  $('env-patch').value = configPayload.env_patch || '';
  $('admin-json').textContent = JSON.stringify(status, null, 2);
}

async function loadModel(modelId) {
  toast(`正在加载 ${modelId}`);
  await api(`/admin/api/models/${encodeURIComponent(modelId)}/load`, {method: 'POST'});
  await refresh();
  toast('模型已加载');
}

async function switchModel(modelId) {
  toast(`正在切换到 ${modelId}`);
  await api('/admin/api/models/switch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({model: modelId, load: true, unload_previous: false})
  });
  await refresh();
  toast('模型已切换');
}

async function unloadModel(modelId, force = false) {
  if (force && !confirm(`强制释放 ${modelId}？正在运行的请求会被中断。`)) return;
  await api(`/admin/api/models/${encodeURIComponent(modelId)}/unload`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({force})
  });
  await refresh();
  toast(force ? '已强制释放' : '已释放模型');
}

async function saveConfig() {
  const body = collectConfigValues();
  const result = await api('/admin/api/config', {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  await refresh();
  const changed = (result.changed || []).length;
  toast(changed ? `已保存 ${changed} 项配置${(result.rebuilt_models || []).length ? '，MOSS 已重建' : (result.model_rebuild_required ? '，忙碌模型会稍后重建' : '')}` : '配置没有变化');
}

async function applyProfile(profile) {
  if (profile === 'deploy_public_hardened') {
    if (!confirm('将应用“公网加固”预设：会收紧公开接口并启用限流，是否继续？')) return;
  }
  const result = await api('/admin/api/config/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({profile})
  });
  await refresh();
  toast(`已应用预设：${result.profile}`);
}

document.addEventListener('click', async event => {
  try {
    const target = event.target.closest('button');
    if (!target) return;
    const adminTab = target.dataset.adminTab;
    const adminSubtab = target.dataset.adminSubtab;
    const loadId = target.dataset.load;
    const switchId = target.dataset.switch;
    const unloadId = target.dataset.unload;
    const forceUnloadId = target.dataset.forceUnload;
    const group = target.dataset.configGroup;
    const profile = target.dataset.profile;
    if (adminTab) {
      activeAdminTab = adminTab;
      renderAdminTab();
    }
    if (adminSubtab) {
      const [group] = adminSubtab.split('.', 1);
      activeSubtab[group] = adminSubtab;
      renderAdminSubnav();
    }
    if (loadId) await loadModel(loadId);
    if (switchId) await switchModel(switchId);
    if (unloadId) await unloadModel(unloadId, false);
    if (forceUnloadId) await unloadModel(forceUnloadId, true);
    if (group) {
      activeGroup = group;
      renderConfigForms(lastConfigPayload);
    }
    if (profile) await applyProfile(profile);
  } catch (err) {
    toast(`操作失败：${err.message}`, true);
  }
});


$('reset-runtime-config-btn').onclick = async () => {
  if (!confirm('清除 /app/outputs/runtime-config.json？清除后需重启容器或重新加载服务，ENV 才会完全接管。')) return;
  const data = await api('/admin/api/config/runtime', {method: 'DELETE'});
  await refresh();
  toast(data.removed ? '已清除持久化配置，建议重启容器' : '没有持久化配置可清除');
};
$('refresh-btn').onclick = () => refresh().then(() => toast('已刷新')).catch(err => toast(err.message, true));
$('clear-cache-btn').onclick = async () => {
  await api('/admin/api/cache', {method: 'DELETE'});
  await refresh();
  toast('缓存已清空');
};
$('unload-btn').onclick = async () => {
  if (!confirm('释放所有可释放模型？忙碌模型会跳过。')) return;
  await api('/admin/api/models/unload', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({include_current: true, force: false})});
  await refresh();
  toast('已释放空闲模型');
};
$('force-unload-btn').onclick = async () => {
  if (!confirm('强制释放所有模型？正在运行的请求会被中断。')) return;
  await api('/admin/api/models/unload', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({include_current: true, force: true})});
  await refresh();
  toast('已强制释放模型');
};
$('save-config-btn').onclick = () => saveConfig().catch(err => toast(err.message, true));
$('reveal-key-btn').onclick = async () => {
  const data = await api('/admin/api/security?reveal=true');
  $('api-key-status').textContent = data.api_key ? `当前 API Key：${data.api_key}` : '当前未启用 API Key';
};
$('rotate-key-btn').onclick = async () => {
  if (!confirm('轮换 API Key？旧客户端 token 会立即失效。')) return;
  const data = await api('/admin/api/security/key', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({rotate: true})});
  $('api-key-status').textContent = `新 API Key：${data.api_key}`;
  toast('API Key 已轮换');
};
$('export-env-btn').onclick = async () => {
  const data = await api('/admin/api/config/env');
  $('env-patch').value = data.env || '';
  document.querySelector('#env-patch').closest('details').open = true;
};

refresh().catch(err => toast(err.message, true));
renderAdminTab();
