import { translate as t } from './common/i18n.js?h=e8cc950b72ef';

let lastData = null;
let lastConfigPayload = null;
let activeGroup = 'kokoro';
let activeAdminTab = 'overview';
const MIB = 1024 * 1024;
const BYTE_FIELD_HINT = '按 MiB 显示和编辑，保存时会自动转换为后端 bytes。';
const adminSubtabs = {
  config: [
    { key: 'config.runtime', label: '运行配置' },
    { key: 'config.quality', label: '音频质量' },
    { key: 'config.text', labelKey: 'nav.config.text' },
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
    // 不要移除所有 subpanel 的 hidden-panel，否则会把其他 tab 的面板全部显示出来
    return;
  }
  holder.classList.add('show');
  holder.innerHTML = tabs.map(tab => `<button class="admin-subnav-btn ${activeSubtab[activeAdminTab] === tab.key ? 'active' : ''}" data-admin-subtab="${escapeHtml(tab.key)}" type="button">${escapeHtml(tab.labelKey ? t(tab.labelKey) : tab.label)}</button>`).join('');
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

function isByteConfigField(field) {
  return field?.type === 'int' && /(^|_)bytes$|max_bytes/.test(String(field.key || ''));
}

function bytesToMiB(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.round((n / MIB) * 100) / 100;
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

function renderUpdate(data = {}) {
  const card = $('update-card');
  const message = $('update-message');
  const link = $('update-release-link');
  if (!card || !message || !link) return;
  const current = data.current_version || '-';
  card.classList.toggle('available', Boolean(data.update_available));
  if (!data.enabled) {
    message.textContent = `当前版本 v${current} · 更新检查已关闭`;
  } else if (data.update_available) {
    message.textContent = `发现新版本 v${data.latest_version}（当前 v${current}），请查看发布说明后手动升级。`;
  } else if (data.checked && data.error) {
    message.textContent = `当前版本 v${current} · ${data.error}`;
  } else if (data.checked) {
    message.textContent = `当前版本 v${current} · 已是最新版本`;
  } else {
    message.textContent = `当前版本 v${current} · 尚未检查更新`;
  }
  if (data.release_url) {
    link.href = data.release_url;
    link.classList.remove('hidden-panel');
  } else {
    link.removeAttribute('href');
    link.classList.add('hidden-panel');
  }
}

async function checkUpdate({ force = false, silent = false } = {}) {
  const btn = $('check-update-btn');
  if (btn) { btn.disabled = true; btn.textContent = '检查中…'; }
  try {
    const data = await api(`/admin/api/update/check?force=${force ? 'true' : 'false'}`, { method: 'POST' });
    renderUpdate(data);
    if (!silent && data.update_available) toast(`发现新版本 v${data.latest_version}`);
    if (!silent && data.error) toast(data.error, true);
  } catch (err) {
    if (!silent) toast(`检查更新失败：${err.message}`, true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '检查更新'; }
  }
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

function providerLabel(m) {
  const provider = String(m.actual_provider || m.device || m.provider || '-').toLowerCase();
  const label = provider === 'cuda_pytorch' || provider === 'cuda' ? 'CUDA'
    : provider === 'cpu_onnx_int8' ? 'CPU ONNX INT8'
      : provider === 'cpu' ? 'CPU' : provider;
  return m.fallback ? `${label} · 已回退 CPU` : label;
}

function modelCard(m) {
  const state = m.loaded ? (m.healthy === false ? '异常' : '已加载') : (m.process_isolated ? '休眠 · 按需唤醒' : (m.idle_unloaded ? '休眠' : '未加载'));
  const active = Number(m.active_count || 0);
  const provider = providerLabel(m);
  const isolation = m.process_isolated ? `进程隔离 · Worker ${m.process_alive ? `在线${m.worker_pid ? ` #${m.worker_pid}` : ''}` : '已退出'}` : '线程内 · RAM 不保证完整回收';
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
      <span>${m.pending_rebuild ? '待重建' : (m.process_isolated && !m.process_alive ? 'RAM/VRAM 可回收' : (m.low_vram_mode ? '低显存' : '显存正常'))}</span>
      ${m.fallback_reason ? `<span title="${escapeHtml(m.fallback_reason)}">回退原因：${escapeHtml(m.fallback_reason)}</span>` : ''}
    </div>
    <div class="button-row compact">
      <button class="ghost-button small" data-load="${id}" type="button">加载</button>
      <button class="ghost-button small" data-switch="${id}" type="button">切换</button>
      <button class="ghost-button small" data-unload="${id}" type="button">释放</button>
      <button class="danger-button small" data-force-unload="${id}" type="button">${escapeHtml(t('action.force_stop'))}</button>
      <button class="ghost-button small" data-asset-check="${id}" type="button">检测模型文件</button>
      <button class="ghost-button small" data-asset-repair="${id}" type="button">下载/修复模型文件</button>
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
      <span class="config-toggle-copy"><b>${escapeHtml(field.label)} ${fieldBadge(field)}</b>${field.help ? `<small>${escapeHtml(field.help)}</small>` : ''}</span>
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
  const byteField = isByteConfigField(field);
  const displayValue = byteField ? bytesToMiB(value) : value;
  const minValue = byteField && field.min != null ? bytesToMiB(field.min) : field.min;
  const maxValue = byteField && field.max != null ? bytesToMiB(field.max) : field.max;
  const stepValue = byteField ? 1 : field.step;
  const min = minValue != null ? ` min="${escapeHtml(minValue)}"` : '';
  const max = maxValue != null ? ` max="${escapeHtml(maxValue)}"` : '';
  const step = stepValue != null ? ` step="${escapeHtml(stepValue)}"` : '';
  const unit = byteField ? ' <b class="badge">MiB</b>' : '';
  const help = byteField ? [BYTE_FIELD_HINT, field.help].filter(Boolean).join(' ') : field.help;
  return `<label class="config-field">
    <span>${escapeHtml(field.label)}${unit} ${fieldBadge(field)}</span>
    <input data-config-field="${key}" ${byteField ? 'data-config-unit="mib"' : ''} type="${type}" value="${escapeHtml(displayValue)}"${min}${max}${step}>
    ${help ? `<small>${escapeHtml(help)}</small>` : ''}
  </label>`;
}

function renderConfigTabs(schema) {
  const tabs = (schema.groups || []).filter(group => !['advanced', 'text'].includes(group.key));
  if (!tabs.some(group => group.key === activeGroup)) activeGroup = tabs[0]?.key || 'kokoro';
  $('config-tabs').innerHTML = tabs.map(group => (
    `<button class="${group.key === activeGroup ? 'active' : ''}" data-config-group="${escapeHtml(group.key)}" type="button">${escapeHtml(group.label)}</button>`
  )).join('');
}

function renderRuntimeConfigNote(payload) {
  const runtime = payload.runtime_config || {};
  const note = $('runtime-config-note');
  if (note) {
    const count = Number(runtime.field_count || 0);
    note.innerHTML = runtime.exists
      ? t('config.runtime.has_overrides', { count, path: escapeHtml(runtime.path || '') })
      : t('config.runtime.no_overrides');
    note.classList.toggle('warn', runtime.exists && count > 0);
  }
}

function renderConfigForms(payload) {
  const schema = payload.schema || {};
  const values = payload.values || {};
  renderRuntimeConfigNote(payload);
  renderConfigTabs(schema);
  const fields = schema.fields || [];
  $('config-form').innerHTML = fields
    .filter(field => !field.advanced && field.group === activeGroup)
    .map(field => fieldInput(field, values[field.key] ?? field.default))
    .join('');
  const advancedFields = fields.filter(field => field.advanced && field.group === activeGroup);
  $('advanced-config-form').innerHTML = advancedFields
    .map(field => fieldInput(field, values[field.key] ?? field.default))
    .join('');
  const advancedDetails = $('advanced-config-details');
  if (advancedDetails) {
    advancedDetails.classList.toggle('hidden-panel', advancedFields.length === 0);
    if (advancedFields.length === 0) advancedDetails.removeAttribute('open');
  }
  const textForm = $('text-config-form');
  if (textForm) {
    textForm.innerHTML = fields
      .filter(field => field.group === 'text')
      .map(field => fieldInput(field, values[field.key] ?? field.default))
      .join('');
  }
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
    ['公开模型列表', config.public_status_endpoints ? '是' : '否'],
    ['信任反代 IP', config.trust_proxy_headers ? '是' : '否'],
    ['下载源', config.model_source_effective || config.model_source || 'auto'],
    ['配置文件', config.runtime_config_file || '-'],
    ['持久化覆盖', config.runtime_config?.exists ? `${config.runtime_config.field_count || 0} 项` : '无'],
    ['管理员凭据来源', security.admin_auth_source || '-'],
    ['凭据持久化', security.admin_credentials?.persisted ? '已保存哈希' : '尚未保存']
  ].map(([k, v]) => `<div><span>${escapeHtml(k)}</span><b>${escapeHtml(v)}</b></div>`).join('');
  const warning = $('default-admin-warning');
  if (warning) {
    warning.textContent = security.admin_security_warning || '';
    warning.classList.toggle('hidden-panel', !security.admin_default_credentials_active);
  }
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
      const value = input.dataset.configUnit === 'mib' ? Number(input.value) * MIB : Number.parseInt(input.value, 10);
      body[key] = Number.isFinite(value) ? Math.round(value) : value;
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
  renderUpdate(status.update || {});
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
  if (force && !confirm(t('confirm.force_unload_model', { model: modelId }))) return;
  await api(`/admin/api/models/${encodeURIComponent(modelId)}/unload`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({force})
  });
  await refresh();
  toast(force ? t('toast.force_unloaded') : '已释放模型');
}

async function checkAsset(modelId) {
  const data = await api('/admin/api/assets?full_verify_zipvoice=true');
  const key = modelId.startsWith('moss') ? 'moss' : modelId;
  const asset = data.models?.[key] || {};
  toast(`${modelId} 模型文件：${asset.ready ? '完整' : '缺失或需要修复'}`, !asset.ready);
}

async function repairAsset(modelId) {
  if (!confirm(`下载或修复 ${modelId} 模型文件？空闲模型将先释放，并可能重新下载缺失文件。`)) return;
  const data = await api(`/admin/api/assets/${encodeURIComponent(modelId)}/repair`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({force_unload: false})
  });
  await refresh();
  toast(`${modelId} 资产修复：${data.ok ? '完成' : '仍不完整'}`, !data.ok);
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
    const assetCheckId = target.dataset.assetCheck;
    const assetRepairId = target.dataset.assetRepair;
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
    if (assetCheckId) await checkAsset(assetCheckId);
    if (assetRepairId) await repairAsset(assetRepairId);
    if (group) {
      activeGroup = group;
      renderConfigForms(lastConfigPayload);
    }
    if (profile) await applyProfile(profile);
  } catch (err) {
    toast(`操作失败：${err.message}`, true);
  }
});

document.addEventListener('angevoice:locale-changed', () => {
  renderAdminSubnav();
  if (lastData) renderModels(lastData);
  if (lastConfigPayload) renderRuntimeConfigNote(lastConfigPayload);
});


$('reset-runtime-config-btn').onclick = async () => {
  if (!confirm('清除 /app/config/runtime-config.json？清除后需重启容器或重新加载服务，ENV 才会完全接管。')) return;
  const data = await api('/admin/api/config/runtime', {method: 'DELETE'});
  await refresh();
  toast(data.removed ? '已清除持久化配置，建议重启容器' : '没有持久化配置可清除');
};
$('refresh-btn').onclick = () => refresh().then(() => toast('已刷新')).catch(err => toast(err.message, true));
$('check-update-btn').onclick = () => checkUpdate({force: true}).catch(err => toast(err.message, true));
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
  if (!confirm(t('confirm.force_unload_all'))) return;
  await api('/admin/api/models/unload', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({include_current: true, force: true})});
  await refresh();
  toast(t('toast.force_unloaded'));
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

function setCredentialFeedback(message, state = '') {
  const el = $('admin-credentials-feedback');
  el.textContent = message || '';
  el.className = `credential-feedback ${state}`.trim();
}

function toggleCredentialConfirmation(show) {
  $('confirm-admin-credentials-btn').classList.toggle('hidden-panel', !show);
  $('cancel-admin-credentials-btn').classList.toggle('hidden-panel', !show);
  $('save-admin-credentials-btn').classList.toggle('hidden-panel', show);
}

$('save-admin-credentials-btn').onclick = () => {
  const username = $('admin-username-input').value.trim();
  const password = $('admin-password-input').value;
  if (!username || !password) { toast('请输入新用户名和新密码', true); return; }
  toggleCredentialConfirmation(true);
  setCredentialFeedback('再次确认后将立即保存哈希凭据，当前登录会失效，需要使用新账号密码重新登录。', 'pending');
};
$('cancel-admin-credentials-btn').onclick = () => {
  toggleCredentialConfirmation(false);
  setCredentialFeedback('已取消保存，未修改管理员凭据。');
};
$('confirm-admin-credentials-btn').onclick = async () => {
  const username = $('admin-username-input').value.trim();
  const password = $('admin-password-input').value;
  const confirmBtn = $('confirm-admin-credentials-btn');
  const cancelBtn = $('cancel-admin-credentials-btn');
  if (!username || !password) { toggleCredentialConfirmation(false); toast('请输入新用户名和新密码', true); return; }
  confirmBtn.disabled = true;
  cancelBtn.disabled = true;
  setCredentialFeedback('正在安全保存管理员凭据…', 'pending');
  try {
    await api('/admin/api/security/credentials', {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username, password})
    });
    $('admin-password-input').value = '';
    toggleCredentialConfirmation(false);
    setCredentialFeedback('管理员凭据已安全保存。请刷新页面并使用新账号密码重新登录。', 'success');
    toast('管理员凭据已安全保存，请使用新账号密码重新登录');
  } catch (err) {
    setCredentialFeedback(`保存失败：${err.message}`, 'error');
    toast(`保存失败：${err.message}`, true);
  } finally {
    confirmBtn.disabled = false;
    cancelBtn.disabled = false;
  }
};
$('download-diagnostics-btn').onclick = async () => {
  const response = await fetch('/admin/api/diagnostics/bundle');
  if (!response.ok) throw new Error(await response.text());
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url; link.download = 'angevoice-diagnostics.zip'; link.click();
  URL.revokeObjectURL(url);
  toast('诊断包已下载');
};
$('export-env-btn').onclick = async () => {
  const data = await api('/admin/api/config/env');
  $('env-patch').value = data.env || '';
  document.querySelector('#env-patch').closest('details').open = true;
};

refresh().then(() => checkUpdate({silent: true})).catch(err => toast(err.message, true));
renderAdminTab();
