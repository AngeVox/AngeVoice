function requireFunction(value, name) {
  if (typeof value !== 'function') throw new TypeError(`${name} must be a function`);
  return value;
}

export function createAudioOutputController({
  element,
  createObjectURL,
  revokeObjectURL,
  triggerDownload,
  schedule,
  cancelSchedule,
  callbacks = {},
} = {}) {
  if (!element || typeof element.addEventListener !== 'function' || typeof element.removeEventListener !== 'function') {
    throw new TypeError('element must support media events');
  }
  const createUrl = requireFunction(createObjectURL, 'createObjectURL');
  const revokeUrl = requireFunction(revokeObjectURL, 'revokeObjectURL');
  const trigger = requireFunction(triggerDownload, 'triggerDownload');
  const scheduleCleanup = requireFunction(schedule, 'schedule');
  const cancelCleanup = requireFunction(cancelSchedule, 'cancelSchedule');
  const onStateChange = callbacks.onStateChange || (() => {});
  const onAutoplayRejected = callbacks.onAutoplayRejected || (() => {});

  let generation = 0;
  let sourceBlob = null;
  let availableBlob = null;
  let persistentUrl = '';
  let playing = false;
  let disposed = false;
  const liveUrls = new Set();
  const downloadTimers = new Map();

  const snapshot = () => Object.freeze({
    blob: sourceBlob,
    downloadableBlob: availableBlob,
    playing,
    hasSource: Boolean(persistentUrl),
  });

  const notify = () => {
    if (!disposed) onStateChange(snapshot());
  };

  const setPlaying = value => {
    const next = Boolean(value);
    if (playing === next) return;
    playing = next;
    notify();
  };

  const revokeOnce = url => {
    if (!url || !liveUrls.has(url)) return false;
    revokeUrl(url);
    liveUrls.delete(url);
    return true;
  };

  const syncPlayingFromElement = () => {
    if (disposed) return;
    setPlaying(!element.paused && !element.ended);
  };

  const nativeListeners = Object.freeze({
    play: syncPlayingFromElement,
    pause: syncPlayingFromElement,
    ended: syncPlayingFromElement,
  });
  Object.entries(nativeListeners).forEach(([name, listener]) => element.addEventListener(name, listener));

  const controller = {
    beginResult() {
      if (disposed) return { status: 'disposed' };
      generation += 1;
      availableBlob = null;
      notify();
      return { status: 'begun', generation };
    },

    setBlob(blob, { autoplay = false } = {}) {
      if (disposed) return { status: 'disposed', autoplayCompletion: Promise.resolve('disposed') };
      if (!blob) throw new TypeError('blob is required');

      const operationGeneration = ++generation;
      const nextUrl = createUrl(blob);
      liveUrls.add(nextUrl);
      const previousUrl = persistentUrl;
      try {
        element.src = nextUrl;
      } catch (error) {
        revokeOnce(nextUrl);
        throw error;
      }

      persistentUrl = nextUrl;
      sourceBlob = blob;
      availableBlob = blob;
      syncPlayingFromElement();
      notify();
      if (previousUrl && previousUrl !== nextUrl) revokeOnce(previousUrl);

      let autoplayCompletion = Promise.resolve('skipped');
      if (autoplay) {
        try {
          const playResult = element.play();
          syncPlayingFromElement();
          autoplayCompletion = Promise.resolve(playResult).then(
            () => (disposed || generation !== operationGeneration ? 'stale' : 'played'),
            error => {
              if (disposed || generation !== operationGeneration) return 'stale';
              setPlaying(false);
              onAutoplayRejected(error);
              return 'rejected';
            },
          );
        } catch (error) {
          setPlaying(false);
          onAutoplayRejected(error);
          autoplayCompletion = Promise.resolve('rejected');
        }
      }
      return { status: 'set', url: nextUrl, autoplayCompletion };
    },

    stopPlayback({ resetPosition = true } = {}) {
      if (disposed) return { status: 'disposed' };
      try { element.pause(); } catch (_) {}
      if (resetPosition) {
        try { element.currentTime = 0; } catch (_) {}
      }
      setPlaying(false);
      return { status: 'stopped', blob: sourceBlob, url: persistentUrl };
    },

    download({ blob = null, filename = '' } = {}) {
      if (disposed) return { status: 'disposed' };
      const selectedBlob = blob || availableBlob;
      if (!selectedBlob) return { status: 'no_blob' };
      const url = createUrl(selectedBlob);
      liveUrls.add(url);
      let triggerError = null;
      try {
        trigger({ url, filename });
      } catch (error) {
        triggerError = error;
      }

      let cleanupFired = false;
      const cleanup = () => {
        cleanupFired = true;
        downloadTimers.delete(url);
        revokeOnce(url);
      };
      try {
        const timer = scheduleCleanup(cleanup, 500);
        if (!cleanupFired) downloadTimers.set(url, timer);
      } catch (_) {
        cleanup();
      }
      return triggerError
        ? { status: 'trigger_failed', url, error: triggerError }
        : { status: 'scheduled', url };
    },

    dispose() {
      if (disposed) return;
      disposed = true;
      generation += 1;
      Object.entries(nativeListeners).forEach(([name, listener]) => element.removeEventListener(name, listener));
      try { element.pause(); } catch (_) {}
      try { element.currentTime = 0; } catch (_) {}
      try { element.removeAttribute('src'); } catch (_) {
        try { element.src = ''; } catch (_) {}
      }
      try { element.load?.(); } catch (_) {}
      if (persistentUrl) revokeOnce(persistentUrl);
      for (const [url, timer] of [...downloadTimers.entries()]) {
        try { cancelCleanup(timer); } catch (_) {}
        downloadTimers.delete(url);
        revokeOnce(url);
      }
      sourceBlob = null;
      availableBlob = null;
      persistentUrl = '';
      playing = false;
    },

    get blob() { return sourceBlob; },
    get downloadableBlob() { return availableBlob; },
    get playing() { return playing; },
    get hasSource() { return Boolean(persistentUrl); },
    get sourceUrl() { return persistentUrl; },
    get disposed() { return disposed; },
  };

  return Object.freeze(controller);
}
