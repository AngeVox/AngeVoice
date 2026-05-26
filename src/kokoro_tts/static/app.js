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
  token: localStorage.getItem('angevoice.apiToken.v1') || '',
  theme: document.documentElement.dataset.theme || 'light',
  metricsCollapsed: localStorage.getItem('angevoice.metricsCollapsed.v1') === 'true',
  favorites: readList('angevoice.favoriteVoices.v2'),
  recent: readList('angevoice.recentVoices.v2'),
  busy: false,
  playing: false,
  currentRequestId: '',
  currentWs: null,
  currentAbort: null,
  currentPlayer: null,
  lastBlob: null,
  promptAudioFile: null,
  zipvoiceProfiles: [],
  zipvoicePreviewUrl: '',
  zipvoicePreviewSequence: 0,
  zipvoicePreviewReady: false,
  zipvoicePreviewKey: '',
  zipvoicePreviewLoadingKey: '',
  zipvoicePreviewIgnoreError: false,
  zipvoiceProfilesLoaded: false,
  zipvoiceProfilesSignature: '',
  lastAppliedModelId: '',
  authRejected: false,
  totalSegments: 0,
  totalAudioChunks: 0,
  engineParams: {},
  referenceRecorder: null,
  toastTimer: null,
  zipvoiceExpanded: false
};

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
  engineParameters: document.getElementById('engine-parameters'),
  engineParameterFields: document.getElementById('engine-parameter-fields'),
  clonePanel: document.getElementById('clone-panel'),
  cloneStatus: document.getElementById('clone-status'),
  promptAudio: document.getElementById('prompt-audio'),
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
  { id: 'all', label: '全部', match: () => true },
  { id: 'female-zh', label: '中文女声', match: voice => voice.startsWith('zf_') },
  { id: 'male-zh', label: '中文男声', match: voice => voice.startsWith('zm_') },
  { id: 'en', label: '英文', match: voice => /^[ab][fm]_/.test(voice) },
  { id: 'favorites', label: '收藏', match: voice => state.favorites.includes(voice) },
  { id: 'recent', label: '最近', match: voice => state.recent.includes(voice) }
];

class StreamPlayer {
  constructor() {
    this.ctx = null;
    this.nextStartTime = 0;
    this.sources = [];
    this.pcmChunks = [];
    this.sampleRate = Number(bootstrap.sampleRate) || 24000;
    this.channels = 1;
    this.prebufferSeconds = 0.25;
    this.audioChunks = 0;
    this.underrunCount = 0;
  }

  setPrebuffer(seconds) {
    const value = Number(seconds);
    if (Number.isFinite(value)) {
      this.prebufferSeconds = Math.max(0, Math.min(3, value));
    }
    if (this.ctx && this.audioChunks === 0) {
      this.nextStartTime = Math.max(this.nextStartTime, this.ctx.currentTime + this.prebufferSeconds);
    }
  }

  init(sampleRate = this.sampleRate, channels = this.channels) {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AudioContextCtor({ sampleRate });
    this.sampleRate = this.ctx.sampleRate;
    this.channels = Math.max(1, Number(channels) || 1);
    this.nextStartTime = this.ctx.currentTime + this.prebufferSeconds;
    this.pcmChunks = [];
    this.audioChunks = 0;
    this.underrunCount = 0;
  }

  resume() {
    if (this.ctx?.state === 'suspended') {
      this.ctx.resume();
    }
  }

  stop() {
    this.sources.forEach(source => {
      try {
        source.stop();
      } catch (_) {
        // 音频源可能已经播放结束。
      }
    });
    this.sources = [];
    this.nextStartTime = this.ctx ? this.ctx.currentTime : 0;
    this.audioChunks = 0;
  }

  bufferedSeconds() {
    if (!this.ctx) return 0;
    return Math.max(0, this.nextStartTime - this.ctx.currentTime);
  }

  enqueuePCM(base64Data, sampleRate = this.sampleRate, channels = this.channels) {
    if (!this.ctx) {
      this.init(sampleRate, channels);
    }
    this.resume();
    this.channels = Math.max(1, Number(channels) || 1);
    const bytes = decodeBase64(base64Data);
    this.pcmChunks.push(bytes);
    const samples = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2);
    const frameCount = Math.floor(samples.length / this.channels);

    const buffer = this.ctx.createBuffer(this.channels, frameCount, this.sampleRate);
    for (let channel = 0; channel < this.channels; channel += 1) {
      const target = buffer.getChannelData(channel);
      for (let frame = 0; frame < frameCount; frame += 1) {
        target[frame] = samples[(frame * this.channels) + channel] / 32767;
      }
    }
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);
    const underrun = this.audioChunks > 0 && this.nextStartTime <= this.ctx.currentTime + 0.02;
    if (underrun) {
      this.underrunCount += 1;
    }
    const start = Math.max(this.ctx.currentTime + (this.audioChunks === 0 ? this.prebufferSeconds : 0), this.nextStartTime);
    source.start(start);
    this.nextStartTime = start + buffer.duration;
    this.audioChunks += 1;
    this.sources.push(source);
    state.playing = true;
    source.onended = () => {
      this.sources = this.sources.filter(item => item !== source);
      if (this.sources.length === 0) {
        state.playing = false;
        updateButtons();
      }
    };
    updateButtons();
  }

  buildWavBlob() {
    if (!this.pcmChunks.length) {
      return null;
    }
    const total = this.pcmChunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
    const pcm = new Uint8Array(total);
    let offset = 0;
    this.pcmChunks.forEach(chunk => {
      pcm.set(chunk, offset);
      offset += chunk.byteLength;
    });

    const wav = new ArrayBuffer(44 + pcm.byteLength);
    const view = new DataView(wav);
    const write = (pos, text) => {
      for (let i = 0; i < text.length; i += 1) {
        view.setUint8(pos + i, text.charCodeAt(i));
      }
    };

    write(0, 'RIFF');
    view.setUint32(4, 36 + pcm.byteLength, true);
    write(8, 'WAVE');
    write(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, this.channels, true);
    view.setUint32(24, this.sampleRate, true);
    view.setUint32(28, this.sampleRate * this.channels * 2, true);
    view.setUint16(32, this.channels * 2, true);
    view.setUint16(34, 16, true);
    write(36, 'data');
    view.setUint32(40, pcm.byteLength, true);
    new Uint8Array(wav, 44).set(pcm);
    return new Blob([wav], { type: 'audio/wav' });
  }
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

function decodeBase64(value) {
  const raw = atob(value);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) {
    bytes[i] = raw.charCodeAt(i);
  }
  return bytes;
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
  return fetch(url, { ...options, headers });
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
  els.metricsToggle.textContent = collapsed ? '展开' : '收起';
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

function showToast(text, kind = 'success', { sticky = false } = {}) {
  if (!els.toastStack || !text) return;
  if (state.toastTimer) {
    window.clearTimeout(state.toastTimer);
    state.toastTimer = null;
  }
  let toast = els.toastStack.querySelector('.toast');
  if (!toast) {
    toast = document.createElement('section');
    toast.className = 'toast';
    toast.innerHTML = '<span class="toast-dot"></span><div class="toast-message"></div><button type="button" class="toast-close" aria-label="关闭通知">×</button>';
    toast.querySelector('.toast-close').addEventListener('click', dismissToast);
    els.toastStack.replaceChildren(toast);
  }
  toast.className = `toast ${kind}`;
  toast.querySelector('.toast-message').textContent = text;
  if (!sticky) {
    state.toastTimer = window.setTimeout(dismissToast, kind === 'error' || kind === 'warning' ? 9000 : 4800);
  }
}

function setProgress(text, isError = false, options = {}) {
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
  showToast(text, kind, { sticky: options.sticky ?? (loading || isError) });
}

function setZipVoiceExpanded(expanded) {
  state.zipvoiceExpanded = Boolean(expanded);
  if (!els.zipvoiceCard || !els.zipvoiceDetails || !els.zipvoiceToggle) return;
  els.zipvoiceCard.classList.toggle('collapsed', !state.zipvoiceExpanded);
  els.zipvoiceDetails.hidden = !state.zipvoiceExpanded;
  els.zipvoiceToggle.textContent = state.zipvoiceExpanded ? '收起' : '展开';
  els.zipvoiceToggle.setAttribute('aria-expanded', String(state.zipvoiceExpanded));
}

function warnReferenceDuration(seconds) {
  if (!modelSupportsProfiles() || !Number.isFinite(seconds) || seconds <= 3) return;
  setProgress(`参考录音为 ${seconds.toFixed(1)} 秒。ZipVoice 官方建议单人参考音频少于 3 秒；较长录音仍可使用，但可能降低速度或音质。`, false, { kind: 'warning' });
}

function ensureAuthToken() {
  if (!bootstrap.authRequired || state.token) {
    return true;
  }
  const adminTip = bootstrap.adminEnabled
    ? '可点击设置窗口里的管理后台链接，在 API Key 区域复制或轮换。'
    : `管理后台未启用时，请查看启动日志或 ${bootstrap.apiKeyFile || 'ANGEVOICE_API_KEY_FILE'}。`;
  setProgress(`服务已启用 API Key，请先填写 Bearer Token。${adminTip} KOKORO_API_KEY=auto 会在首次启动自动生成。`, true);
  els.tokenInput.value = '';
  els.settingsDialog.showModal();
  return false;
}

function setBusy(value) {
  state.busy = value;
  updateButtons();
}

function updateButtons() {
  els.generateBtn.disabled = state.busy;
  els.generateBtn.textContent = state.busy ? '处理中...' : (currentModelNeedsWake() ? '立即唤醒' : '立即生成');
  els.previewBtn.disabled = state.busy;
  if (els.model) {
    els.model.disabled = state.busy || bootstrap.modelSwitchEnabled === false;
  }
  els.stopBtn.disabled = !(state.busy || state.playing || state.currentWs || state.currentAbort);
  els.downloadBtn.disabled = !(state.lastBlob || state.currentPlayer?.pcmChunks.length);
}

function currentModel() {
  return state.models.find(model => model.id === state.selectedModel) || state.models.find(model => model.current) || state.models[0] || null;
}

function currentModelNeedsWake(model = currentModel()) {
  if (!model) return false;
  return model.available !== false && (model.loaded === false || model.idle_unloaded === true);
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

function modelRequiresPromptAudio(model = currentModel()) {
  return Boolean(model?.requires_prompt_audio);
}

function modelRequiresPromptText(model = currentModel()) {
  return Boolean(model?.requires_prompt_text);
}

function runtimeProviderLabel(model = currentModel()) {
  const provider = String(model?.actual_provider || model?.provider || '').toLowerCase();
  const display = provider === 'cuda_pytorch' || provider === 'cuda' ? 'CUDA'
    : provider === 'cpu_onnx_int8' ? 'CPU ONNX INT8'
      : provider === 'cpu' ? 'CPU' : (provider || '已加载');
  return model?.fallback ? `${display} · 已回退` : display;
}

function currentParameterSchema(model = currentModel()) {
  return Array.isArray(model?.parameter_schema) ? model.parameter_schema : [];
}

function renderEngineParameters(model = currentModel()) {
  if (!els.engineParameters || !els.engineParameterFields) return;
  const schema = currentParameterSchema(model);
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

function modelSupportsVoiceClone(model = currentModel()) {
  const modes = Array.isArray(model?.modes) ? model.modes : [];
  return Boolean(
    model?.voice_clone_supported ||
    modes.includes('voice_clone') ||
    model?.backend === 'moss-tts-nano-onnx' ||
    String(model?.id || '').startsWith('moss')
  );
}

function modelLabel(model) {
  if (!model) return '未知模型';
  return `${model.name || model.id}`;
}

function profileForVoiceId(voiceId) {
  if (!modelSupportsProfiles()) return null;
  return state.zipvoiceProfiles.find(profile => profile.voice_id === voiceId) || null;
}

function displayVoiceName(voiceId) {
  const profile = profileForVoiceId(voiceId);
  return profile?.name || voiceId;
}

function zipVoiceDescriptor(voiceId) {
  const profile = profileForVoiceId(voiceId);
  return profile ? `${currentModel()?.name || '已保存音色'} · 音色 ID ${profile.voice_id}` : '已保存参考音色';
}

function zipVoiceUploadKey(file) {
  if (!file) return '';
  return `upload:${file.name || 'reference.wav'}:${file.size || 0}:${file.lastModified || 0}`;
}

function zipVoiceProfileKey(voiceId) {
  const profile = profileForVoiceId(voiceId);
  return `profile:${voiceId}:${profile?.revision || ''}`;
}

function clearZipVoicePreview() {
  if (!els.zipvoiceReferencePreview) return;
  state.zipvoicePreviewReady = false;
  state.zipvoicePreviewKey = '';
  state.zipvoicePreviewLoadingKey = '';
  state.zipvoicePreviewIgnoreError = true;
  els.zipvoiceReferencePreview.pause();
  els.zipvoiceReferencePreview.removeAttribute('src');
  els.zipvoiceReferencePreview.hidden = true;
  els.zipvoiceReferencePreview.load();
  window.setTimeout(() => { state.zipvoicePreviewIgnoreError = false; }, 100);
  if (state.zipvoicePreviewUrl) {
    URL.revokeObjectURL(state.zipvoicePreviewUrl);
    state.zipvoicePreviewUrl = '';
  }
}

function replaceZipVoicePreviewBlob(blob, sourceKey = '') {
  if (!els.zipvoiceReferencePreview) return;
  if (!blob) {
    clearZipVoicePreview();
    return;
  }
  if (sourceKey && sourceKey === state.zipvoicePreviewKey && els.zipvoiceReferencePreview.src) {
    return;
  }
  const playableBlob = blob.type === 'audio/wav'
    ? blob
    : new Blob([blob], { type: 'audio/wav' });
  const previousUrl = state.zipvoicePreviewUrl;
  const nextUrl = URL.createObjectURL(playableBlob);
  state.zipvoicePreviewReady = false;
  state.zipvoicePreviewKey = sourceKey;
  state.zipvoicePreviewLoadingKey = '';
  state.zipvoicePreviewUrl = nextUrl;
  state.zipvoicePreviewIgnoreError = true;
  els.zipvoiceReferencePreview.pause();
  els.zipvoiceReferencePreview.src = nextUrl;
  els.zipvoiceReferencePreview.hidden = false;
  els.zipvoiceReferencePreview.load();
  window.setTimeout(() => {
    state.zipvoicePreviewIgnoreError = false;
    if (previousUrl && previousUrl !== nextUrl) {
      URL.revokeObjectURL(previousUrl);
    }
  }, 150);
}

async function responseAudioWavBlob(response) {
  const blob = await response.blob();
  return blob.type === 'audio/wav' ? blob : new Blob([await blob.arrayBuffer()], { type: 'audio/wav' });
}

async function normalizeUploadedZipVoicePreview(file, { force = false } = {}) {
  if (!modelSupportsProfiles() || !file || !els.zipvoiceReferencePreview || state.selectedVoice) return;
  if (bootstrap.authRequired && !state.token) return;
  const sourceKey = zipVoiceUploadKey(file);
  if (!force && (state.zipvoicePreviewKey === sourceKey || state.zipvoicePreviewLoadingKey === sourceKey)) return;
  state.zipvoicePreviewLoadingKey = sourceKey;
  const requestSequence = ++state.zipvoicePreviewSequence;
  const form = new FormData();
  form.append('reference_audio', file, file.name || 'reference.wav');
  try {
    const response = await apiFetch(`/v1/reference-audio/${encodeURIComponent(profileEngineId())}/preview`, { method: 'POST', body: form });
    if (!response.ok) throw new Error(await readError(response));
    if (state.promptAudioFile !== file || state.selectedVoice || requestSequence !== state.zipvoicePreviewSequence) return;
    replaceZipVoicePreviewBlob(await responseAudioWavBlob(response), sourceKey);
    const duration = Number(response.headers.get('X-AngeVoice-Duration-Seconds'));
    if (Number.isFinite(duration) && duration > 3) {
      warnReferenceDuration(duration);
    } else {
      setProgress('参考音频已准备完成，可点击播放器试听');
    }
  } catch (error) {
    if (state.promptAudioFile === file && !state.selectedVoice && requestSequence === state.zipvoicePreviewSequence) {
      clearZipVoicePreview();
      setProgress(`参考音频试听转换失败：${error.message || '请上传有效 WAV 文件'}`, true);
    }
  } finally {
    if (state.zipvoicePreviewLoadingKey === sourceKey) state.zipvoicePreviewLoadingKey = '';
  }
}

async function loadSavedZipVoicePreview(voiceId, { force = false } = {}) {
  if (!modelSupportsProfiles() || !voiceId || !els.zipvoiceReferencePreview) return;
  if (!ensureAuthToken()) return;
  const sourceKey = zipVoiceProfileKey(voiceId);
  if (!force && (state.zipvoicePreviewKey === sourceKey || state.zipvoicePreviewLoadingKey === sourceKey)) return;
  state.zipvoicePreviewLoadingKey = sourceKey;
  const requestSequence = ++state.zipvoicePreviewSequence;
  setProgress(`正在加载音色“${displayVoiceName(voiceId)}”的参考试听…`);
  try {
    const response = await apiFetch(`/v1/voice-profiles/${encodeURIComponent(profileEngineId())}/${encodeURIComponent(voiceId)}/reference.wav`);
    if (!response.ok) throw new Error(await readError(response));
    if (state.selectedVoice !== voiceId || requestSequence !== state.zipvoicePreviewSequence) return;
    replaceZipVoicePreviewBlob(await responseAudioWavBlob(response), sourceKey);
    setProgress(`音色“${displayVoiceName(voiceId)}”已加载，可点击播放器试听`);
  } catch (error) {
    if (requestSequence !== state.zipvoicePreviewSequence) return;
    clearZipVoicePreview();
    setProgress(`已保存音色试听失败：${error.message || '无法读取参考音频'}`, true);
  } finally {
    if (state.zipvoicePreviewLoadingKey === sourceKey) state.zipvoicePreviewLoadingKey = '';
  }
}

function selectZipVoiceTemporaryReference() {
  if (!modelSupportsProfiles()) return;
  state.selectedVoice = '';
  if (els.voice) els.voice.value = '';
  if (els.zipvoiceProfileSelect) els.zipvoiceProfileSelect.value = '';
  renderVoices();
}

function setPromptAudioFile(file, { loadPreview = true } = {}) {
  if (file && modelSupportsProfiles()) setZipVoiceExpanded(true);
  const changed = state.promptAudioFile !== (file || null);
  state.promptAudioFile = file || null;
  if (changed) state.zipvoicePreviewSequence += 1;
  if (els.cloneStatus) {
    els.cloneStatus.textContent = state.promptAudioFile ? state.promptAudioFile.name : (modelSupportsProfiles() ? `${currentModel()?.name || '模型'} 参考录音` : '参考音频克隆');
  }
  if (els.clearPromptAudio) {
    els.clearPromptAudio.disabled = !state.promptAudioFile;
  }
  if (els.zipvoiceReferencePreview && loadPreview) {
    if (modelSupportsProfiles() && state.promptAudioFile && !state.selectedVoice) {
      clearZipVoicePreview();
      setProgress('正在准备参考音频试听…');
      normalizeUploadedZipVoicePreview(state.promptAudioFile, { force: true });
    } else if (!modelSupportsProfiles() || (!state.promptAudioFile && !state.selectedVoice)) {
      clearZipVoicePreview();
    }
  }
  applyStreamToggleState();
}

function setRecordingStatus(message, active = false) {
  if (!els.recordingStatus) return;
  els.recordingStatus.textContent = message;
  els.recordingStatus.classList.toggle('active', Boolean(active));
}

function encodeRecordedWav(chunks, sampleRate) {
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const writeText = (offset, text) => { for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index)); };
  writeText(0, 'RIFF');
  view.setUint32(4, 36 + length * 2, true);
  writeText(8, 'WAVE');
  writeText(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, 'data');
  view.setUint32(40, length * 2, true);
  let offset = 44;
  chunks.forEach(chunk => {
    for (let index = 0; index < chunk.length; index += 1) {
      const value = Math.max(-1, Math.min(1, chunk[index]));
      view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true);
      offset += 2;
    }
  });
  return new Blob([buffer], { type: 'audio/wav' });
}

async function stopReferenceRecording({ discard = false, stoppedAtLimit = false } = {}) {
  const recorder = state.referenceRecorder;
  if (!recorder) return;
  recorder.processor?.disconnect();
  recorder.source?.disconnect();
  recorder.silentGain?.disconnect();
  recorder.stream?.getTracks().forEach(track => track.stop());
  try { await recorder.context?.close(); } catch (_) { /* already closed */ }
  state.referenceRecorder = null;
  if (els.recordReference) els.recordReference.disabled = false;
  if (els.stopRecordReference) els.stopRecordReference.disabled = true;
  if (discard || !recorder.chunks.length) {
    setRecordingStatus('录音已取消，可重新录制或上传 WAV 文件');
    return;
  }
  const blob = encodeRecordedWav(recorder.chunks, recorder.sampleRate);
  const file = new File([blob], `angevoice_reference_${Date.now()}.wav`, { type: 'audio/wav', lastModified: Date.now() });
  if (modelSupportsProfiles()) selectZipVoiceTemporaryReference();
  try {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    els.promptAudio.files = transfer.files;
  } catch (_) { /* DataTransfer can be unavailable on older browsers; state still works. */ }
  setPromptAudioFile(file);
  const seconds = recorder.totalFrames / recorder.sampleRate;
  setRecordingStatus(`${stoppedAtLimit ? '已在 15 秒上限处自动停止，' : ''}已录制 ${seconds.toFixed(1)} 秒 WAV 参考音频，可试听、保存或直接生成`);
  if (stoppedAtLimit) {
    setProgress('录音已在 15 秒上限处自动停止。建议重新录制少于 3 秒的清晰参考音频，以获得更好的克隆质量。', false, { kind: 'warning' });
  } else if (seconds > 3) {
    warnReferenceDuration(seconds);
  }
}

async function startReferenceRecording() {
  if (!modelSupportsVoiceClone()) return;
  if (modelSupportsProfiles()) setZipVoiceExpanded(true);
  if (!window.isSecureContext) {
    setProgress('当前页面通过 HTTP 打开，浏览器会禁止麦克风录音。请改用 HTTPS 或在本机通过 localhost 访问，也可直接上传 WAV 参考音频。', true);
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
    setProgress('当前浏览器无法使用网页麦克风录音，请检查权限或改为上传 WAV 参考音频。', true);
    return;
  }
  if (state.referenceRecorder) await stopReferenceRecording({ discard: true });
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    const context = new AudioContext();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    const recorder = { stream, context, source, processor, silentGain, chunks: [], sampleRate: context.sampleRate, totalFrames: 0 };
    processor.onaudioprocess = event => {
      const samples = new Float32Array(event.inputBuffer.getChannelData(0));
      recorder.chunks.push(samples);
      recorder.totalFrames += samples.length;
      const seconds = recorder.totalFrames / recorder.sampleRate;
      if (seconds >= 14.8 && !recorder.autoStopping) {
        recorder.autoStopping = true;
        setProgress('录音已达到 15 秒上限，将自动停止。ZipVoice 官方仍建议使用少于 3 秒的清晰短音频。', false, { kind: 'warning' });
        void stopReferenceRecording({ stoppedAtLimit: true });
        return;
      }
      setRecordingStatus(`录音中 ${seconds.toFixed(1)} 秒 · 官方建议少于 3 秒，最长 15 秒`, true);
    };
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(context.destination);
    state.referenceRecorder = recorder;
    els.recordReference.disabled = true;
    els.stopRecordReference.disabled = false;
    setRecordingStatus('录音中 0.0 秒 · 官方建议少于 3 秒，最长 15 秒', true);
  } catch (error) {
    const denied = error?.name === 'NotAllowedError' || error?.name === 'SecurityError';
    const guidance = denied ? '请在浏览器地址栏授予麦克风权限，或改为上传 WAV 参考音频。' : '请检查麦克风设备，或改为上传 WAV 参考音频。';
    setProgress(`无法使用麦克风：${guidance}`, true);
    setRecordingStatus('麦克风不可用，可改为上传 WAV 文件');
  }
}

function applyStreamToggleState() {
  if (!els.streamToggle) return;
  const model = currentModel();
  const streamAvailable = Boolean(bootstrap.streamEnabled) && String(model?.stream_mode || '').toLowerCase() !== 'non_streaming';
  if (!streamAvailable) {
    els.streamToggle.checked = false;
    els.streamToggle.disabled = true;
    els.streamToggle.title = '当前模型运行时暂不支持流式播放';
    return;
  }
  const cloneUploadActive = modelSupportsVoiceClone() && Boolean(state.promptAudioFile);
  els.streamToggle.disabled = false;
  if (String(model?.stream_mode || '') === 'segmented') {
    els.streamToggle.title = '分句流式：每句生成后立即播放';
  } else {
    els.streamToggle.title = cloneUploadActive ? '参考音频会随流式首包发送' : '';
  }
}

function applyModelUi() {
  const model = currentModel();
  if (!model) return;
  els.modelStatus.textContent = model.loaded ? runtimeProviderLabel(model) : '未加载';
  els.modelStatus.className = model.available === false ? 'warn-text' : '';
  if (els.speed) {
    const speedSupported = model.speed_supported !== false;
    els.speed.disabled = !speedSupported;
    els.speed.title = speedSupported ? '' : '当前模型暂不支持语速调节，MOSS 固定 speed=1.0';
    if (!speedSupported) {
      els.speed.value = '1.0';
    }
    els.speedValue.textContent = Number(els.speed.value || 1).toFixed(1);
  }
  if (currentModelNeedsWake(model)) {
    const idleLabel = model.idle_unloaded ? '已休眠，点击“立即唤醒”加载模型' : '未加载，点击“立即唤醒”加载模型';
    els.modelStatus.textContent = idleLabel;
    els.modelStatus.className = 'warn-text';
  }
  const cloneSupported = modelSupportsVoiceClone(model);
  if (els.clonePanel) {
    els.clonePanel.hidden = !cloneSupported;
  }
  if (els.promptAudio) {
    els.promptAudio.accept = modelSupportsProfiles(model) ? '.wav,audio/wav' : 'audio/*,.wav,.mp3,.flac,.ogg,.m4a,.aac';
    els.promptAudio.title = modelSupportsProfiles(model) ? '可保存音色的模型请上传或录制 WAV 参考音频' : '';
  }
  if (els.zipvoiceCard) {
    els.zipvoiceCard.hidden = !modelSupportsProfiles(model);
    if (modelSupportsProfiles(model) && state.lastAppliedModelId !== model.id) setZipVoiceExpanded(false);
  }
  const modelChanged = state.lastAppliedModelId !== model.id;
  state.lastAppliedModelId = model.id;
  if (modelSupportsProfiles(model) && (modelChanged || !state.zipvoiceProfilesLoaded)) {
    loadZipVoiceProfiles({ forcePreview: modelChanged });
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
    els.previewBtn.textContent = modelSupportsProfiles(model) ? '生成示例音频' : '试听';
    els.previewBtn.title = modelSupportsProfiles(model) ? '生成一段新的示例语音，不是播放参考录音' : '';
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
    option.textContent = modelLabel(model);
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
  if (!model || !currentModelNeedsWake(model)) {
    return false;
  }
  setBusy(true);
  setProgress(`正在唤醒 ${model.id}，首次下载/加载可能需要更久...`);
  try {
    const response = await apiFetch(`/v1/models/${encodeURIComponent(model.id)}/load`, { method: 'POST' });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    const result = await response.json().catch(() => ({}));
    setProgress(result.message || `${model.id} 已唤醒，可以立即生成`);
    await refreshServiceState();
    return true;
  } catch (error) {
    setProgress(error.message || '模型唤醒失败', true);
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
  setProgress(`正在切换到 ${modelId}...`);
  try {
    const response = await apiFetch('/v1/models/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelId, unload_previous: true })
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    const result = await response.json();
    state.selectedModel = result.current_model || modelId;
    setProgress(`已切换到 ${state.selectedModel}`);
    await refreshServiceState();
  } catch (error) {
    setProgress(error.message || '模型切换失败', true);
    renderModelSelect();
  } finally {
    setBusy(false);
  }
}

function voiceKind(voice) {
  if (modelSupportsProfiles()) return zipVoiceDescriptor(voice);
  if (state.selectedModel.startsWith('moss')) return 'MOSS 预设音色';
  if (voice.startsWith('zf_')) return '中文女声';
  if (voice.startsWith('zm_')) return '中文男声';
  if (/^[ab]f_/.test(voice)) return '英文女声';
  if (/^[ab]m_/.test(voice)) return '英文男声';
  return '其他音色';
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
  if (!modelSupportsProfiles() || !els.zipvoiceProfileSelect) return;
  try {
    const response = await apiFetch(`/v1/voice-profiles?engine=${encodeURIComponent(profileEngineId())}`);
    if (!response.ok) return;
    const data = await response.json();
    const nextProfiles = Array.isArray(data.profiles) ? data.profiles : [];
    const signature = JSON.stringify(nextProfiles.map(profile => [profile.voice_id, profile.name || '', profile.revision || '']));
    const profilesChanged = signature !== state.zipvoiceProfilesSignature;
    state.zipvoiceProfiles = nextProfiles;
    state.zipvoiceProfilesLoaded = true;
    state.zipvoiceProfilesSignature = signature;
    els.zipvoiceProfileSelect.innerHTML = '<option value="">临时克隆（使用上传参考）</option>';
    state.zipvoiceProfiles.forEach(profile => {
      const option = document.createElement('option');
      option.value = profile.voice_id;
      option.textContent = profile.name || profile.voice_id;
      els.zipvoiceProfileSelect.appendChild(option);
    });
    state.voices = state.zipvoiceProfiles.map(profile => profile.voice_id);
    if (state.selectedVoice && state.voices.includes(state.selectedVoice)) {
      els.zipvoiceProfileSelect.value = state.selectedVoice;
      const selectedProfile = profileForVoiceId(state.selectedVoice);
      if (selectedProfile && els.zipvoiceProfileName) els.zipvoiceProfileName.value = selectedProfile.name || '';
    } else {
      state.selectedVoice = '';
      if (els.zipvoiceProfileName) els.zipvoiceProfileName.value = '';
    }
    renderVoiceSelect();
    renderVoices();
    resetDeleteProfileConfirmation();
    if (state.selectedVoice && (forcePreview || profilesChanged || state.zipvoicePreviewKey !== zipVoiceProfileKey(state.selectedVoice))) {
      await loadSavedZipVoicePreview(state.selectedVoice, { force: forcePreview || profilesChanged });
    }
  } catch (_) {
    // 音色列表需要有效 API Key；生成时仍会给出明确错误。
  }
}

async function loadRecommendedPrompts() {
  if (!els.zipvoiceRecommendedPrompts) return;
  if (els.zipvoiceRecommendedPrompts.childElementCount) {
    els.zipvoiceRecommendedPrompts.hidden = !els.zipvoiceRecommendedPrompts.hidden;
    return;
  }
  const response = await apiFetch(`/v1/reference-audio/${encodeURIComponent(profileEngineId())}/recommended-prompts`);
  if (!response.ok) return;
  const data = await response.json();
  (data.items || []).forEach(prompt => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'prompt-chip';
    button.textContent = prompt;
    button.addEventListener('click', () => { els.promptText.value = prompt; });
    els.zipvoiceRecommendedPrompts.appendChild(button);
  });
  els.zipvoiceRecommendedPrompts.hidden = false;
}

async function saveZipVoiceProfile() {
  if (!ensureAuthToken()) return;
  if (!state.promptAudioFile || !els.promptText.value.trim() || !els.zipvoiceProfileId.value.trim()) {
    setProgress('保存音色需要 WAV 参考音频、参考文本和音色 ID', true);
    return;
  }
  const form = new FormData();
  form.append('reference_audio', state.promptAudioFile, state.promptAudioFile.name);
  form.append('prompt_text', els.promptText.value.trim());
  form.append('voice_id', els.zipvoiceProfileId.value.trim());
  form.append('name', els.zipvoiceProfileName.value.trim());
  const response = await apiFetch(`/v1/voice-profiles/${encodeURIComponent(profileEngineId())}`, { method: 'POST', body: form });
  if (!response.ok) { setProgress(await readError(response), true); return; }
  const data = await response.json();
  state.selectedVoice = data.profile.voice_id;
  await loadZipVoiceProfiles({ forcePreview: true });
  els.zipvoiceProfileSelect.value = state.selectedVoice;
  setProgress(`音色“${data.profile.name || state.selectedVoice}”已保存，可直接复用`);
  resetDeleteProfileConfirmation();
}

function resetDeleteProfileConfirmation() {
  if (els.zipvoiceUpdateProfile) els.zipvoiceUpdateProfile.disabled = !state.selectedVoice;
  if (!els.zipvoiceDeleteProfile) return;
  els.zipvoiceDeleteProfile.disabled = !state.selectedVoice;
  els.zipvoiceDeleteProfile.dataset.confirming = '';
  els.zipvoiceDeleteProfile.textContent = '删除音色';
  els.zipvoiceDeleteProfile.classList.remove('confirming');
}

async function updateSelectedVoiceProfileMetadata() {
  if (!modelSupportsProfiles() || !state.selectedVoice) {
    setProgress('请先选择已保存音色', true);
    return;
  }
  const name = els.zipvoiceProfileName.value.trim();
  if (!name) {
    setProgress('请输入新的显示名称', true);
    return;
  }
  if (els.zipvoiceUpdateProfile) els.zipvoiceUpdateProfile.disabled = true;
  try {
    const response = await apiFetch(`/v1/voice-profiles/${encodeURIComponent(profileEngineId())}/${encodeURIComponent(state.selectedVoice)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    if (!response.ok) throw new Error(await readError(response));
    setProgress('音色名称已更新');
    await loadZipVoiceProfiles({ forcePreview: false });
    renderVoices();
  } catch (error) {
    setProgress(error.message || '更新音色名称失败', true);
  } finally {
    resetDeleteProfileConfirmation();
  }
}

async function deleteSelectedVoiceProfile() {
  if (!modelSupportsProfiles() || !state.selectedVoice || !ensureAuthToken()) return;
  const voiceId = state.selectedVoice;
  const profileName = displayVoiceName(voiceId);
  if (els.zipvoiceDeleteProfile.dataset.confirming !== voiceId) {
    els.zipvoiceDeleteProfile.dataset.confirming = voiceId;
    els.zipvoiceDeleteProfile.textContent = '再次点击确认删除';
    els.zipvoiceDeleteProfile.classList.add('confirming');
    setProgress(`即将删除音色“${profileName}”。再次点击删除按钮确认，此操作不可撤销。`, true);
    window.setTimeout(() => {
      if (els.zipvoiceDeleteProfile?.dataset.confirming === voiceId) resetDeleteProfileConfirmation();
    }, 6000);
    return;
  }
  els.zipvoiceDeleteProfile.disabled = true;
  try {
    const response = await apiFetch(`/v1/voice-profiles/${encodeURIComponent(profileEngineId())}/${encodeURIComponent(voiceId)}`, { method: 'DELETE' });
    if (!response.ok) throw new Error(await readError(response));
    const result = await response.json();
    if (!result.deleted) throw new Error('音色不存在或已被删除');
    state.selectedVoice = '';
    clearZipVoicePreview();
    if (els.zipvoiceProfileSelect) els.zipvoiceProfileSelect.value = '';
    if (els.voice) els.voice.value = '';
    await loadZipVoiceProfiles();
    if (state.promptAudioFile) setPromptAudioFile(state.promptAudioFile);
    setProgress(`音色“${profileName}”已删除，持久化参考音频与元数据已清理`);
  } catch (error) {
    setProgress(`删除音色失败：${error.message || '未知错误'}`, true);
  } finally {
    resetDeleteProfileConfirmation();
  }
}

function renderVoiceSelect() {
  els.voice.innerHTML = '';
  if (modelSupportsProfiles()) {
    const tempOption = document.createElement('option');
    tempOption.value = '';
    tempOption.textContent = '临时克隆（上传参考音频）';
    els.voice.appendChild(tempOption);
  }
  state.voices.forEach(voice => {
    const option = document.createElement('option');
    option.value = voice;
    option.textContent = displayVoiceName(voice);
    option.title = modelSupportsProfiles() ? `音色 ID：${voice}` : '';
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
    button.textContent = `${group.label} ${state.voices.filter(group.match).length}`;
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
      state.selectedVoice = voice;
      els.voice.value = voice;
      if (modelSupportsProfiles() && els.zipvoiceProfileSelect) {
        els.zipvoiceProfileSelect.value = voice;
        loadSavedZipVoicePreview(voice);
      }
      renderVoices();
      renderFavorite();
    });
    els.voiceList.appendChild(item);
  });
  if (!list.length) {
    const empty = document.createElement('div');
    empty.className = 'request-log-item';
    empty.textContent = '没有匹配的音色';
    els.voiceList.appendChild(empty);
  }
  renderFavorite();
}

function renderFavorite() {
  const active = state.favorites.includes(state.selectedVoice);
  els.favoriteBtn.textContent = active ? '已收藏' : '收藏';
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
    const healthLabel = health.auth_required && !state.token ? '需要 Key' : `${health.status}${health.current_model ? ` · ${health.current_model}` : ''}`;
    setHealth(['ok', 'idle'].includes(health.status) ? 'ok' : '', healthLabel);
    if (!modelSupportsProfiles() && Array.isArray(health.voices) && health.voices.join('|') !== state.voices.join('|')) {
      state.voices = health.voices;
      state.selectedVoice = health.model?.default_voice || state.voices[0] || '';
      renderVoiceSelect();
      renderVoices();
    }
    updateMetrics({ cache_items: health.cache_items || 0 });
  } catch (_) {
    setHealth('error', '离线');
    return;
  }

  if (bootstrap.authRequired && (!state.token || state.authRejected)) {
    return;
  }

  try {
    const statsResp = await apiFetch('/stats');
    if (statsResp.status === 401) {
      state.authRejected = true;
      setProgress('API Key 无效或已轮换，请在设置中重新填写后再操作音色与试听。', true);
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

async function synthesizeHttp(text, voice, speed, autoplay = true) {
  state.currentAbort = new AbortController();
  state.currentRequestId = '';
  state.lastBlob = null;
  updateButtons();
  setBusy(true);
  setProgress(modelRequiresPromptText() ? '正在生成正文音频（参考文本仅用于音色条件）...' : '正在生成 WAV...');

  try {
    const form = new FormData();
    form.append('model', state.selectedModel);
    form.append('text', text);
    form.append('voice', voice);
    form.append('speed', speed);
    form.append('response_format', 'wav');
    Object.entries(collectEngineParams()).forEach(([key, value]) => form.append(key, String(value)));
    const useUploadedReference = modelSupportsVoiceClone() && state.promptAudioFile && (!modelSupportsProfiles() || !voice);
    if (useUploadedReference) {
      form.append('prompt_audio', state.promptAudioFile, state.promptAudioFile.name);
    }
    if (useUploadedReference && modelRequiresPromptText() && !els.promptText.value.trim()) {
      throw new Error('当前模型临时克隆需要填写参考文本');
    }
    if (modelRequiresPromptAudio() && !useUploadedReference && !voice) {
      throw new Error('请上传参考音频，或选择已保存音色');
    }
    if (useUploadedReference && modelRequiresPromptText()) {
      form.append('prompt_text', els.promptText.value.trim());
    }
    const response = await apiFetch('/api/tts', {
      method: 'POST',
      body: form,
      signal: state.currentAbort.signal
    });
    state.currentRequestId = response.headers.get('X-Request-ID') || '';
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    state.lastBlob = await response.blob();
    els.audio.src = URL.createObjectURL(state.lastBlob);
    setProgress('生成完成');
    if (autoplay) {
      state.playing = true;
      els.audio.play().catch(() => {
        state.playing = false;
        updateButtons();
      });
    }
  } catch (error) {
    if (error.name !== 'AbortError') {
      setProgress(error.message || '生成失败', true);
    }
  } finally {
    state.currentAbort = null;
    setBusy(false);
    refreshServiceState();
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('参考音频读取失败'));
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',', 2)[1] : value);
    };
    reader.readAsDataURL(file);
  });
}

async function buildPromptAudioPayload() {
  if (!modelSupportsVoiceClone() || !state.promptAudioFile) {
    return null;
  }
  const file = state.promptAudioFile;
  return {
    filename: file.name || 'prompt.wav',
    mime_type: file.type || 'application/octet-stream',
    data: await readFileAsBase64(file)
  };
}

async function synthesizeStream(text, voice, speed) {
  setBusy(true);
  setProgress(modelSupportsProfiles() ? '正在建立分句流式连接（参考文本仅用于音色条件）...' : '正在建立流式连接...');
  let promptAudio = null;
  try {
    if (modelSupportsVoiceClone() && state.promptAudioFile && (!modelSupportsProfiles() || !voice)) {
      setProgress('正在读取参考音频...');
      promptAudio = await buildPromptAudioPayload();
    }
  } catch (error) {
    setProgress(error.message || '参考音频读取失败', true);
    setBusy(false);
    return;
  }

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  // Capture the WebSocket instance in a local variable so that all event
  // handlers below close over *this specific connection*.  If the user
  // stops and starts a new synthesis before the old WebSocket closes,
  // state.currentWs will already point to the new connection.  Guards
  // like `if (ws !== state.currentWs) return;` ensure the stale handlers
  // of the old connection never touch the new connection's state.
  const ws = new WebSocket(`${protocol}//${location.host}/ws/v1/tts`);
  state.currentWs = ws;
  state.currentPlayer = new StreamPlayer();
  state.currentRequestId = '';
  state.lastBlob = null;
  state.totalSegments = 0;
  state.totalAudioChunks = 0;

  ws.onopen = () => {
    // Guard: a new synthesis may have replaced state.currentWs already.
    if (ws !== state.currentWs) { try { ws.close(); } catch (_) {} return; }
    const payload = {
      text,
      model: state.selectedModel,
      voice,
      speed: Number(speed),
      format: 'pcm_s16le',
      binary: false,
      token: state.token
    };
    const engineParams = collectEngineParams();
    if (Object.keys(engineParams).length) {
      payload.engine_params = engineParams;
    }
    if (promptAudio) {
      payload.prompt_audio = promptAudio;
    }
    if (modelRequiresPromptText() && !voice && promptAudio) {
      if (!els.promptText.value.trim()) {
        setProgress('当前模型临时克隆需要填写参考文本', true);
        cleanupWs(ws, true);
        return;
      }
      // 临时克隆才发送参考文本；已保存音色仅由服务端读取其固化的参考条件。
      payload.prompt_text = els.promptText.value.trim();
    }
    ws.send(JSON.stringify(payload));
  };

  ws.onmessage = event => {
    if (ws !== state.currentWs) return;
    if (typeof event.data !== 'string') return;
    const msg = JSON.parse(event.data);
    if (msg.request_id) {
      state.currentRequestId = msg.request_id;
    }
    if (msg.type === 'started') {
      state.totalSegments = msg.segments || 0;
      state.totalAudioChunks = 0;
      state.currentPlayer.setPrebuffer(msg.recommended_prebuffer_seconds || (state.selectedModel.startsWith('moss') ? 0.75 : 0.25));
      setProgress(`流式合成开始：文本 ${state.totalSegments} 段，预缓冲 ${state.currentPlayer.prebufferSeconds.toFixed(2)}s`);
    } else if (msg.type === 'audio') {
      const doneCount = msg.index + 1;
      state.totalAudioChunks = doneCount;
      state.currentPlayer.enqueuePCM(msg.data, msg.sample_rate, msg.channels);
      const buffered = state.currentPlayer.bufferedSeconds().toFixed(2);
      const underruns = state.currentPlayer.underrunCount ? `，补帧 ${state.currentPlayer.underrunCount} 次` : '';
      setProgress(`已接收音频块 ${doneCount}，文本 ${state.totalSegments || '-'} 段，缓冲 ${buffered}s${underruns}`);
    } else if (msg.type === 'done') {
      state.lastBlob = state.currentPlayer.buildWavBlob();
      if (state.lastBlob) {
        els.audio.src = URL.createObjectURL(state.lastBlob);
      }
      setProgress(`合成完成：文本 ${msg.total_segments || state.totalSegments} 段，音频块 ${msg.total_audio_chunks || state.totalAudioChunks}`);
      cleanupWs(ws, false);
    } else if (msg.type === 'cancelled') {
      setProgress('已停止', true);
      cleanupWs(ws, false);
    } else if (msg.type === 'error' || msg.type === 'segment_error') {
      setProgress(msg.message || '流式合成失败', true);
      cleanupWs(ws, true);
    }
  };

  ws.onerror = () => {
    if (ws !== state.currentWs) return;
    setProgress('WebSocket 连接失败', true);
    cleanupWs(ws, true);
  };

  ws.onclose = () => {
    if (ws !== state.currentWs) return;
    cleanupWs(ws, false);
  };
}

function cleanupWs(ws, hadError) {
  // Guard: only clean up state if this WebSocket is still the active one.
  // If a new synthesis has already started, state.currentWs points to the
  // new connection and we must not touch it here.
  if (ws !== state.currentWs) {
    // The caller's WS is stale; just make sure it's closed and bail out.
    try { ws.close(); } catch (_) {}
    return;
  }
  // Detach all handlers before closing so that ws.close() below does not
  // re-trigger this function through the onclose event.
  ws.onopen = null;
  ws.onmessage = null;
  ws.onerror = null;
  ws.onclose = null;
  try {
    ws.close();
  } catch (_) {
    // 连接已经关闭。
  }
  state.currentWs = null;
  setBusy(false);
  if (!hadError) {
    refreshServiceState();
  }
}

async function readError(response) {
  try {
    const data = await response.json();
    return data.detail || response.statusText;
  } catch (_) {
    return response.statusText || '请求失败';
  }
}

async function stopCurrent() {
  if (state.currentPlayer) {
    state.currentPlayer.stop();
  }
  state.playing = false;
  try {
    els.audio.pause();
    els.audio.currentTime = 0;
  } catch (_) {
    // 播放器当前可能没有音频来源。
  }
  if (state.currentAbort) {
    state.currentAbort.abort();
    state.currentAbort = null;
  }
  // Detach all handlers from the current WebSocket BEFORE sending cancel and
  // before closing, so that the ws.onclose event does not fire cleanupWs and
  // accidentally interfere with a new synthesis that may start right after.
  const ws = state.currentWs;
  if (ws) {
    ws.onopen = null;
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;
    state.currentWs = null;
    if (ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: 'cancel' })); } catch (_) {}
    }
    try { ws.close(); } catch (_) {}
  }
  if (state.currentRequestId) {
    apiFetch(`/v1/audio/requests/${state.currentRequestId}/cancel`, { method: 'POST' }).catch(() => {});
    state.currentRequestId = '';
  }
  // Mark as idle immediately so the UI is responsive for the next action.
  setBusy(false);
  setProgress('已停止', true);
  updateButtons();
}

function downloadAudio() {
  const blob = state.lastBlob || state.currentPlayer?.buildWavBlob();
  if (!blob) return;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `angevoice_${new Date().toISOString().replace(/[:.]/g, '-')}.wav`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 500);
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
  els.form.addEventListener('submit', async event => {
    event.preventDefault();
    // Block re-submission while synthesis is already in progress.
    // The generate button is disabled in this state, but form submission
    // can still fire via keyboard (Enter) even on a disabled button.
    if (state.busy) return;
    const text = els.text.value.trim();
    if (!text) {
      setProgress('请输入文本', true);
      return;
    }
    if (!ensureAuthToken()) {
      return;
    }
    if (currentModelNeedsWake()) {
      await wakeCurrentModel();
      return;
    }
    state.selectedVoice = els.voice.value;
    addRecent(state.selectedVoice);
    renderVoices();
    if (state.currentWs || state.currentAbort) {
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
    if (!ensureAuthToken()) {
      return;
    }
    if (currentModelNeedsWake()) {
      wakeCurrentModel();
      return;
    }
    state.selectedVoice = els.voice.value;
    addRecent(state.selectedVoice);
    synthesizeHttp('你好，我是 AngeVoice 当前选中的音色预览。', state.selectedVoice, currentModelSpeedValue(), true);
  });
  els.stopBtn.addEventListener('click', stopCurrent);
  els.clearBtn.addEventListener('click', () => {
    els.text.value = '';
    updateCounter();
  });
  els.downloadBtn.addEventListener('click', downloadAudio);
  els.favoriteBtn.addEventListener('click', toggleFavorite);
  els.model?.addEventListener('change', event => {
    switchModel(event.target.value);
  });
  els.voice.addEventListener('change', () => {
    state.selectedVoice = els.voice.value;
    if (els.zipvoiceProfileSelect && modelSupportsProfiles()) {
      els.zipvoiceProfileSelect.value = state.selectedVoice;
      if (state.selectedVoice) {
        const selectedProfile = profileForVoiceId(state.selectedVoice);
        if (selectedProfile && els.zipvoiceProfileName) els.zipvoiceProfileName.value = selectedProfile.name || '';
        resetDeleteProfileConfirmation();
        loadSavedZipVoicePreview(state.selectedVoice, { force: true });
      } else if (state.promptAudioFile) {
        setPromptAudioFile(state.promptAudioFile);
      } else {
        replaceZipVoicePreviewBlob(null);
      }
    }
    renderVoices();
  });
  els.zipvoiceProfileSelect?.addEventListener('change', () => {
    setZipVoiceExpanded(true);
    state.selectedVoice = els.zipvoiceProfileSelect.value;
    const selectedProfile = profileForVoiceId(state.selectedVoice);
    if (els.zipvoiceProfileName) els.zipvoiceProfileName.value = selectedProfile?.name || '';
    resetDeleteProfileConfirmation();
    els.voice.value = state.selectedVoice;
    renderVoices();
    if (state.selectedVoice) {
      loadSavedZipVoicePreview(state.selectedVoice, { force: true });
    } else if (state.promptAudioFile) {
      setPromptAudioFile(state.promptAudioFile);
    } else {
      replaceZipVoicePreviewBlob(null);
    }
  });
  els.zipvoiceToggle?.addEventListener('click', () => setZipVoiceExpanded(!state.zipvoiceExpanded));
  els.zipvoiceRecommendBtn?.addEventListener('click', loadRecommendedPrompts);
  els.zipvoiceSaveProfile?.addEventListener('click', saveZipVoiceProfile);
  els.zipvoiceUpdateProfile?.addEventListener('click', updateSelectedVoiceProfileMetadata);
  els.zipvoiceDeleteProfile?.addEventListener('click', deleteSelectedVoiceProfile);
  els.voiceSearch.addEventListener('input', renderVoices);
  els.promptAudio?.addEventListener('change', () => {
    const file = els.promptAudio.files?.[0] || null;
    if (file && modelSupportsProfiles()) {
      selectZipVoiceTemporaryReference();
    }
    setPromptAudioFile(file);
  });
  els.recordReference?.addEventListener('click', startReferenceRecording);
  els.stopRecordReference?.addEventListener('click', () => stopReferenceRecording());
  els.clearPromptAudio?.addEventListener('click', async () => {
    if (state.referenceRecorder) await stopReferenceRecording({ discard: true });
    setPromptAudioFile(null);
    if (els.promptAudio) {
      els.promptAudio.value = '';
    }
  });
  els.speed.addEventListener('input', () => {
    els.speedValue.textContent = Number(els.speed.value).toFixed(1);
  });
  els.text.addEventListener('input', updateCounter);
  els.audio.addEventListener('ended', () => {
    state.playing = false;
    updateButtons();
  });
  els.audio.addEventListener('pause', () => {
    if (els.audio.currentTime === 0 || els.audio.ended) {
      state.playing = false;
      updateButtons();
    }
  });

  els.zipvoiceReferencePreview?.addEventListener('loadeddata', () => {
    state.zipvoicePreviewReady = true;
    state.zipvoicePreviewIgnoreError = false;
  });
  els.zipvoiceReferencePreview?.addEventListener('error', () => {
    if (state.zipvoicePreviewIgnoreError || !els.zipvoiceReferencePreview?.getAttribute('src')) return;
    const code = els.zipvoiceReferencePreview?.error?.code || '未知';
    setProgress(`参考音频试听失败（媒体错误码 ${code}）。请在无浏览器扩展的窗口复测，并保留 Network 响应。`, true);
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
  els.saveTokenBtn.addEventListener('click', () => {
    state.token = els.tokenInput.value.trim();
    state.authRejected = false;
    if (state.token) {
      localStorage.setItem('angevoice.apiToken.v1', state.token);
    } else {
      localStorage.removeItem('angevoice.apiToken.v1');
    }
    els.settingsDialog.close();
    refreshServiceState();
  });
  els.clearTokenBtn.addEventListener('click', () => {
    state.token = '';
    state.authRejected = false;
    els.tokenInput.value = '';
    localStorage.removeItem('angevoice.apiToken.v1');
    refreshServiceState();
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
