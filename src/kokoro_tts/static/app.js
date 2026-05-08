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
  totalSegments: 0
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
  clonePanel: document.getElementById('clone-panel'),
  cloneStatus: document.getElementById('clone-status'),
  promptAudio: document.getElementById('prompt-audio'),
  clearPromptAudio: document.getElementById('clear-prompt-audio'),
  generateBtn: document.getElementById('generate-btn'),
  previewBtn: document.getElementById('preview-btn'),
  stopBtn: document.getElementById('stop-btn'),
  clearBtn: document.getElementById('clear-btn'),
  progress: document.getElementById('progress-track'),
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
  }

  init(sampleRate = this.sampleRate, channels = this.channels) {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AudioContextCtor({ sampleRate });
    this.sampleRate = this.ctx.sampleRate;
    this.channels = Math.max(1, Number(channels) || 1);
    this.nextStartTime = 0;
    this.pcmChunks = [];
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
        // source may have already ended
      }
    });
    this.sources = [];
    this.nextStartTime = this.ctx ? this.ctx.currentTime : 0;
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
    const start = Math.max(this.ctx.currentTime, this.nextStartTime);
    source.start(start);
    this.nextStartTime = start + buffer.duration;
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

function setProgress(text, isError = false) {
  els.progress.textContent = text;
  els.progress.classList.toggle('show', Boolean(text));
  els.progress.classList.toggle('error', isError);
}

function ensureAuthToken() {
  if (!bootstrap.authRequired || state.token) {
    return true;
  }
  setProgress('服务已启用 API Key，请先在右上角设置中填写 Bearer Token', true);
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

function modelSupportsVoiceClone(model = currentModel()) {
  const modes = Array.isArray(model?.modes) ? model.modes : [];
  return Boolean(
    model?.voice_clone_supported ||
    modes.includes('voice_clone') ||
    model?.backend === 'moss-tts-nano-onnx' ||
    String(model?.id || '').startsWith('moss-nano')
  );
}

function modelLabel(model) {
  if (!model) return '未知模型';
  const suffix = model.experimental ? ' · 实验' : '';
  return `${model.name || model.id}${suffix}`;
}

function setPromptAudioFile(file) {
  state.promptAudioFile = file || null;
  if (els.cloneStatus) {
    els.cloneStatus.textContent = state.promptAudioFile ? state.promptAudioFile.name : 'MOSS 克隆';
  }
  if (els.clearPromptAudio) {
    els.clearPromptAudio.disabled = !state.promptAudioFile;
  }
  applyStreamToggleState();
}

function applyStreamToggleState() {
  if (!els.streamToggle) return;
  const cloneUploadActive = modelSupportsVoiceClone() && Boolean(state.promptAudioFile);
  if (!bootstrap.streamEnabled) {
    els.streamToggle.checked = false;
  }
  els.streamToggle.disabled = !bootstrap.streamEnabled;
  els.streamToggle.title = cloneUploadActive ? '参考音频会随流式首包发送' : '';
}

function applyModelUi() {
  const model = currentModel();
  if (!model) return;
  els.modelStatus.textContent = model.loaded ? (model.actual_provider || model.provider || '已加载') : '未加载';
  els.modelStatus.className = model.available === false ? 'warn-text' : '';
  if (els.speed) {
    const speedSupported = model.speed_supported !== false;
    els.speed.disabled = !speedSupported;
    els.speed.title = speedSupported ? '' : '当前模型暂不支持语速调节';
  }
  const cloneSupported = modelSupportsVoiceClone(model);
  if (els.clonePanel) {
    els.clonePanel.hidden = !cloneSupported;
  }
  if (!cloneSupported) {
    setPromptAudioFile(null);
    if (els.promptAudio) {
      els.promptAudio.value = '';
    }
  } else {
    setPromptAudioFile(state.promptAudioFile);
  }
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
  if (state.selectedModel.startsWith('moss-nano')) return 'MOSS 预设音色';
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
    .filter(voice => !keyword || voice.toLowerCase().includes(keyword));
}

function renderVoiceSelect() {
  els.voice.innerHTML = '';
  state.voices.forEach(voice => {
    const option = document.createElement('option');
    option.value = voice;
    option.textContent = voice;
    els.voice.appendChild(option);
  });
  if (!state.voices.includes(state.selectedVoice)) {
    state.selectedVoice = state.voices[0] || '';
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
    name.textContent = voice;
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
    setHealth(health.status === 'ok' ? 'ok' : '', healthLabel);
    if (Array.isArray(health.voices) && health.voices.join('|') !== state.voices.join('|')) {
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

  try {
    const statsResp = await apiFetch('/stats');
    if (statsResp.status === 401) {
      return;
    }
    if (statsResp.ok) {
      const stats = await statsResp.json();
      updateMetrics(stats);
    }
  } catch (_) {
    // auth may be disabled or metrics may be unavailable
  }

  try {
    const requestsResp = await apiFetch('/requests');
    if (requestsResp.ok) {
      const data = await requestsResp.json();
      renderRequests(data.requests || []);
    }
  } catch (_) {
    // queue status may be disabled
  }
}

async function synthesizeHttp(text, voice, speed, autoplay = true) {
  state.currentAbort = new AbortController();
  state.currentRequestId = '';
  state.lastBlob = null;
  updateButtons();
  setBusy(true);
  setProgress('正在生成 WAV...');

  try {
    const form = new FormData();
    form.append('model', state.selectedModel);
    form.append('text', text);
    form.append('voice', voice);
    form.append('speed', speed);
    form.append('response_format', 'wav');
    if (modelSupportsVoiceClone() && state.promptAudioFile) {
      form.append('prompt_audio', state.promptAudioFile, state.promptAudioFile.name);
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
  setProgress('正在建立流式连接...');
  let promptAudio = null;
  try {
    if (modelSupportsVoiceClone() && state.promptAudioFile) {
      setProgress('正在读取参考音频...');
      promptAudio = await buildPromptAudioPayload();
    }
  } catch (error) {
    setProgress(error.message || '参考音频读取失败', true);
    setBusy(false);
    return;
  }

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  state.currentWs = new WebSocket(`${protocol}//${location.host}/ws/v1/tts`);
  state.currentPlayer = new StreamPlayer();
  state.currentRequestId = '';
  state.lastBlob = null;
  state.totalSegments = 0;

  state.currentWs.onopen = () => {
    const payload = {
      text,
      model: state.selectedModel,
      voice,
      speed: Number(speed),
      format: 'pcm_s16le',
      binary: false,
      token: state.token
    };
    if (promptAudio) {
      payload.prompt_audio = promptAudio;
    }
    state.currentWs.send(JSON.stringify(payload));
  };

  state.currentWs.onmessage = event => {
    if (typeof event.data !== 'string') return;
    const msg = JSON.parse(event.data);
    if (msg.request_id) {
      state.currentRequestId = msg.request_id;
    }
    if (msg.type === 'started') {
      state.totalSegments = msg.segments || 0;
      setProgress(`流式合成开始，共 ${state.totalSegments} 段`);
    } else if (msg.type === 'audio') {
      const doneCount = msg.index + 1;
      const totalText = state.totalSegments && doneCount <= state.totalSegments ? ` / ${state.totalSegments}` : '';
      setProgress(`已接收 ${doneCount}${totalText} 段`);
      state.currentPlayer.enqueuePCM(msg.data, msg.sample_rate, msg.channels);
    } else if (msg.type === 'done') {
      state.lastBlob = state.currentPlayer.buildWavBlob();
      if (state.lastBlob) {
        els.audio.src = URL.createObjectURL(state.lastBlob);
      }
      setProgress(`合成完成，共 ${msg.total_segments || state.totalSegments} 段`);
      cleanupWs(false);
    } else if (msg.type === 'cancelled') {
      setProgress('已停止', true);
      cleanupWs(false);
    } else if (msg.type === 'error' || msg.type === 'segment_error') {
      setProgress(msg.message || '流式合成失败', true);
      cleanupWs(true);
    }
  };

  state.currentWs.onerror = () => {
    setProgress('WebSocket 连接失败', true);
    cleanupWs(true);
  };

  state.currentWs.onclose = () => {
    cleanupWs(false);
  };
}

function cleanupWs(hadError) {
  if (state.currentWs) {
    state.currentWs.onclose = null;
    try {
      state.currentWs.close();
    } catch (_) {
      // already closed
    }
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
    // audio element may be empty
  }
  if (state.currentAbort) {
    state.currentAbort.abort();
  }
  if (state.currentWs?.readyState === WebSocket.OPEN) {
    state.currentWs.send(JSON.stringify({ type: 'cancel' }));
  }
  if (state.currentRequestId) {
    apiFetch(`/v1/audio/requests/${state.currentRequestId}/cancel`, { method: 'POST' }).catch(() => {});
  }
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
    const text = els.text.value.trim();
    if (!text) {
      setProgress('请输入文本', true);
      return;
    }
    if (!ensureAuthToken()) {
      return;
    }
    state.selectedVoice = els.voice.value;
    addRecent(state.selectedVoice);
    renderVoices();
    if (state.currentWs || state.currentAbort) {
      await stopCurrent();
    }
    if (els.streamToggle.checked) {
      await synthesizeStream(text, state.selectedVoice, els.speed.value);
    } else {
      synthesizeHttp(text, state.selectedVoice, els.speed.value, true);
    }
  });

  els.previewBtn.addEventListener('click', () => {
    if (!ensureAuthToken()) {
      return;
    }
    state.selectedVoice = els.voice.value;
    addRecent(state.selectedVoice);
    synthesizeHttp('你好，我是 AngeVoice 当前选中的音色预览。', state.selectedVoice, els.speed.value, true);
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
    renderVoices();
  });
  els.voiceSearch.addEventListener('input', renderVoices);
  els.promptAudio?.addEventListener('change', () => {
    setPromptAudioFile(els.promptAudio.files?.[0] || null);
  });
  els.clearPromptAudio?.addEventListener('click', () => {
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
