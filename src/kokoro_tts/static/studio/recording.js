export const RECORDING_RECOMMENDED_SECONDS = 3;
export const RECORDING_AUTO_STOP_SECONDS = 14.8;

function descriptor(key, params = null) {
  return { key, params };
}

export function encodeRecordedWav(chunks, sampleRate, BlobType = Blob) {
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const writeText = (offset, text) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
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
  return new BlobType([buffer], { type: 'audio/wav' });
}

export function createReferenceRecorderController({
  elements = {},
  environment = {},
  callbacks = {},
} = {}) {
  const env = {
    isSecureContext: environment.isSecureContext ?? (() => Boolean(globalThis.isSecureContext)),
    getUserMedia: environment.getUserMedia ?? (constraints => globalThis.navigator?.mediaDevices?.getUserMedia(constraints)),
    AudioContext: environment.AudioContext ?? globalThis.AudioContext,
    Blob: environment.Blob ?? globalThis.Blob,
    File: environment.File ?? globalThis.File,
    DataTransfer: environment.DataTransfer ?? globalThis.DataTransfer,
    now: environment.now ?? (() => Date.now()),
  };
  const onStatus = callbacks.onStatus ?? (() => {});
  const onProgress = callbacks.onProgress ?? (() => {});
  const onFile = callbacks.onFile ?? (() => {});
  const onTemporaryReference = callbacks.onTemporaryReference ?? (() => {});
  const onLongRecording = callbacks.onLongRecording ?? (() => {});
  const supportsVoiceClone = callbacks.supportsVoiceClone ?? (() => false);
  const supportsProfiles = callbacks.supportsProfiles ?? (() => false);
  const expandProfiles = callbacks.expandProfiles ?? (() => {});
  let recorder = null;
  let startPromise = null;

  function setControls(active, starting = false) {
    if (elements.startButton) elements.startButton.disabled = Boolean(active || starting);
    if (elements.stopButton) elements.stopButton.disabled = !active;
  }

  async function release(target) {
    if (!target) return;
    if (target.processor) target.processor.onaudioprocess = null;
    target.processor?.disconnect();
    target.source?.disconnect();
    target.silentGain?.disconnect();
    target.stream?.getTracks().forEach(track => track.stop());
    try {
      await target.context?.close();
    } catch (_) {
      // AudioContext.close() is allowed to reject when the context is already closed.
    }
  }

  async function stop({ discard = false, stoppedAtLimit = false } = {}) {
    const current = recorder;
    if (!current) return null;
    recorder = null;
    await release(current);
    setControls(false);
    if (discard || !current.chunks.length) {
      onStatus(descriptor('studio.record.cancelled'), false);
      return null;
    }

    const blob = encodeRecordedWav(current.chunks, current.sampleRate, env.Blob);
    const now = env.now();
    const file = new env.File([blob], `angevoice_reference_${now}.wav`, {
      type: 'audio/wav',
      lastModified: now,
    });
    if (supportsProfiles()) onTemporaryReference();
    if (env.DataTransfer && elements.fileInput) {
      try {
        const transfer = new env.DataTransfer();
        transfer.items.add(file);
        elements.fileInput.files = transfer.files;
      } catch (_) {
        // Older browsers can reject programmatic file-list assignment; controller state still owns the File.
      }
    }
    onFile(file);
    const seconds = current.totalFrames / current.sampleRate;
    const completion = stoppedAtLimit
      ? descriptor('studio.record.complete_at_limit', { seconds: seconds.toFixed(1) })
      : descriptor('studio.record.complete', { seconds: seconds.toFixed(1) });
    onStatus(completion, false);
    if (stoppedAtLimit) {
      onProgress(descriptor('studio.record.limit_quality_warning'), false, { kind: 'warning' });
    } else if (seconds > RECORDING_RECOMMENDED_SECONDS) {
      onLongRecording(seconds);
    }
    return file;
  }

  async function startRecording() {
    if (!supportsVoiceClone()) return false;
    if (supportsProfiles()) expandProfiles();
    if (!env.isSecureContext()) {
      onProgress(descriptor('studio.record.insecure_context'), true);
      return false;
    }
    if (typeof env.getUserMedia !== 'function' || typeof env.AudioContext !== 'function') {
      onProgress(descriptor('studio.record.unsupported'), true);
      return false;
    }
    if (recorder) await stop({ discard: true });

    const pending = {};
    setControls(false, true);
    try {
      pending.stream = await env.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      pending.context = new env.AudioContext();
      pending.source = pending.context.createMediaStreamSource(pending.stream);
      pending.processor = pending.context.createScriptProcessor(4096, 1, 1);
      pending.silentGain = pending.context.createGain();
      pending.silentGain.gain.value = 0;
      const session = {
        ...pending,
        chunks: [],
        sampleRate: pending.context.sampleRate,
        totalFrames: 0,
        autoStopping: false,
      };
      recorder = session;
      pending.processor.onaudioprocess = event => {
        if (recorder !== session) return;
        const active = session;
        const samples = new Float32Array(event.inputBuffer.getChannelData(0));
        active.chunks.push(samples);
        active.totalFrames += samples.length;
        const seconds = active.totalFrames / active.sampleRate;
        if (seconds >= RECORDING_AUTO_STOP_SECONDS && !active.autoStopping) {
          active.autoStopping = true;
          onProgress(descriptor('studio.record.limit_reached'), false, { kind: 'warning' });
          void stop({ stoppedAtLimit: true });
          return;
        }
        onStatus(descriptor('studio.record.active', { seconds: seconds.toFixed(1) }), true);
      };
      pending.source.connect(pending.processor);
      pending.processor.connect(pending.silentGain);
      pending.silentGain.connect(pending.context.destination);
      setControls(true);
      onStatus(descriptor('studio.record.active', { seconds: '0.0' }), true);
      return true;
    } catch (error) {
      if (recorder) recorder = null;
      await release(pending);
      setControls(false);
      const denied = error?.name === 'NotAllowedError' || error?.name === 'SecurityError';
      if (denied) {
        onProgress(descriptor('studio.record.permission_denied'), true);
      } else {
        onProgress(descriptor('studio.record.device_failed'), true);
      }
      onStatus(descriptor('studio.record.microphone_unavailable'), false);
      return false;
    }
  }

  function start() {
    if (startPromise) return startPromise;
    const operation = startRecording();
    startPromise = operation;
    void operation.then(
      () => {
        if (startPromise === operation) startPromise = null;
      },
      () => {
        if (startPromise === operation) startPromise = null;
      },
    );
    return operation;
  }

  return Object.freeze({
    start,
    stop,
    discard: () => stop({ discard: true }),
    get active() {
      return Boolean(recorder);
    },
  });
}
