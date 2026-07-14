export const REFERENCE_AUDIO_RECOMMENDED_SECONDS = 3;

function descriptor(key, params = null) {
  return { key, params };
}

function sourceKeyPart(value) {
  return encodeURIComponent(String(value ?? ''));
}

function normalizedEngineId(engineId) {
  return String(engineId ?? '').trim().toLowerCase();
}

export function referenceAudioUploadKey({ engineId, file } = {}) {
  if (!file) return '';
  return `upload:${sourceKeyPart(normalizedEngineId(engineId))}:${sourceKeyPart(file.name || 'reference.wav')}:${sourceKeyPart(file.size || 0)}:${sourceKeyPart(file.lastModified || 0)}`;
}

export function referenceAudioProfileKey({ engineId, voiceId, revision = '' } = {}) {
  return `profile:${sourceKeyPart(normalizedEngineId(engineId))}:${sourceKeyPart(voiceId)}:${sourceKeyPart(revision)}`;
}

export async function responseAudioWavBlob(response, BlobType = Blob) {
  const blob = await response.blob();
  if (blob.type === 'audio/wav') return blob;
  return new BlobType([await blob.arrayBuffer()], { type: 'audio/wav' });
}

export function createReferenceAudioPreviewController({
  element = null,
  requests = {},
  environment = {},
  callbacks = {},
} = {}) {
  const injectedSetTimeout = environment.setTimeout;
  const injectedClearTimeout = environment.clearTimeout;
  const env = {
    Blob: environment.Blob ?? globalThis.Blob,
    URL: environment.URL ?? globalThis.URL,
    AbortController: environment.AbortController ?? globalThis.AbortController,
    schedule: (...args) => injectedSetTimeout
      ? Reflect.apply(injectedSetTimeout, undefined, args)
      : globalThis.setTimeout(...args),
    cancelTimer: timer => injectedClearTimeout
      ? Reflect.apply(injectedClearTimeout, undefined, [timer])
      : globalThis.clearTimeout(timer),
  };
  const requestUploaded = requests.uploaded;
  const requestSaved = requests.saved;
  const readResponseError = requests.readError ?? (async response => response.statusText || '');
  const onProgress = callbacks.onProgress ?? (() => {});
  const onDurationWarning = callbacks.onDurationWarning ?? (() => {});

  let activeRequest = null;
  let currentUrl = '';
  let sourceKey = '';
  let loadingKey = '';
  let ready = false;
  let disposed = false;
  const retiredUrls = new Map();

  function revokeUrl(url) {
    if (!url) return;
    env.URL?.revokeObjectURL?.(url);
  }

  function retireUrl(url) {
    if (!url || retiredUrls.has(url)) return;
    const timer = env.schedule(() => {
      retiredUrls.delete(url);
      revokeUrl(url);
    }, 150);
    retiredUrls.set(url, timer);
  }

  function cancelActiveRequest() {
    if (!activeRequest) return;
    activeRequest.abortController?.abort();
    activeRequest = null;
    loadingKey = '';
  }

  function clearMedia() {
    ready = false;
    sourceKey = '';
    if (element) {
      element.pause?.();
      element.removeAttribute?.('src');
      element.hidden = true;
      element.load?.();
    }
    const previousUrl = currentUrl;
    currentUrl = '';
    revokeUrl(previousUrl);
  }

  function clear() {
    cancelActiveRequest();
    clearMedia();
  }

  function replaceBlob(blob, nextSourceKey, { force = false } = {}) {
    if (!element || !blob || disposed) return false;
    if (!force && nextSourceKey && nextSourceKey === sourceKey && element.getAttribute?.('src')) return false;
    const playableBlob = blob.type === 'audio/wav'
      ? blob
      : new env.Blob([blob], { type: 'audio/wav' });
    const previousUrl = currentUrl;
    const nextUrl = env.URL.createObjectURL(playableBlob);
    currentUrl = nextUrl;
    sourceKey = nextSourceKey;
    ready = false;
    element.pause?.();
    element.src = nextUrl;
    element.hidden = false;
    element.load?.();
    if (previousUrl && previousUrl !== nextUrl) retireUrl(previousUrl);
    return true;
  }

  function begin(nextSourceKey, force) {
    if (disposed || !element || !nextSourceKey) return null;
    if (!force && nextSourceKey === sourceKey && element.getAttribute?.('src')) return null;
    if (!force && activeRequest?.sourceKey === nextSourceKey) return null;
    cancelActiveRequest();
    const abortController = typeof env.AbortController === 'function'
      ? new env.AbortController()
      : { signal: undefined, abort() {} };
    const request = { sourceKey: nextSourceKey, abortController };
    activeRequest = request;
    loadingKey = nextSourceKey;
    return request;
  }

  function isCurrent(request) {
    return !disposed && activeRequest === request;
  }

  function finish(request) {
    if (!isCurrent(request)) return false;
    activeRequest = null;
    loadingKey = '';
    return true;
  }

  async function responseError(response) {
    try {
      return String(await readResponseError(response) || '').trim();
    } catch (_) {
      return '';
    }
  }

  async function previewUploaded({ file, key = referenceAudioUploadKey({ file }), force = false } = {}) {
    if (!file || typeof requestUploaded !== 'function') return false;
    const request = begin(key, force);
    if (!request) return false;
    onProgress(descriptor('studio.reference_audio.preparing'), false, { kind: 'loading' });
    try {
      const response = await requestUploaded(file, { signal: request.abortController.signal });
      if (!isCurrent(request)) return false;
      if (!response.ok) throw new Error(await responseError(response));
      const blob = await responseAudioWavBlob(response, env.Blob);
      if (!isCurrent(request)) return false;
      if (!replaceBlob(blob, key, { force })) {
        finish(request);
        return false;
      }
      const duration = Number(response.headers?.get?.('X-AngeVoice-Duration-Seconds'));
      if (!finish(request)) return false;
      if (Number.isFinite(duration) && duration > REFERENCE_AUDIO_RECOMMENDED_SECONDS) {
        onDurationWarning(duration);
      } else {
        onProgress(descriptor('studio.reference_audio.upload_ready'));
      }
      return true;
    } catch (error) {
      if (!isCurrent(request) || error?.name === 'AbortError') return false;
      clearMedia();
      finish(request);
      const message = String(error?.message || '').trim();
      onProgress(
        message
          ? descriptor('studio.reference_audio.upload_failed_detail', { message })
          : descriptor('studio.reference_audio.upload_failed'),
        true,
      );
      return false;
    }
  }

  async function previewSaved({ voiceId, name = voiceId, key, force = false } = {}) {
    if (!voiceId || !key || typeof requestSaved !== 'function') return false;
    const request = begin(key, force);
    if (!request) return false;
    onProgress(descriptor('studio.reference_audio.saved_loading', { name }), false, { kind: 'loading' });
    try {
      const response = await requestSaved(voiceId, { signal: request.abortController.signal });
      if (!isCurrent(request)) return false;
      if (!response.ok) throw new Error(await responseError(response));
      const blob = await responseAudioWavBlob(response, env.Blob);
      if (!isCurrent(request)) return false;
      if (!replaceBlob(blob, key, { force })) {
        finish(request);
        return false;
      }
      if (!finish(request)) return false;
      onProgress(descriptor('studio.reference_audio.saved_ready', { name }));
      return true;
    } catch (error) {
      if (!isCurrent(request) || error?.name === 'AbortError') return false;
      clearMedia();
      finish(request);
      const message = String(error?.message || '').trim();
      onProgress(
        message
          ? descriptor('studio.reference_audio.saved_failed_detail', { message })
          : descriptor('studio.reference_audio.saved_failed'),
        true,
      );
      return false;
    }
  }

  function handleLoadedData() {
    if (!disposed && element?.getAttribute?.('src')) ready = true;
  }

  function handleMediaError() {
    if (disposed || !element?.getAttribute?.('src')) return;
    const activeSource = element.getAttribute('src');
    if (element.currentSrc && element.currentSrc !== activeSource) return;
    const code = String(element.error?.code || 'unknown');
    onProgress(descriptor('studio.reference_audio.media_failed', { code }), true);
  }

  element?.addEventListener?.('loadeddata', handleLoadedData);
  element?.addEventListener?.('error', handleMediaError);

  function dispose() {
    if (disposed) return;
    clear();
    disposed = true;
    element?.removeEventListener?.('loadeddata', handleLoadedData);
    element?.removeEventListener?.('error', handleMediaError);
    retiredUrls.forEach((timer, url) => {
      env.cancelTimer(timer);
      revokeUrl(url);
    });
    retiredUrls.clear();
  }

  return Object.freeze({
    previewUploaded,
    previewSaved,
    clear,
    dispose,
    get sourceKey() {
      return sourceKey;
    },
    get loadingKey() {
      return loadingKey;
    },
    get ready() {
      return ready;
    },
    get active() {
      return Boolean(activeRequest);
    },
  });
}
