const clampPrebuffer = value => Math.max(0, Math.min(12, value));

const ignoreRejection = value => {
  if (value && typeof value.then === 'function') {
    Promise.resolve(value).catch(() => {});
  }
};

export function createStreamPlayer({
  createAudioContext,
  decodeBase64,
  createBlob,
  callbacks = {},
  defaults = {},
} = {}) {
  if (typeof createAudioContext !== 'function') throw new TypeError('createAudioContext is required');
  if (typeof decodeBase64 !== 'function') throw new TypeError('decodeBase64 is required');
  if (typeof createBlob !== 'function') throw new TypeError('createBlob is required');

  const onPlayingChange = typeof callbacks.onPlayingChange === 'function'
    ? callbacks.onPlayingChange
    : () => {};
  let context = null;
  let nextStartTime = 0;
  let activeSources = new Set();
  let pcmChunks = [];
  let sampleRate = Number(defaults.sampleRate) || 24000;
  let channels = Math.max(1, Number(defaults.channels) || 1);
  const configuredPrebuffer = Number(defaults.prebufferSeconds);
  let prebufferSeconds = Number.isFinite(configuredPrebuffer)
    ? clampPrebuffer(configuredPrebuffer)
    : 0.25;
  let audioChunkCount = 0;
  let underrunCount = 0;
  let playing = false;
  let disposed = false;
  let generation = 0;

  const setPlaying = (value, { silent = false } = {}) => {
    const next = Boolean(value);
    if (playing === next) return;
    playing = next;
    if (!silent && !disposed) onPlayingChange(next);
  };

  const initializeContext = (requestedSampleRate, requestedChannels) => {
    generation += 1;
    context = createAudioContext({ sampleRate: requestedSampleRate });
    sampleRate = context.sampleRate;
    channels = Math.max(1, Number(requestedChannels) || 1);
    nextStartTime = context.currentTime + prebufferSeconds;
    pcmChunks = [];
    audioChunkCount = 0;
    underrunCount = 0;
  };

  const closeContext = ownedContext => {
    if (!ownedContext || typeof ownedContext.close !== 'function') return;
    try {
      ignoreRejection(ownedContext.close());
    } catch (_) {
      // Context release is best-effort during teardown.
    }
  };

  const stopSources = ({ silent = false } = {}) => {
    generation += 1;
    const sources = [...activeSources];
    activeSources = new Set();
    sources.forEach(source => {
      try {
        source.stop();
      } catch (_) {
        // The source may already have ended.
      }
    });
    nextStartTime = context ? context.currentTime : 0;
    audioChunkCount = 0;
    setPlaying(false, { silent });
  };

  const player = {
    init(requestedSampleRate = sampleRate, requestedChannels = channels) {
      if (disposed) return false;
      if (context) {
        const previousContext = context;
        stopSources({ silent: true });
        context = null;
        closeContext(previousContext);
      }
      initializeContext(requestedSampleRate, requestedChannels);
      return true;
    },

    setPrebuffer(seconds) {
      if (disposed) return prebufferSeconds;
      const value = Number(seconds);
      if (Number.isFinite(value)) {
        prebufferSeconds = clampPrebuffer(value);
      }
      if (context && audioChunkCount === 0) {
        nextStartTime = Math.max(nextStartTime, context.currentTime + prebufferSeconds);
      }
      return prebufferSeconds;
    },

    enqueuePCM(base64Data, requestedSampleRate = sampleRate, requestedChannels = channels) {
      if (disposed) return null;
      if (!context) {
        player.init(requestedSampleRate, requestedChannels);
      }
      if (context.state === 'suspended') {
        try {
          ignoreRejection(context.resume());
        } catch (_) {
          // Preserve scheduling even when resuming is unavailable.
        }
      }
      channels = Math.max(1, Number(requestedChannels) || 1);
      const bytes = decodeBase64(base64Data);
      pcmChunks.push(bytes);
      const samples = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2);
      const frameCount = Math.floor(samples.length / channels);
      const buffer = context.createBuffer(channels, frameCount, sampleRate);
      for (let channel = 0; channel < channels; channel += 1) {
        const target = buffer.getChannelData(channel);
        for (let frame = 0; frame < frameCount; frame += 1) {
          target[frame] = samples[(frame * channels) + channel] / 32767;
        }
      }

      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      const underrun = audioChunkCount > 0 && nextStartTime <= context.currentTime + 0.02;
      if (underrun) underrunCount += 1;
      const start = Math.max(
        context.currentTime + (audioChunkCount === 0 ? prebufferSeconds : 0),
        nextStartTime,
      );
      source.start(start);
      nextStartTime = start + buffer.duration;
      audioChunkCount += 1;
      activeSources.add(source);
      const sourceGeneration = generation;
      source.onended = () => {
        if (disposed || sourceGeneration !== generation) return;
        activeSources.delete(source);
        if (activeSources.size === 0) setPlaying(false);
      };
      setPlaying(true);
      return source;
    },

    bufferedSeconds() {
      if (!context) return 0;
      return Math.max(0, nextStartTime - context.currentTime);
    },

    buildWavBlob() {
      if (disposed || pcmChunks.length === 0) return null;
      const total = pcmChunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
      const pcm = new Uint8Array(total);
      let offset = 0;
      pcmChunks.forEach(chunk => {
        pcm.set(chunk, offset);
        offset += chunk.byteLength;
      });

      const wav = new ArrayBuffer(44 + pcm.byteLength);
      const view = new DataView(wav);
      const write = (position, text) => {
        for (let index = 0; index < text.length; index += 1) {
          view.setUint8(position + index, text.charCodeAt(index));
        }
      };
      write(0, 'RIFF');
      view.setUint32(4, 36 + pcm.byteLength, true);
      write(8, 'WAVE');
      write(12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, channels, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * channels * 2, true);
      view.setUint16(32, channels * 2, true);
      view.setUint16(34, 16, true);
      write(36, 'data');
      view.setUint32(40, pcm.byteLength, true);
      new Uint8Array(wav, 44).set(pcm);
      return createBlob([wav], { type: 'audio/wav' });
    },

    stop() {
      if (disposed) return false;
      stopSources();
      return true;
    },

    dispose() {
      if (disposed) return false;
      disposed = true;
      stopSources({ silent: true });
      pcmChunks = [];
      const ownedContext = context;
      context = null;
      nextStartTime = 0;
      closeContext(ownedContext);
      return true;
    },

    get playing() { return playing; },
    get hasAudio() { return pcmChunks.length > 0; },
    get pcmChunkCount() { return pcmChunks.length; },
    get audioChunkCount() { return audioChunkCount; },
    get underrunCount() { return underrunCount; },
    get sampleRate() { return sampleRate; },
    get channels() { return channels; },
    get prebufferSeconds() { return prebufferSeconds; },
    get disposed() { return disposed; },
    get generation() { return generation; },
    get activeSourceCount() { return activeSources.size; },
    get hasContext() { return context !== null; },
  };

  return Object.freeze(player);
}
