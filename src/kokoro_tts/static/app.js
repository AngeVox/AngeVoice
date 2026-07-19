import { translate as t } from './common/i18n.js';
import { modelLabel, runtimeProviderLabel } from './studio/model-presentation.js';
import {
  modelNeedsWake,
  modelParameterSchema,
  modelRequiresPromptAudio,
  modelRequiresPromptText,
  modelSupportsVoiceClone
} from './studio/model-capabilities.js';
import {
  builtinVoiceKind
} from './studio/voice-presentation.js';
import { createReferenceRecorderController } from './studio/recording.js';
import {
  createReferenceAudioFileChooserController,
  createReferenceAudioPreviewController,
  referenceAudioProfileKey,
  referenceAudioUploadKey
} from './studio/reference-audio-preview.js';
import { createVoiceProfileController } from './studio/voice-profiles.js';
import { createHttpSynthesisController } from './studio/http-synthesis.js';
import { createAudioOutputController } from './studio/audio-output.js';
import { createErrorPresentationPolicy } from './studio/error-presentation.js';
import { createStreamPlayer } from './studio/stream-player.js';
import { createStreamSynthesisController } from './studio/stream-synthesis.js';

const bootstrapEl = document.getElementById('angevoice-bootstrap');
const bootstrap = bootstrapEl ? JSON.parse(bootstrapEl.textContent || '{}') : {};
const defaultModels = Array.isArray(bootstrap.models) && bootstrap.models.length ? bootstrap.models : [{
  id: 'kokoro',
  name: 'Kokoro v1.1 Chinese',
  backend: 'kokoro',
  provider: 'auto',
  current: true,
  loaded: true,
  available: true,
  speed_supported: true
}];

const state = {
  models: defaultModels,
  selectedModel: bootstrap.currentModel || bootstrap.defaultModel || defaultModels[0]?.id || 'kokoro',
  voices: Array.isArray(bootstrap.voices) ? bootstrap.voices : [],
  selectedVoice: bootstrap.defaultVoice || '',
  activeFilter: 'all',
  token: '',
  theme: document.documentElement.dataset.theme || 'light',
  metricsCollapsed: localStorage.getItem('angevoice.metricsCollapsed.v1') === 'true',
  favorites: readList('angevoice.favoriteVoices.v2'),
  recent: readList('angevoice.recentVoices.v2'),
  busy: false,
  promptAudioFile: null,
  lastAppliedModelId: '',
  authRejected: false,
  hasCookieSession: false,
  engineParams: {},
  toastTimer: null,
  progressTranslation: null,
  recordingTranslation: null,
  promptAudioStatusTranslation: null,
  composeTextEdited: false,
  zipvoiceExpanded: false,
  textNormalization: localStorage.getItem('angevoice.textNormalization.v1') || 'default'
};
localStorage.removeItem('angevoice.apiToken.v1');
// Restore cookie session awareness from server-injected bootstrap (survives page refresh)
state.hasCookieSession = Boolean(bootstrap.hasCookieSession);

const els = {
  form: document.getElementById('tts-form'),
  text: document.getElementById('text'),
  charCount: document.getElementById('char-count'),
  maxCount: document.getElementById('max-count'),
  model: document.getElementById('model-select'),
  modelStatus: document.getElementById('model-status'),
  voice: document.getElementById('voice'),
  voiceSearch: document.getElementById('voice-search'),
  voiceTabs: document.getElementById('voice-tabs'),
  voiceList: document.getElementById('voice-list'),
  favoriteBtn: document.getElementById('favorite-btn'),
  speed: document.getElementById('speed'),
  speedValue: document.getElementById('speed-value'),
  streamToggle: document.getElementById('stream-toggle'),
  textNormalization: document.getElementById('text-normalization'),
  engineParameters: document.getElementById('engine-parameters'),
  engineParameterFields: document.getElementById('engine-parameter-fields'),
  clonePanel: document.getElementById('clone-panel'),
  cloneStatus: document.getElementById('clone-status'),
  promptAudio: document.getElementById('prompt-audio'),
  promptAudioPicker: document.getElementById('prompt-audio-picker'),
  promptAudioFileName: document.getElementById('prompt-audio-file-name'),
  clearPromptAudio: document.getElementById('clear-prompt-audio'),
  recordReference: document.getElementById('record-reference-btn'),
  stopRecordReference: document.getElementById('stop-record-reference-btn'),
  recordingStatus: document.getElementById('recording-status'),
  zipvoiceCard: document.getElementById('zipvoice-card'),
  zipvoiceToggle: document.getElementById('zipvoice-toggle'),
  zipvoiceDetails: document.getElementById('zipvoice-details'),
  zipvoiceReferencePreview: document.getElementById('zipvoice-reference-preview'),
  promptText: document.getElementById('prompt-text'),
  zipvoiceRecommendBtn: document.getElementById('zipvoice-recommend-btn'),
  zipvoiceRecommendedPrompts: document.getElementById('zipvoice-recommended-prompts'),
  zipvoiceProfileSelect: document.getElementById('zipvoice-profile-select'),
  zipvoiceProfileId: document.getElementById('zipvoice-profile-id'),
  zipvoiceProfileName: document.getElementById('zipvoice-profile-name'),
  zipvoiceSaveProfile: document.getElementById('zipvoice-save-profile'),
  zipvoiceUpdateProfile: document.getElementById('zipvoice-update-profile'),
  zipvoiceDeleteProfile: document.getElementById('zipvoice-delete-profile'),
  generateBtn: document.getElementById('generate-btn'),
  previewBtn: document.getElementById('preview-btn'),
  stopBtn: document.getElementById('stop-btn'),
  clearBtn: document.getElementById('clear-btn'),
  progress: document.getElementById('progress-track'),
  toastStack: document.getElementById('toast-stack'),
  audio: document.getElementById('audio-player'),
  downloadBtn: document.getElementById('download-btn'),
  healthPill: document.getElementById('health-pill'),
  requestLog: document.getElementById('request-log'),
  bootScreen: document.getElementById('boot-screen'),
  themeBtn: document.getElementById('theme-btn'),
  statsDrawer: document.getElementById('stats-drawer'),
  metricsToggle: document.getElementById('metrics-toggle'),
  settingsBtn: document.getElementById('settings-btn'),
  settingsDialog: document.getElementById('settings-dialog'),
  tokenInput: document.getElementById('api-token'),
  saveTokenBtn: document.getElementById('save-token-btn'),
  clearTokenBtn: document.getElementById('clear-token-btn'),
  metricRequests: document.getElementById('metric-requests'),
  metricCache: document.getElementById('metric-cache'),
  metricVoices: document.getElementById('metric-voices'),
  metricActive: document.getElementById('metric-active')
};

const groups = [
  { id: 'all', labelKey: 'voices.all', match: () => true },
  { id: 'female-zh', labelKey: 'voices.female_zh', match: voice => voice.startsWith('zf_') },
  { id: 'male-zh', labelKey: 'voices.male_zh', match: voice => voice.startsWith('zm_') },
  { id: 'en', labelKey: 'voices.en', match: voice => /^[ab][fm]_/.test(voice) },
  { id: 'favorites', labelKey: 'voices.favorite', match: voice => state.favorites.includes(voice) },
  { id: 'recent', labelKey: 'voices.recent', match: voice => state.recent.includes(voice) }
];
let referenceRecorderController = null;
let referenceAudioPreviewController = null;
let referenceAudioFileChooserController = null;
let voiceProfileController = null;
let httpSynthesisController = null;
let audioOutputController = null;
let streamSynthesisController = null;
let latestSynthesisRefreshOwner = '';

function claimSynthesisRefresh(owner) {
  latestSynthesisRefreshOwner = owner;
}

function refreshForSynthesisOwner(owner) {
  if (latestSynthesisRefreshOwner !== owner) return;
  return refreshServiceState();
}

function readList(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
  } catch (_) {
    return [];
  }
}

function writeList(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  return headers;
}

async function apiFetch(url, options = {}) {
  const headers = authHeaders(options.headers || {});
  return fetch(url, { ...options, headers, credentials: 'same-origin' });
}

async function createApiSession(token) {
  const response = await fetch('/v1/auth/session', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    credentials: 'same-origin'
  });
  if (!response.ok) {
    const copy = response.status === 401
      ? descriptor('studio.error.api_key_invalid')
      : descriptor('studio.error.session_save_failed_status', { status: response.status });
    throw presentationError(localErrorPresentation(copy));
  }
  return response.json().catch(() => ({ ok: true }));
}

async function clearApiSession() {
  await fetch('/v1/auth/session', { method: 'DELETE', credentials: 'same-origin' });
}

function setHealth(kind, label) {
  els.healthPill.className = `status-pill ${kind}`;
  els.healthPill.querySelector('b').textContent = label;
}

function applyTheme(theme) {
  state.theme = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem('angevoice.theme.v1', state.theme);
  els.themeBtn.textContent = state.theme === 'dark' ? '☀' : '☾';
}

function setMetricsCollapsed(collapsed) {
  state.metricsCollapsed = collapsed;
  els.statsDrawer.classList.toggle('collapsed', collapsed);
  els.metricsToggle.textContent = collapsed ? t('stats.expand') : t('stats.collapse');
  localStorage.setItem('angevoice.metricsCollapsed.v1', String(collapsed));
}

function finishBoot() {
  window.setTimeout(() => {
    els.bootScreen?.classList.add('boot-done');
  }, 650);
  window.setTimeout(() => {
    els.bootScreen?.remove();
  }, 1200);
}

function dismissToast() {
  if (state.toastTimer) {
    window.clearTimeout(state.toastTimer);
    state.toastTimer = null;
  }
  els.toastStack?.replaceChildren();
}

function localizeToastAccessibility() {
  const closeButton = els.toastStack?.querySelector('.toast-close');
  if (closeButton) closeButton.setAttribute('aria-label', t('toast.close'));
}

function translateDescriptor(copy) {
  return t(copy.key, copy.params);
}

function descriptor(key, params = null) {
  return { key, params };
}

function isTranslationDescriptor(value) {
  return Boolean(value && typeof value === 'object' && typeof value.key === 'string');
}

function localErrorPresentation(copy) {
  return Object.freeze({
    value: copy,
    source: 'fallback',
    code: '',
    backendMessage: '',
    rawBackend: false,
  });
}

function presentationError(presentation) {
  const value = presentation?.value;
  const error = new Error(typeof value === 'string' ? value : '');
  Object.defineProperty(error, 'presentation', {
    configurable: false,
    enumerable: false,
    value: presentation,
    writable: false,
  });
  return error;
}

function localizeTransientCopy() {
  localizeToastAccessibility();
  if (state.progressTranslation && els.progress) {
    els.progress.textContent = translateDescriptor(state.progressTranslation);
  }
  const toast = els.toastStack?.querySelector('.toast');
  if (toast?.angevoiceTranslation) {
    toast.querySelector('.toast-message').textContent = translateDescriptor(toast.angevoiceTranslation);
  }
  if (state.recordingTranslation && els.recordingStatus) {
    els.recordingStatus.textContent = translateDescriptor(state.recordingTranslation);
  }
  if (state.promptAudioStatusTranslation && els.cloneStatus) {
    els.cloneStatus.textContent = translateDescriptor(state.promptAudioStatusTranslation);
  }
  referenceAudioFileChooserController?.render(state.promptAudioFile);
}

const USER_ERROR_MESSAGES = {
  NO_SYNTHESIZABLE_TEXT: descriptor('studio.error.no_synthesizable_text'),
  FFMPEG_DISABLED: descriptor('studio.error.ffmpeg_disabled'),
  FFMPEG_UNAVAILABLE: descriptor('studio.error.ffmpeg_unavailable'),
  FFMPEG_CONVERSION_FAILED: descriptor('studio.error.ffmpeg_conversion_failed')
};

function looksLikeRawBackendError(message) {
  return /integer division|ZeroDivisionError|Traceback|TypeError:|ValueError:|tokens_lens|No English or Chinese characters/i.test(String(message || ''));
}

const DEFAULT_RAW_BACKEND_FALLBACK = descriptor('studio.error.synthesis_safe_fallback');
const errorPresentationPolicy = createErrorPresentationPolicy({
  resolveKnownCode: code => (
    Object.prototype.hasOwnProperty.call(USER_ERROR_MESSAGES, code)
      ? USER_ERROR_MESSAGES[code]
      : undefined
  ),
  isRawBackendError: looksLikeRawBackendError,
});

function userFacingErrorPresentation(
  payload,
  fallback = descriptor('studio.error.request_failed'),
  options = {},
) {
  const rawFallback = options.rawFallback === undefined
    ? DEFAULT_RAW_BACKEND_FALLBACK
    : options.rawFallback;
  return errorPresentationPolicy.present(payload, { fallback, rawFallback });
}

function showToast(text, kind = 'success', { sticky = false, translation = null } = {}) {
  if (!els.toastStack || !text) return;
  if (state.toastTimer) {
    window.clearTimeout(state.toastTimer);
    state.toastTimer = null;
  }
  let toast = els.toastStack.querySelector('.toast');
  if (!toast) {
    toast = document.createElement('section');
    toast.className = 'toast';
    const dot = document.createElement('span');
    dot.className = 'toast-dot';
    const message = document.createElement('div');
    message.className = 'toast-message';
    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'toast-close';
    closeButton.textContent = '×';
    closeButton.addEventListener('click', dismissToast);
    toast.append(dot, message, closeButton);
    els.toastStack.replaceChildren(toast);
  }
  localizeToastAccessibility();
  toast.className = `toast ${kind}`;
  toast.angevoiceTranslation = translation;
  toast.querySelector('.toast-message').textContent = text;
  if (!sticky) {
    state.toastTimer = window.setTimeout(dismissToast, kind === 'error' || kind === 'warning' ? 9000 : 4800);
  }
}

function setProgress(text, isError = false, options = {}) {
  state.progressTranslation = options.translation || null;
  if (els.progress) {
    els.progress.textContent = text;
    els.progress.classList.toggle('error', isError);
  }
  if (!text) {
    dismissToast();
    return;
  }
  const loading = /正在|连接|读取|加载|唤醒|切换|处理中|合成开始|已接收音频块/.test(text);
  const kind = options.kind || (isError ? 'error' : (loading ? 'loading' : 'success'));
  showToast(text, kind, {
    sticky: options.sticky ?? (loading || isError),
    translation: state.progressTranslation
  });
}

function setTranslatedProgress(key, params = null, isError = false, options = {}) {
  const translation = { key, params: params ? { ...params } : null };
  setTranslatedDescriptor(translation, isError, options);
}

function setTranslatedDescriptor(copy, isError = false, options = {}) {
  const translation = { key: copy.key, params: copy.params ? { ...copy.params } : null };
  setProgress(translateDescriptor(translation), isError, { ...options, translation });
}

function showErrorPresentation(presentation, options = {}) {
  const value = presentation?.value;
  if (isTranslationDescriptor(value)) {
    setTranslatedDescriptor(value, true, options);
    return;
  }
  setProgress(typeof value === 'string' ? value : '', true, options);
}

function showPresentationError(error, fallback, options = {}) {
  const presentation = error?.presentation
    || userFacingErrorPresentation(error, fallback);
  showErrorPresentation(presentation, options);
}

function setZipVoiceExpanded(expanded) {
  state.zipvoiceExpanded = Boolean(expanded);
  if (!els.zipvoiceCard || !els.zipvoiceDetails || !els.zipvoiceToggle) return;
  els.zipvoiceCard.classList.toggle('collapsed', !state.zipvoiceExpanded);
  els.zipvoiceDetails.hidden = !state.zipvoiceExpanded;
  els.zipvoiceToggle.textContent = state.zipvoiceExpanded ? t('action.collapse') : t('action.expand');
  els.zipvoiceToggle.setAttribute('aria-expanded', String(state.zipvoiceExpanded));
}

function warnReferenceDuration(seconds) {
  if (!modelSupportsProfiles() || !Number.isFinite(seconds) || seconds <= 3) return;
  setTranslatedProgress(
    'studio.reference_audio.duration_warning',
    { seconds: seconds.toFixed(1) },
    false,
    { kind: 'warning' },
  );
}

function ensureAuthToken() {
  if (!bootstrap.authRequired || state.token || state.hasCookieSession) {
    return true;
  }
  if (bootstrap.adminEnabled) {
    setTranslatedProgress('studio.auth.required_admin', null, true);
  } else {
    setTranslatedProgress(
      'studio.auth.required_file',
      { api_key_file: bootstrap.apiKeyFile || 'ANGEVOICE_API_KEY_FILE' },
      true
    );
  }
  els.tokenInput.value = '';
  els.settingsDialog.showModal();
  return false;
}

function setBusy(value) {
  state.busy = value;
  updateButtons();
}

function makeClientRequestId() {
  const randomPart = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/[^A-Za-z0-9]/g, '').slice(0, 18);
  return `av_${randomPart || Date.now().toString(36)}`;
}

function cancelRequestById(requestId) {
  if (!requestId) return Promise.resolve(null);
  return apiFetch(`/v1/audio/requests/${encodeURIComponent(requestId)}/cancel`, {
    method: 'POST'
  });
}

function updateButtons() {
  const replaceableHttpOperation = Boolean(httpSynthesisController?.active);
  const controlsBusy = state.busy && !replaceableHttpOperation;
  els.generateBtn.disabled = controlsBusy;
  els.generateBtn.textContent = state.busy ? t('action.processing') : (modelNeedsWake(currentModel()) ? t('action.wake') : t('action.generate'));
  els.previewBtn.disabled = controlsBusy;
  if (els.model) {
    els.model.disabled = state.busy || bootstrap.modelSwitchEnabled === false;
  }
  els.stopBtn.disabled = !(
    state.busy
    || Boolean(streamSynthesisController?.player?.playing)
    || audioOutputController?.playing
    || streamSynthesisController?.active
    || replaceableHttpOperation
  );
  els.downloadBtn.disabled = !(
    audioOutputController?.downloadableBlob
    || streamSynthesisController?.player?.hasAudio
  );
}

function currentModel() {
  return state.models.find(model => model.id === state.selectedModel) || state.models.find(model => model.current) || state.models[0] || null;
}

function currentModelSpeedValue(model = currentModel()) {
  if (model?.speed_supported === false) {
    return 1.0;
  }
  return Number(els.speed.value) || 1.0;
}

function modelSupportsProfiles(model = currentModel()) {
  return Boolean(model?.supports_saved_voice_profiles);
}

function profileEngineId(model = currentModel()) {
  return String(model?.id || state.selectedModel || '').toLowerCase();
}

function renderEngineParameters(model = currentModel()) {
  if (!els.engineParameters || !els.engineParameterFields) return;
  const schema = modelParameterSchema(model);
  els.engineParameterFields.innerHTML = '';
  els.engineParameters.hidden = schema.length === 0;
  if (!schema.length || !model) return;
  const values = state.engineParams[model.id] || {};
  schema.forEach(spec => {
    const field = document.createElement('label');
    field.className = 'field engine-parameter-field';
    const title = document.createElement('span');
    title.textContent = spec.label || spec.key;
    let input;
    if (spec.type === 'boolean') {
      field.classList.add('toggle-row');
      input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = Object.prototype.hasOwnProperty.call(values, spec.key) ? Boolean(values[spec.key]) : Boolean(spec.default);
      field.innerHTML = '';
      field.append(input, title);
    } else {
      input = document.createElement('input');
      input.type = 'number';
      if (spec.minimum !== undefined) input.min = String(spec.minimum);
      if (spec.maximum !== undefined) input.max = String(spec.maximum);
      input.step = '1';
      input.value = String(Object.prototype.hasOwnProperty.call(values, spec.key) ? values[spec.key] : (spec.default ?? ''));
      field.append(title, input);
    }
    input.dataset.engineParameter = spec.key;
    input.dataset.parameterType = spec.type || 'string';
    input.title = spec.description || '';
    input.addEventListener('change', () => {
      state.engineParams[model.id] = collectEngineParams(model);
    });
    els.engineParameterFields.appendChild(field);
  });
}

function collectEngineParams(model = currentModel()) {
  if (!model || !els.engineParameterFields) return {};
  const params = {};
  els.engineParameterFields.querySelectorAll('[data-engine-parameter]').forEach(input => {
    const key = input.dataset.engineParameter;
    if (!key) return;
    if (input.dataset.parameterType === 'boolean') {
      params[key] = Boolean(input.checked);
    } else if (input.value !== '') {
      params[key] = Number(input.value);
    }
  });
  return params;
}

function currentTextNormalization() {
  const value = String(els.textNormalization?.value || state.textNormalization || 'default').trim().toLowerCase();
  return ['default', 'wetext', 'legacy', 'off'].includes(value) ? value : 'default';
}

function profileForVoiceId(voiceId) {
  if (!modelSupportsProfiles()) return null;
  return voiceProfileController?.findProfile(voiceId) || null;
}

function displayVoiceName(voiceId) {
  const profile = profileForVoiceId(voiceId);
  return profile?.name || voiceId;
}

function zipVoiceDescriptor(voiceId) {
  const profile = profileForVoiceId(voiceId);
  return profile
    ? t('profile.saved_voice', { voice_id: profile.voice_id })
    : t('profile.temporary_clone');
}

function zipVoiceProfileKey(voiceId) {
  const profile = profileForVoiceId(voiceId);
  return referenceAudioProfileKey({
    engineId: profileEngineId(),
    voiceId,
    revision: profile?.revision,
  });
}

function clearZipVoicePreview() {
  referenceAudioPreviewController?.clear();
}

async function normalizeUploadedZipVoicePreview(file, { force = false } = {}) {
  if (!modelSupportsProfiles() || !file || !els.zipvoiceReferencePreview || state.selectedVoice) return;
  if (bootstrap.authRequired && !state.token && !state.hasCookieSession) return;
  await referenceAudioPreviewController?.previewUploaded({
    file,
    key: referenceAudioUploadKey({ engineId: profileEngineId(), file }),
    force,
  });
}

async function loadSavedZipVoicePreview(voiceId, { force = false } = {}) {
  if (!modelSupportsProfiles() || !voiceId || !els.zipvoiceReferencePreview) return;
  if (!ensureAuthToken()) return;
  await referenceAudioPreviewController?.previewSaved({
    voiceId,
    name: displayVoiceName(voiceId),
    key: zipVoiceProfileKey(voiceId),
    force,
  });
}

function initializeReferenceAudioPreview() {
  referenceAudioPreviewController = createReferenceAudioPreviewController({
    element: els.zipvoiceReferencePreview,
    requests: {
      uploaded: (file, { signal }) => {
        const form = new FormData();
        form.append('reference_audio', file, file.name || 'reference.wav');
        return apiFetch(`/v1/reference-audio/${encodeURIComponent(profileEngineId())}/preview`, {
          method: 'POST',
          body: form,
          signal,
        });
      },
      saved: (voiceId, { signal }) => apiFetch(
        `/v1/voice-profiles/${encodeURIComponent(profileEngineId())}/${encodeURIComponent(voiceId)}/reference.wav`,
        { signal },
      ),
      readError: readErrorText,
    },
    callbacks: {
      onProgress: setTranslatedDescriptor,
      onDurationWarning: warnReferenceDuration,
    },
  });
}

function initializeReferenceAudioFileChooser() {
  referenceAudioFileChooserController = createReferenceAudioFileChooserController({
    element: els.promptAudioFileName,
    translate: t,
  });
  referenceAudioFileChooserController.render(state.promptAudioFile);
}

function initializeAudioOutput() {
  audioOutputController = createAudioOutputController({
    element: els.audio,
    createObjectURL: globalThis.URL['createObjectURL'].bind(globalThis.URL),
    revokeObjectURL: globalThis.URL['revokeObjectURL'].bind(globalThis.URL),
    triggerDownload: ({ url, filename }) => {
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.click();
    },
    schedule: globalThis.setTimeout.bind(globalThis),
    cancelSchedule: globalThis.clearTimeout.bind(globalThis),
    callbacks: { onStateChange: updateButtons },
  });
}

function createStudioStreamPlayer(callbacks = {}) {
  return createStreamPlayer({
    createAudioContext: options => {
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      return new AudioContextCtor(options);
    },
    decodeBase64: value => {
      const raw = atob(value);
      const bytes = new Uint8Array(raw.length);
      for (let index = 0; index < raw.length; index += 1) {
        bytes[index] = raw.charCodeAt(index);
      }
      return bytes;
    },
    createBlob: (parts, options) => new Blob(parts, options),
    callbacks: {
      onPlayingChange: () => callbacks.onStateChange?.(),
    },
    defaults: {
      sampleRate: Number(bootstrap.sampleRate) || 24000,
      channels: 1,
      prebufferSeconds: 0.25,
    },
  });
}

function initializeVoiceProfileController() {
  voiceProfileController = createVoiceProfileController({
    elements: {
      profileSelect: els.zipvoiceProfileSelect,
      profileId: els.zipvoiceProfileId,
      profileName: els.zipvoiceProfileName,
      promptText: els.promptText,
      recommendedPrompts: els.zipvoiceRecommendedPrompts,
      recommendButton: els.zipvoiceRecommendBtn,
      saveButton: els.zipvoiceSaveProfile,
      updateButton: els.zipvoiceUpdateProfile,
      deleteButton: els.zipvoiceDeleteProfile,
    },
    requests: {
      list: ({ engineId }) => apiFetch(`/v1/voice-profiles?engine=${encodeURIComponent(engineId)}`),
      save: ({ file, promptText, voiceId, name, engineId }) => {
        const form = new FormData();
        form.append('reference_audio', file, file.name);
        form.append('prompt_text', promptText);
        form.append('voice_id', voiceId);
        form.append('name', name);
        return apiFetch(`/v1/voice-profiles/${encodeURIComponent(engineId)}`, { method: 'POST', body: form });
      },
      update: ({ engineId, voiceId, name }) => apiFetch(
        `/v1/voice-profiles/${encodeURIComponent(engineId)}/${encodeURIComponent(voiceId)}`,
        { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) },
      ),
      delete: ({ engineId, voiceId }) => apiFetch(
        `/v1/voice-profiles/${encodeURIComponent(engineId)}/${encodeURIComponent(voiceId)}`,
        { method: 'DELETE' },
      ),
      recommended: ({ engineId }) => apiFetch(`/v1/reference-audio/${encodeURIComponent(engineId)}/recommended-prompts`),
      readError: readErrorText,
    },
    callbacks: {
      supportsProfiles: modelSupportsProfiles,
      currentEngineId: profileEngineId,
      getSelectedVoice: () => state.selectedVoice,
      setSelectedVoice: voiceId => { state.selectedVoice = voiceId; },
      getPromptAudioFile: () => state.promptAudioFile,
      ensureSaveAuthorized: ensureAuthToken,
      ensureDeleteAuthorized: ensureAuthToken,
      onProfilesChanged: ({ profiles, selectedVoice, changed, forcePreview }) => {
        state.voices = profiles.map(profile => profile.voice_id);
        if (!selectedVoice && state.selectedVoice) state.selectedVoice = '';
        renderVoiceSelect();
        renderVoices();
        if (selectedVoice && (
          forcePreview
          || referenceAudioPreviewController?.sourceKey !== zipVoiceProfileKey(selectedVoice)
        )) {
          void loadSavedZipVoicePreview(selectedVoice, { force: forcePreview });
        }
      },
      onSelection: (voiceId, { deleted = false } = {}) => {
        setZipVoiceExpanded(true);
        if (els.voice) els.voice.value = voiceId;
        renderVoices();
        renderFavorite();
        if (voiceId) {
          void loadSavedZipVoicePreview(voiceId, { force: true });
        } else if (state.promptAudioFile) {
          setPromptAudioFile(state.promptAudioFile);
        } else if (deleted || !voiceId) {
          clearZipVoicePreview();
        }
      },
      onProgress: setTranslatedDescriptor,
      onError: (error, fallbackCopy) => {
        const message = String(error?.message || '').trim();
        const fallback = translateDescriptor(fallbackCopy);
        const isDeleteFailure = fallbackCopy?.key === 'profile.delete_failed';
        const separator = document.documentElement.dataset.locale === 'en' ? ': ' : '：';
        setProgress(isDeleteFailure && message ? `${fallback}${separator}${message}` : (message || fallback), true);
      },
    },
    translate: t,
  });
}

function selectZipVoiceTemporaryReference() {
  if (!modelSupportsProfiles()) return;
  voiceProfileController?.selectVoice('');
}

function setPromptAudioFile(file, { loadPreview = true } = {}) {
  if (file && modelSupportsProfiles()) setZipVoiceExpanded(true);
  const changed = state.promptAudioFile !== (file || null);
  state.promptAudioFile = file || null;
  referenceAudioFileChooserController?.render(state.promptAudioFile);
  if (modelSupportsProfiles()) {
    voiceProfileController?.renderCopy();
    renderVoiceSelect();
  }
  if (changed) clearZipVoicePreview();
  if (els.cloneStatus) {
    if (state.promptAudioFile) {
      state.promptAudioStatusTranslation = null;
      els.cloneStatus.textContent = state.promptAudioFile.name;
    } else {
      state.promptAudioStatusTranslation = modelSupportsProfiles()
        ? descriptor('studio.reference_audio.profile_recording', { model: currentModel()?.name || t('studio.model.unknown') })
        : descriptor('studio.reference_audio.clone');
      els.cloneStatus.textContent = translateDescriptor(state.promptAudioStatusTranslation);
    }
  }
  if (els.clearPromptAudio) {
    els.clearPromptAudio.disabled = !state.promptAudioFile;
  }
  if (els.zipvoiceReferencePreview && loadPreview) {
    if (modelSupportsProfiles() && state.promptAudioFile && !state.selectedVoice) {
      normalizeUploadedZipVoicePreview(state.promptAudioFile, { force: true });
    } else if (!modelSupportsProfiles() || (!state.promptAudioFile && !state.selectedVoice)) {
      clearZipVoicePreview();
    }
  }
  applyStreamToggleState();
}

function setRecordingStatus(copy, active = false) {
  state.recordingTranslation = copy;
  if (!els.recordingStatus) return;
  els.recordingStatus.textContent = translateDescriptor(copy);
  els.recordingStatus.classList.toggle('active', Boolean(active));
}

function initializeReferenceRecorder() {
  referenceRecorderController = createReferenceRecorderController({
    elements: {
      startButton: els.recordReference,
      stopButton: els.stopRecordReference,
      fileInput: els.promptAudio,
    },
    callbacks: {
      onStatus: setRecordingStatus,
      onProgress: setTranslatedDescriptor,
      onFile: file => setPromptAudioFile(file),
      onTemporaryReference: selectZipVoiceTemporaryReference,
      onLongRecording: warnReferenceDuration,
      supportsVoiceClone: () => modelSupportsVoiceClone(currentModel()),
      supportsProfiles: modelSupportsProfiles,
      expandProfiles: () => setZipVoiceExpanded(true),
    },
  });
}

function applyStreamToggleState() {
  if (!els.streamToggle) return;
  const model = currentModel();
  const streamAvailable = Boolean(bootstrap.streamEnabled) && String(model?.stream_mode || '').toLowerCase() !== 'non_streaming';
  if (!streamAvailable) {
    els.streamToggle.checked = false;
    els.streamToggle.disabled = true;
    els.streamToggle.title = t('studio.stream.runtime_unsupported');
    return;
  }
  const cloneUploadActive = modelSupportsVoiceClone(currentModel()) && Boolean(state.promptAudioFile);
  els.streamToggle.disabled = false;
  if (String(model?.stream_mode || '') === 'segmented') {
    els.streamToggle.title = t('studio.stream.segmented');
  } else {
    els.streamToggle.title = cloneUploadActive ? t('studio.stream.reference_first_frame') : '';
  }
}

function applyModelUi() {
  const model = currentModel();
  if (!model) return;
  els.modelStatus.textContent = model.loaded ? runtimeProviderLabel(model, t) : t('studio.model.unloaded');
  els.modelStatus.className = model.available === false ? 'warn-text' : '';
  if (els.speed) {
    const speedSupported = model.speed_supported !== false;
    els.speed.disabled = !speedSupported;
    els.speed.title = speedSupported ? '' : t('studio.speed.unsupported');
    if (!speedSupported) {
      els.speed.value = '1.0';
    }
    els.speedValue.textContent = Number(els.speed.value || 1).toFixed(1);
  }
  if (modelNeedsWake(model)) {
    const idleLabel = model.idle_unloaded ? t('studio.model.sleeping') : t('studio.model.not_loaded');
    els.modelStatus.textContent = idleLabel;
    els.modelStatus.className = 'warn-text';
  }
  const cloneSupported = modelSupportsVoiceClone(model);
  if (els.clonePanel) {
    els.clonePanel.hidden = !cloneSupported;
  }
  if (els.promptAudio) {
    els.promptAudio.accept = modelSupportsProfiles(model) ? '.wav,audio/wav' : 'audio/*,.wav,.mp3,.flac,.ogg,.m4a,.aac';
    els.promptAudio.title = modelSupportsProfiles(model) ? t('studio.reference_audio.wav_only_title') : '';
  }
  if (els.zipvoiceCard) {
    els.zipvoiceCard.hidden = !modelSupportsProfiles(model);
    if (modelSupportsProfiles(model) && state.lastAppliedModelId !== model.id) setZipVoiceExpanded(false);
  }
  const modelChanged = state.lastAppliedModelId !== model.id;
  state.lastAppliedModelId = model.id;
  if (modelChanged && modelSupportsProfiles(model)) {
    const profiles = voiceProfileController?.profiles || [];
    state.voices = profiles.map(profile => profile.voice_id);
    const selectedProfileExists = profiles.some(profile => profile.voice_id === state.selectedVoice);
    if (!selectedProfileExists) {
      state.selectedVoice = '';
      if (els.voice) els.voice.value = '';
      clearZipVoicePreview();
    }
    renderVoiceSelect();
    renderVoices();
    voiceProfileController?.resetDeleteConfirmation();
  }
  if (modelSupportsProfiles(model) && (modelChanged || !voiceProfileController?.profilesLoaded)) {
    void loadZipVoiceProfiles({ forcePreview: modelChanged });
  }
  if (!cloneSupported) {
    setPromptAudioFile(null, { loadPreview: modelChanged });
    if (els.promptAudio) {
      els.promptAudio.value = '';
    }
  } else if (modelChanged && modelSupportsProfiles(model)) {
    if (state.selectedVoice) {
      loadSavedZipVoicePreview(state.selectedVoice, { force: true });
    } else if (state.promptAudioFile) {
      normalizeUploadedZipVoicePreview(state.promptAudioFile, { force: true });
    }
  }
  if (els.previewBtn) {
    els.previewBtn.textContent = modelSupportsProfiles(model) ? t('studio.preview.generate') : t('action.preview');
    els.previewBtn.title = modelSupportsProfiles(model) ? t('studio.preview.generate_title') : '';
  }
  renderEngineParameters(model);
  applyStreamToggleState();
}

function renderModelSelect() {
  if (!els.model) return;
  els.model.innerHTML = '';
  state.models.forEach(model => {
    const option = document.createElement('option');
    option.value = model.id;
    option.textContent = modelLabel(model, t);
    option.disabled = model.available === false;
    els.model.appendChild(option);
  });
  if (!state.models.some(model => model.id === state.selectedModel)) {
    state.selectedModel = state.models.find(model => model.current)?.id || state.models[0]?.id || 'kokoro';
  }
  els.model.value = state.selectedModel;
  applyModelUi();
}

function updateModelData(models = [], current = '') {
  if (Array.isArray(models) && models.length) {
    state.models = models;
  }
  if (current) {
    state.selectedModel = current;
  }
  renderModelSelect();
}

async function wakeCurrentModel() {
  const model = currentModel();
  if (!model || !modelNeedsWake(model)) {
    return false;
  }
  setBusy(true);
  setTranslatedProgress('studio.model.waking', { model_id: model.id }, false, { kind: 'loading' });
  try {
    const response = await apiFetch(`/v1/models/${encodeURIComponent(model.id)}/load`, { method: 'POST' });
    if (!response.ok) {
      throw presentationError(await readError(response));
    }
    const result = await response.json().catch(() => ({}));
    if (result.message) {
      setProgress(result.message);
    } else {
      setTranslatedProgress('studio.model.wake_success', { model_id: model.id });
    }
    await refreshServiceState();
    return true;
  } catch (error) {
    showPresentationError(error, descriptor('studio.error.model_wake_failed'));
    return false;
  } finally {
    setBusy(false);
  }
}

async function switchModel(modelId) {
  if (!modelId || modelId === state.selectedModel) return;
  if (!ensureAuthToken()) {
    renderModelSelect();
    return;
  }
  setBusy(true);
  setTranslatedProgress('studio.model.switching', { model_id: modelId }, false, { kind: 'loading' });
  try {
    const response = await apiFetch('/v1/models/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelId, unload_previous: true })
    });
    if (!response.ok) {
      throw presentationError(await readError(response));
    }
    const result = await response.json();
    state.selectedModel = result.current_model || modelId;
    setTranslatedProgress('studio.model.switched', { model_id: state.selectedModel });
    await refreshServiceState();
  } catch (error) {
    showPresentationError(error, descriptor('studio.error.model_switch_failed'));
    renderModelSelect();
  } finally {
    setBusy(false);
  }
}

function voiceKind(voice) {
  if (modelSupportsProfiles()) return zipVoiceDescriptor(voice);
  if (state.selectedModel.startsWith('moss')) return t('studio.voices.moss_preset');
  return builtinVoiceKind(voice, t);
}

function matchingVoices() {
  const keyword = els.voiceSearch.value.trim().toLowerCase();
  const group = groups.find(item => item.id === state.activeFilter) || groups[0];
  return state.voices
    .filter(group.match)
    .filter(voice => {
      if (!keyword) return true;
      return voice.toLowerCase().includes(keyword) || displayVoiceName(voice).toLowerCase().includes(keyword);
    });
}

async function loadZipVoiceProfiles({ forcePreview = false } = {}) {
  return voiceProfileController?.load({ forcePreview });
}

async function loadRecommendedPrompts() {
  return voiceProfileController?.loadRecommendedPrompts();
}

async function saveZipVoiceProfile() {
  if (ensureAuthToken()) return voiceProfileController?.save();
}

function resetDeleteProfileConfirmation() {
  voiceProfileController?.resetDeleteConfirmation();
}

async function updateSelectedVoiceProfileMetadata() {
  return voiceProfileController?.updateName();
}

async function deleteSelectedVoiceProfile() {
  if (ensureAuthToken()) return voiceProfileController?.remove();
}

function renderVoiceSelect() {
  els.voice.innerHTML = '';
  if (modelSupportsProfiles()) {
    const tempOption = document.createElement('option');
    tempOption.value = '';
    tempOption.textContent = state.promptAudioFile
      ? t('profile.temporary_clone_uploaded')
      : t('profile.temporary_clone');
    els.voice.appendChild(tempOption);
  }
  state.voices.forEach(voice => {
    const option = document.createElement('option');
    option.value = voice;
    option.textContent = displayVoiceName(voice);
    option.title = modelSupportsProfiles() ? t('studio.voices.id_title', { voice_id: voice }) : '';
    els.voice.appendChild(option);
  });
  if (!state.voices.includes(state.selectedVoice)) {
    state.selectedVoice = modelSupportsProfiles() ? '' : (state.voices[0] || '');
  }
  els.voice.value = state.selectedVoice;
}

function renderVoiceTabs() {
  els.voiceTabs.innerHTML = '';
  groups.forEach(group => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = group.id === state.activeFilter ? 'active' : '';
    button.textContent = `${t(group.labelKey)} ${state.voices.filter(group.match).length}`;
    button.addEventListener('click', () => {
      state.activeFilter = group.id;
      renderVoices();
    });
    els.voiceTabs.appendChild(button);
  });
}

function renderVoices() {
  renderVoiceTabs();
  const list = matchingVoices();
  els.voiceList.innerHTML = '';
  list.forEach(voice => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `voice-item ${voice === state.selectedVoice ? 'active' : ''}`;
    const text = document.createElement('span');
    const name = document.createElement('span');
    name.className = 'voice-name';
    name.textContent = displayVoiceName(voice);
    const kind = document.createElement('span');
    kind.className = 'voice-kind';
    kind.textContent = voiceKind(voice);
    const fav = document.createElement('span');
    fav.className = 'voice-fav';
    fav.textContent = state.favorites.includes(voice) ? '★' : '';
    text.append(name, kind);
    item.append(text, fav);
    item.addEventListener('click', () => {
      if (modelSupportsProfiles()) {
        voiceProfileController?.selectVoice(voice);
        return;
      }
      state.selectedVoice = voice;
      els.voice.value = voice;
      renderVoices();
      renderFavorite();
    });
    els.voiceList.appendChild(item);
  });
  if (!list.length) {
    const empty = document.createElement('div');
    empty.className = 'request-log-item';
    empty.textContent = t('voices.none');
    els.voiceList.appendChild(empty);
  }
  renderFavorite();
}

function renderFavorite() {
  const active = state.favorites.includes(state.selectedVoice);
  els.favoriteBtn.textContent = active ? t('voices.favorited') : t('voices.favorite');
}

function addRecent(voice) {
  if (!voice) return;
  state.recent = [voice, ...state.recent.filter(item => item !== voice)].slice(0, 8);
  writeList('angevoice.recentVoices.v2', state.recent);
}

function toggleFavorite() {
  const voice = state.selectedVoice;
  if (!voice) return;
  if (state.favorites.includes(voice)) {
    state.favorites = state.favorites.filter(item => item !== voice);
  } else {
    state.favorites = [voice, ...state.favorites];
  }
  writeList('angevoice.favoriteVoices.v2', state.favorites);
  renderVoices();
}

function updateCounter() {
  const max = Number(bootstrap.maxTextLength) || 10000;
  const count = els.text.value.length;
  els.charCount.textContent = String(count);
  els.maxCount.textContent = String(max);
  document.querySelector('.counter').className = `counter ${count > max * 0.95 ? 'danger' : count > max * 0.8 ? 'warning' : ''}`;
}

function updateMetrics(stats = {}) {
  animateNumber(els.metricRequests, stats.requests_total || 0);
  animateNumber(els.metricCache, stats.cache_items || 0);
  animateNumber(els.metricVoices, state.voices.length);
  animateNumber(els.metricActive, stats.active_requests || 0);
}

function animateNumber(el, value) {
  const next = Number(value) || 0;
  const prev = Number(el.dataset.value || '0');
  if (prev === next) return;
  el.dataset.value = String(next);
  el.animate([{ transform: 'translateY(4px)', opacity: 0.5 }, { transform: 'translateY(0)', opacity: 1 }], {
    duration: 180,
    easing: 'ease-out'
  });
  el.textContent = String(next);
}

function renderRequests(items = []) {
  els.requestLog.innerHTML = '';
  items.slice(-5).reverse().forEach(item => {
    const row = document.createElement('div');
    row.className = 'request-log-item';
    const detail = document.createElement('span');
    const id = document.createElement('b');
    id.textContent = item.id || '-';
    const meta = document.createElement('span');
    meta.textContent = `${item.voice || ''} ${item.format || ''}`.trim();
    detail.append(id, document.createElement('br'), meta);
    const status = document.createElement('span');
    status.textContent = item.status || '-';
    row.append(detail, status);
    els.requestLog.appendChild(row);
  });
}

async function refreshServiceState() {
  try {
    const health = await fetch('/health').then(resp => resp.json());
    updateModelData(health.models || [], health.current_model || health.model?.id || '');
    const hasAuth = state.token || state.hasCookieSession;
    const healthLabel = health.auth_required && !hasAuth
      ? t('studio.health.key_required')
      : `${health.status}${health.current_model ? ` · ${health.current_model}` : ''}`;
    setHealth(['ok', 'idle'].includes(health.status) ? 'ok' : '', healthLabel);
    if (!modelSupportsProfiles() && Array.isArray(health.voices) && health.voices.join('|') !== state.voices.join('|')) {
      state.voices = health.voices;
      state.selectedVoice = health.model?.default_voice || state.voices[0] || '';
      renderVoiceSelect();
      renderVoices();
    }
    updateMetrics({ cache_items: health.cache_items || 0 });
  } catch (_) {
    setHealth('error', t('studio.health.offline'));
    return;
  }

  if (bootstrap.authRequired && ((!state.token && !state.hasCookieSession) || state.authRejected)) {
    return;
  }

  try {
    const statsResp = await apiFetch('/stats');
    if (statsResp.status === 401) {
      state.authRejected = true;
      state.hasCookieSession = false;
      showErrorPresentation(localErrorPresentation(descriptor('studio.error.api_key_rotated')));
      return;
    }
    if (statsResp.ok) {
      const stats = await statsResp.json();
      updateMetrics(stats);
    }
  } catch (_) {
    // 认证可能未启用，或指标接口暂不可用。
  }

  try {
    const requestsResp = await apiFetch('/requests');
    if (requestsResp.ok) {
      const data = await requestsResp.json();
      renderRequests(data.requests || []);
    }
  } catch (_) {
    // 队列状态接口可能未启用。
  }
}

function httpSynthesisSnapshot(text, voice, speed, autoplay = true) {
  const model = currentModel();
  return Object.freeze({
    model: state.selectedModel,
    text,
    voice,
    speed,
    textNormalization: currentTextNormalization(),
    engineParams: Object.freeze({ ...collectEngineParams(model) }),
    promptAudioFile: state.promptAudioFile,
    promptText: els.promptText.value.trim(),
    supportsVoiceClone: modelSupportsVoiceClone(model),
    supportsProfiles: modelSupportsProfiles(model),
    requiresPromptText: modelRequiresPromptText(model),
    requiresPromptAudio: modelRequiresPromptAudio(model),
    autoplay,
  });
}

function synthesizeHttp(text, voice, speed, autoplay = true) {
  if (!httpSynthesisController) {
    httpSynthesisController = createHttpSynthesisController({
      request: apiFetch,
      cancelRequest: cancelRequestById,
      readError,
      createRequestId: makeClientRequestId,
      callbacks: {
        onBusyChange: setBusy,
        onStart: () => {
          const retirement = streamSynthesisController.retirePlayer();
          if (retirement.completion) void retirement.completion;
          audioOutputController.beginResult();
        },
        onProgress: setTranslatedDescriptor,
        onAuthRequired: () => {
          state.hasCookieSession = false;
          state.authRejected = true;
          showErrorPresentation(localErrorPresentation(descriptor('studio.error.session_expired')));
          els.settingsDialog.showModal();
        },
        onRequestError: error => showPresentationError(
          error,
          descriptor('studio.error.generation_failed'),
        ),
        onBlob: (blob, { autoplay: shouldAutoplay }) => {
          audioOutputController.setBlob(blob, { autoplay: shouldAutoplay });
        },
        onRefresh: () => refreshForSynthesisOwner('http'),
      },
    });
  }
  claimSynthesisRefresh('http');
  return httpSynthesisController.start(httpSynthesisSnapshot(text, voice, speed, autoplay));
}

function readPromptAudioFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error());
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',', 2)[1] : value);
    };
    reader.readAsDataURL(file);
  });
}

function streamSynthesisSnapshot(text, voice, speed) {
  const model = currentModel();
  // Snapshot captures temporary-clone inputs before asynchronous preparation.
  return Object.freeze({
    text,
    model: state.selectedModel,
    voice,
    speed: Number(speed),
    textNormalization: currentTextNormalization(),
    token: state.token,
    engineParams: Object.freeze({ ...collectEngineParams(model) }),
    promptAudioFile: state.promptAudioFile,
    promptText: els.promptText.value.trim(),
    supportsVoiceClone: modelSupportsVoiceClone(model),
    supportsProfiles: modelSupportsProfiles(model),
    requiresPromptText: modelRequiresPromptText(model),
    modelId: model?.id || state.selectedModel,
    prebufferSeconds: String(model?.id || state.selectedModel).startsWith('moss') ? 3.0 : 0.25,
  });
}

function initializeStreamSynthesis() {
  streamSynthesisController = createStreamSynthesisController({
    createSocket: () => {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      return new WebSocket(`${protocol}//${location.host}/ws/v1/tts`);
    },
    readPromptAudio: readPromptAudioFile,
    cancelRequest: cancelRequestById,
    createPlayer: callbacks => createStudioStreamPlayer(callbacks),
    callbacks: {
      onBusyChange: setBusy,
      onProgress: (copy, options = {}) => {
        const { isError = false, ...progressOptions } = options;
        setTranslatedDescriptor(copy, Boolean(isError), progressOptions);
      },
      onOutputBegin: () => audioOutputController.beginResult(),
      onBlob: (blob, options) => audioOutputController.setBlob(blob, options),
      onServerError: payload => {
        showErrorPresentation(userFacingErrorPresentation(
          payload,
          descriptor('studio.error.stream_synthesis_failed'),
          {
            rawFallback: USER_ERROR_MESSAGES.NO_SYNTHESIZABLE_TEXT,
          },
        ));
      },
      onPlaybackError: error => {
        showErrorPresentation(userFacingErrorPresentation(
          error,
          descriptor('studio.error.stream_playback_failed'),
        ));
      },
      onSocketError: () => showErrorPresentation(
        localErrorPresentation(descriptor('studio.error.websocket_failed')),
      ),
      onPromptReadError: () => showErrorPresentation(
        localErrorPresentation(descriptor('studio.error.reference_audio_read_failed')),
      ),
      onSessionInvalid: () => {
        state.hasCookieSession = false;
        state.authRejected = true;
        showErrorPresentation(localErrorPresentation(descriptor('studio.error.session_expired')));
        els.settingsDialog.showModal();
      },
      onRefresh: () => refreshForSynthesisOwner('stream'),
      onStateChange: updateButtons,
    },
  });
}

function synthesizeStream(text, voice, speed) {
  claimSynthesisRefresh('stream');
  return streamSynthesisController.start(streamSynthesisSnapshot(text, voice, speed));
}

async function readError(response) {
  return errorPresentationPolicy.readResponseError(response, {
    fallback: descriptor('studio.error.request_failed'),
    rawFallback: DEFAULT_RAW_BACKEND_FALLBACK,
  });
}

async function readErrorText(response) {
  const presentation = await readError(response);
  return isTranslationDescriptor(presentation.value)
    ? translateDescriptor(presentation.value)
    : presentation.value;
}

async function stopCurrent() {
  audioOutputController.stopPlayback();
  const httpStop = httpSynthesisController?.stop();
  if (httpStop?.completion) void httpStop.completion;
  const streamStop = streamSynthesisController.stop();
  if (streamStop.completion) void streamStop.completion;
  setTranslatedProgress('studio.synthesis.stopped', null, true);
  updateButtons();
}

function downloadAudio() {
  const blob = audioOutputController.downloadableBlob || streamSynthesisController.player?.buildWavBlob();
  if (!blob) return;
  audioOutputController.download({
    blob,
    filename: `angevoice_${new Date().toISOString().replace(/[:.]/g, '-')}.wav`,
  });
}

function bindSpotlights() {
  document.querySelectorAll('.spotlight').forEach(card => {
    card.addEventListener('pointermove', event => {
      const rect = card.getBoundingClientRect();
      card.style.setProperty('--spotlight-x', `${event.clientX - rect.left}px`);
      card.style.setProperty('--spotlight-y', `${event.clientY - rect.top}px`);
    });
  });
}

function bindEvents() {
  window.addEventListener('pagehide', event => {
    if (!event.persisted) referenceAudioPreviewController?.dispose();
    if (!event.persisted) httpSynthesisController?.dispose();
    if (!event.persisted) audioOutputController?.dispose();
    if (!event.persisted) streamSynthesisController?.dispose();
  });
  els.form.addEventListener('submit', async event => {
    event.preventDefault();
    // WebSocket remains single-owner; an active HTTP operation may be replaced.
    if (state.busy && !httpSynthesisController?.active) return;
    const text = els.text.value.trim();
    if (!text) {
      setTranslatedProgress('studio.compose.text_required', null, true);
      return;
    }
    if (!ensureAuthToken()) {
      return;
    }
    if (modelNeedsWake(currentModel())) {
      await wakeCurrentModel();
      return;
    }
    state.selectedVoice = els.voice.value;
    addRecent(state.selectedVoice);
    renderVoices();
    if (streamSynthesisController.active || (httpSynthesisController?.active && els.streamToggle.checked)) {
      await stopCurrent();
    }
    const speed = currentModelSpeedValue();
    if (els.streamToggle.checked) {
      await synthesizeStream(text, state.selectedVoice, speed);
    } else {
      synthesizeHttp(text, state.selectedVoice, speed, true);
    }
  });

  els.previewBtn.addEventListener('click', () => {
    if (state.busy && !httpSynthesisController?.active) return;
    if (!ensureAuthToken()) {
      return;
    }
    if (modelNeedsWake(currentModel())) {
      wakeCurrentModel();
      return;
    }
    state.selectedVoice = els.voice.value;
    addRecent(state.selectedVoice);
    synthesizeHttp(t('studio.preview.default_text'), state.selectedVoice, currentModelSpeedValue(), true);
  });
  els.stopBtn.addEventListener('click', stopCurrent);
  els.clearBtn.addEventListener('click', () => {
    state.composeTextEdited = true;
    els.text.value = '';
    updateCounter();
  });
  els.downloadBtn.addEventListener('click', downloadAudio);
  els.favoriteBtn.addEventListener('click', toggleFavorite);
  els.model?.addEventListener('change', event => {
    switchModel(event.target.value);
  });
  els.voice.addEventListener('change', () => {
    if (modelSupportsProfiles()) {
      voiceProfileController?.selectVoice(els.voice.value);
      return;
    }
    state.selectedVoice = els.voice.value;
    renderVoices();
  });
  els.zipvoiceToggle?.addEventListener('click', () => setZipVoiceExpanded(!state.zipvoiceExpanded));
  els.voiceSearch.addEventListener('input', renderVoices);
  els.promptAudio?.addEventListener('change', () => {
    const file = els.promptAudio.files?.[0] || null;
    if (file && modelSupportsProfiles()) {
      selectZipVoiceTemporaryReference();
    }
    setPromptAudioFile(file);
  });
  els.promptAudioPicker?.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    els.promptAudio?.click();
  });
  els.recordReference?.addEventListener('click', () => referenceRecorderController?.start());
  els.stopRecordReference?.addEventListener('click', () => referenceRecorderController?.stop());
  els.clearPromptAudio?.addEventListener('click', async () => {
    if (referenceRecorderController?.active) await referenceRecorderController.discard();
    setPromptAudioFile(null);
    if (els.promptAudio) {
      els.promptAudio.value = '';
    }
  });
  els.speed.addEventListener('input', () => {
    els.speedValue.textContent = Number(els.speed.value).toFixed(1);
  });
  els.textNormalization?.addEventListener('change', () => {
    state.textNormalization = currentTextNormalization();
    localStorage.setItem('angevoice.textNormalization.v1', state.textNormalization);
  });
  els.text.addEventListener('input', () => {
    state.composeTextEdited = true;
    updateCounter();
  });
  els.themeBtn.addEventListener('click', () => {
    applyTheme(state.theme === 'dark' ? 'light' : 'dark');
  });
  els.metricsToggle.addEventListener('click', () => {
    setMetricsCollapsed(!state.metricsCollapsed);
  });
  els.settingsBtn.addEventListener('click', () => {
    els.tokenInput.value = state.token;
    els.settingsDialog.showModal();
  });
  els.saveTokenBtn.addEventListener('click', async () => {
    const token = els.tokenInput.value.trim();
    if (!token) {
      setTranslatedProgress('studio.session.token_required', null, true);
      return;
    }
    try {
      await createApiSession(token);
      state.token = '';
      state.authRejected = false;
      state.hasCookieSession = true;
      els.tokenInput.value = '';
      localStorage.removeItem('angevoice.apiToken.v1');
      els.settingsDialog.close();
      setTranslatedProgress('studio.session.saved');
      refreshServiceState();
    } catch (err) {
      showPresentationError(err, descriptor('studio.error.session_save_failed'));
    }
  });
  els.clearTokenBtn.addEventListener('click', async () => {
    state.token = '';
    state.authRejected = false;
    state.hasCookieSession = false;
    els.tokenInput.value = '';
    localStorage.removeItem('angevoice.apiToken.v1');
    try {
      await clearApiSession();
    } catch (_) {
      // Local state should still be cleared even if the server is unavailable.
    }
    setTranslatedProgress('studio.session.removed');
    refreshServiceState();
  });
  document.addEventListener('angevoice:locale-changed', () => {
    localizeTransientCopy();
    if (!state.composeTextEdited) {
      els.text.value = t('studio.compose.default_text');
      updateCounter();
    }
    setMetricsCollapsed(state.metricsCollapsed);
    setZipVoiceExpanded(state.zipvoiceExpanded);
    voiceProfileController?.renderCopy();
    applyModelUi();
    renderVoiceTabs();
    renderVoices();
    renderFavorite();
    updateButtons();
  });
}

function init() {
  if (Number(bootstrap.maxTextLength)) {
    els.text.maxLength = Number(bootstrap.maxTextLength);
  }
  if (Number(bootstrap.defaultSpeed)) {
    els.speed.value = String(bootstrap.defaultSpeed);
    els.speedValue.textContent = Number(bootstrap.defaultSpeed).toFixed(1);
  }
  if (els.textNormalization) {
    els.textNormalization.value = currentTextNormalization();
  }
  els.text.value = t('studio.compose.default_text');
  initializeAudioOutput();
  initializeStreamSynthesis();
  initializeReferenceAudioPreview();
  initializeReferenceAudioFileChooser();
  initializeVoiceProfileController();
  initializeReferenceRecorder();
  applyStreamToggleState();
  applyTheme(state.theme);
  setMetricsCollapsed(state.metricsCollapsed);
  renderModelSelect();
  renderVoiceSelect();
  renderVoices();
  updateCounter();
  updateButtons();
  bindSpotlights();
  bindEvents();
  refreshServiceState();
  setInterval(refreshServiceState, 8000);
  finishBoot();
}

init();
