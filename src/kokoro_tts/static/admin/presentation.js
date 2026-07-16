const MIB = 1024 * 1024;

const frozen = value => Object.freeze(value);

export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function formatBytes(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = n;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function isByteConfigField(field) {
  return field?.type === 'int' && /(^|_)bytes$|max_bytes/.test(String(field.key || ''));
}

export function bytesToMiB(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.round((n / MIB) * 100) / 100;
}

export function miBToBytes(value) {
  const bytes = Number(value) * MIB;
  return Number.isFinite(bytes) ? Math.round(bytes) : bytes;
}

export function providerLabel(model, copy) {
  const provider = String(model.actual_provider || model.device || model.provider || '-').toLowerCase();
  const label = provider === 'cuda_pytorch' || provider === 'cuda' ? 'CUDA'
    : provider === 'cpu_onnx_int8' ? 'CPU ONNX INT8'
      : provider === 'cpu' ? 'CPU' : provider;
  return model.fallback ? `${label} · ${copy.providerFallbackCpu}` : label;
}

export function healthPresentation(models, copy) {
  const unhealthy = (models || []).filter(item => item.loaded && item.healthy === false);
  return frozen({
    label: unhealthy.length ? copy.healthErrors(unhealthy.length) : copy.healthOk,
    ok: unhealthy.length === 0,
    error: unhealthy.length > 0,
  });
}

export function metricCardHtml(title, value, tone = '') {
  const safeTone = tone === 'warn' ? 'warn' : '';
  return `<article class="metric-card admin-metric ${safeTone}"><span>${escapeHtml(title)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></article>`;
}

export function metricsHtml(data, copy) {
  const models = data.models || [];
  const stats = data.stats || {};
  const loaded = models.filter(model => model.loaded).length;
  const busy = models.reduce((sum, model) => sum + Number(model.active_count || 0), 0);
  const currentModel = models.find(model => model.current) || {};
  const quality = currentModel.last_output_quality || {};
  const ok = Number(stats.requests_ok || 0);
  const average = ok ? Number(stats.synthesis_seconds_total || 0) / ok : 0;
  return [
    metricCardHtml(copy.metricCurrentModel, data.current_model || '-'),
    metricCardHtml(copy.metricLoaded, loaded),
    metricCardHtml(copy.metricActiveRequests, busy, busy ? 'warn' : ''),
    metricCardHtml(copy.metricCache, `${data.cache_items ?? 0} / ${formatBytes(data.cache_bytes || 0)}`),
    metricCardHtml(copy.metricSuccessFailure, `${stats.requests_ok || 0}/${stats.requests_error || 0}`),
    metricCardHtml(copy.metricAverageTime, average ? `${average.toFixed(2)}s` : '-'),
    metricCardHtml(copy.metricMaxSilence, quality.max_silence_ms != null ? `${quality.max_silence_ms}ms` : '-'),
    metricCardHtml(copy.metricClipRatio, quality.clip_ratio ?? '-'),
  ].join('');
}

export function modelCardHtml(model, copy) {
  const state = model.loaded
    ? (model.healthy === false ? copy.modelError : copy.modelLoaded)
    : (model.process_isolated ? copy.modelSleepingOnDemand : (model.idle_unloaded ? copy.modelSleeping : copy.modelUnloaded));
  const active = Number(model.active_count || 0);
  const provider = providerLabel(model, copy);
  const isolation = model.process_isolated
    ? `${copy.processIsolated} · ${copy.worker} ${model.process_alive ? `${copy.workerOnline}${model.worker_pid ? ` #${model.worker_pid}` : ''}` : copy.workerExited}`
    : copy.threadLocalMemory;
  const quality = model.last_output_quality || {};
  const id = escapeHtml(model.id);
  const modes = (model.modes || []).map(mode => escapeHtml(mode)).join(', ') || '-';
  const lifecycleFact = model.pending_rebuild ? copy.pendingRebuild
    : (model.process_isolated && !model.process_alive ? copy.memoryReclaimable : (model.low_vram_mode ? copy.lowVram : copy.vramNormal));
  return `<article class="model-card ${model.current ? 'current' : ''}">
    <div class="model-card-main">
      <div>
        <h3>${escapeHtml(model.name || model.id)} ${model.current ? `<b class="badge">${escapeHtml(copy.current)}</b>` : ''}</h3>
        <p>${id} · ${escapeHtml(provider)} · ${escapeHtml(isolation)}</p>
      </div>
      <span class="model-state ${model.healthy === false ? 'bad' : ''}">${escapeHtml(state)}${active ? ` · busy=${active}` : ''}</span>
    </div>
    <div class="model-facts">
      <span>${escapeHtml(copy.cache)} ${escapeHtml(model.loaded ? copy.cacheOccupied : copy.empty)}</span>
      <span>${escapeHtml(copy.modes)} ${modes}</span>
      <span>${escapeHtml(copy.longSilence)} ${escapeHtml(quality.long_silence_count ?? '-')}</span>
      <span>${escapeHtml(copy.timeout)} ${escapeHtml(model.consecutive_timeouts ?? 0)}</span>
      <span>${escapeHtml(lifecycleFact)}</span>
      ${model.fallback_reason ? `<span title="${escapeHtml(model.fallback_reason)}">${escapeHtml(copy.fallbackReason)}${escapeHtml(model.fallback_reason)}</span>` : ''}
    </div>
    <div class="button-row compact">
      <button class="ghost-button small" data-load="${id}" type="button">${escapeHtml(copy.load)}</button>
      <button class="ghost-button small" data-switch="${id}" type="button">${escapeHtml(copy.switch)}</button>
      <button class="ghost-button small" data-unload="${id}" type="button">${escapeHtml(copy.unload)}</button>
      <button class="danger-button small" data-force-unload="${id}" type="button">${escapeHtml(copy.forceStop)}</button>
      <button class="ghost-button small" data-asset-check="${id}" type="button">${escapeHtml(copy.checkAssets)}</button>
      <button class="ghost-button small" data-asset-repair="${id}" type="button">${escapeHtml(copy.repairAssets)}</button>
    </div>
  </article>`;
}

export function modelsHtml(data, copy) {
  return (data.models || []).map(model => modelCardHtml(model, copy)).join('')
    || `<p class="empty-state">${escapeHtml(copy.emptyModels)}</p>`;
}

export function fieldBadgeHtml(field, copy) {
  if (field.restart) return `<b class="badge">${escapeHtml(copy.restart)}</b>`;
  if (field.rebuild_moss) return `<b class="badge">${escapeHtml(copy.rebuild)}</b>`;
  return `<b class="badge">${escapeHtml(copy.immediate)}</b>`;
}

export function configFieldHtml(field, value, copy) {
  const key = escapeHtml(field.key);
  if (field.type === 'bool') {
    return `<label class="config-toggle">
      <input data-config-field="${key}" type="checkbox" ${value ? 'checked' : ''}>
      <span class="config-toggle-copy"><b>${escapeHtml(field.label)} ${fieldBadgeHtml(field, copy)}</b>${field.help ? `<small>${escapeHtml(field.help)}</small>` : ''}</span>
    </label>`;
  }
  if (field.type === 'choice') {
    const options = (field.choices || [])
      .map(choice => `<option value="${escapeHtml(choice.value)}" ${String(value) === String(choice.value) ? 'selected' : ''}>${escapeHtml(choice.label)}</option>`)
      .join('');
    return `<label class="config-field">
      <span>${escapeHtml(field.label)} ${fieldBadgeHtml(field, copy)}</span>
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
  const help = byteField ? [copy.byteFieldHint, field.help].filter(Boolean).join(' ') : field.help;
  return `<label class="config-field">
    <span>${escapeHtml(field.label)}${unit} ${fieldBadgeHtml(field, copy)}</span>
    <input data-config-field="${key}" ${byteField ? 'data-config-unit="mib"' : ''} type="${type}" value="${escapeHtml(displayValue)}"${min}${max}${step}>
    ${help ? `<small>${escapeHtml(help)}</small>` : ''}
  </label>`;
}

export function configTabsPresentation(schema, requestedGroup) {
  const tabs = (schema.groups || []).filter(group => !['advanced', 'text'].includes(group.key));
  const activeGroup = tabs.some(group => group.key === requestedGroup) ? requestedGroup : (tabs[0]?.key || 'kokoro');
  const html = tabs.map(group => (
    `<button class="${group.key === activeGroup ? 'active' : ''}" data-config-group="${escapeHtml(group.key)}" type="button">${escapeHtml(group.label)}</button>`
  )).join('');
  return frozen({ html, activeGroup });
}

export function configPresentation(payload, requestedGroup, copy) {
  const schema = payload.schema || {};
  const values = payload.values || {};
  const tabs = configTabsPresentation(schema, requestedGroup);
  const fields = schema.fields || [];
  const standardHtml = fields
    .filter(field => !field.advanced && field.group === tabs.activeGroup)
    .map(field => configFieldHtml(field, values[field.key] ?? field.default, copy))
    .join('');
  const advancedFields = fields.filter(field => field.advanced && field.group === tabs.activeGroup);
  const advancedHtml = advancedFields
    .map(field => configFieldHtml(field, values[field.key] ?? field.default, copy))
    .join('');
  const textHtml = fields
    .filter(field => field.group === 'text')
    .map(field => configFieldHtml(field, values[field.key] ?? field.default, copy))
    .join('');
  return frozen({
    tabsHtml: tabs.html,
    activeGroup: tabs.activeGroup,
    standardHtml,
    advancedHtml,
    textHtml,
    hasAdvanced: advancedFields.length > 0,
  });
}

const profileCardHtml = profile => `<button class="profile-card" data-profile="${escapeHtml(profile.key)}" type="button">
    <b>${escapeHtml(profile.label)}</b>
    <span>${escapeHtml(profile.description)}</span>
  </button>`;

export function profilesPresentation(payload) {
  const profiles = payload.schema?.profiles || [];
  const tuning = profiles.filter(profile => !String(profile.key).startsWith('deploy_'));
  const deploy = profiles.filter(profile => String(profile.key).startsWith('deploy_'));
  return frozen({
    tuningHtml: tuning.map(profileCardHtml).join(''),
    deployHtml: deploy.map(profileCardHtml).join(''),
  });
}

export function securityPresentation(data, copy) {
  const security = data.security || {};
  const config = data.config || {};
  const keyState = security.api_key_enabled ? copy.enabled : copy.disabled;
  const source = security.api_key_auto_generated ? copy.autoGenerated : copy.manualOrEnvironment;
  const items = [
    [copy.publicModelList, config.public_status_endpoints ? copy.yes : copy.no],
    [copy.trustProxyIp, config.trust_proxy_headers ? copy.yes : copy.no],
    [copy.downloadSource, config.model_source_effective || config.model_source || 'auto'],
    [copy.configFile, config.runtime_config_file || '-'],
    [copy.persistentOverrides, config.runtime_config?.exists ? copy.itemCount(config.runtime_config.field_count || 0) : copy.none],
    [copy.adminCredentialSource, security.admin_auth_source || '-'],
    [copy.credentialPersistence, security.admin_credentials?.persisted ? copy.hashSaved : copy.notSaved],
  ];
  return frozen({
    apiKeyStatus: copy.apiKeyStatus(keyState, source, security.api_key_preview || '-'),
    summaryHtml: items.map(([key, value]) => `<div><span>${escapeHtml(key)}</span><b>${escapeHtml(value)}</b></div>`).join(''),
    warningText: security.admin_security_warning || '',
    showWarning: Boolean(security.admin_default_credentials_active),
  });
}

export function qualityHtml(data, copy) {
  const currentModel = (data.models || []).find(model => model.current) || {};
  const quality = currentModel.last_output_quality || {};
  const vram = currentModel.vram || {};
  const items = [
    [copy.vramRemaining, vram.free_mb != null ? `${vram.free_mb}/${vram.total_mb || '-'} MB` : '-'],
    [copy.vramMode, currentModel.low_vram_mode ? copy.lowVramProtection : (currentModel.full_decode_disabled ? copy.decodeProtection : copy.normal)],
    [copy.longSilence, quality.long_silence_count ?? '-'],
    [copy.maxSilence, quality.max_silence_ms != null ? `${quality.max_silence_ms}ms` : '-'],
    [copy.silenceRatio, quality.silence_ratio != null ? `${(Number(quality.silence_ratio) * 100).toFixed(1)}%` : '-'],
    [copy.clipping, quality.clip_ratio != null ? `${(Number(quality.clip_ratio) * 100).toFixed(3)}%` : '-'],
    [copy.repairedImpulses, quality.repaired_impulses ?? '-'],
    [copy.peak, quality.max_abs_after ?? '-'],
  ];
  return items.map(([key, value]) => `<div><span>${escapeHtml(key)}</span><b>${escapeHtml(value)}</b></div>`).join('');
}

export function requestsHtml(data, copy) {
  const requests = [...(data.active_requests || [])]
    .sort((left, right) => Number(right.updated_at || 0) - Number(left.updated_at || 0))
    .slice(0, 6);
  return requests.map(request => {
    const label = request.error ? `${request.status} · ${request.error}` : request.status;
    return `<article class="request-item">
      <b>${escapeHtml(request.model || '-')} · ${escapeHtml(request.voice || '-')}</b>
      <span>${escapeHtml(label || '-')}</span>
      <small>${escapeHtml(request.chars || 0)} ${escapeHtml(copy.characters)} · ${escapeHtml(request.elapsed_seconds || '-')}s</small>
    </article>`;
  }).join('') || `<p class="empty-state">${escapeHtml(copy.emptyRequests)}</p>`;
}
