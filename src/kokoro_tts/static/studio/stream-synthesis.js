const CONNECTING = 0;
const OPEN = 1;

function requiredFunction(value, name) {
  if (typeof value !== 'function') {
    throw new TypeError(`stream synthesis dependency ${name} must be a function`);
  }
  return value;
}

function immutableSnapshot(source) {
  if (!source || typeof source !== 'object') {
    throw new TypeError('stream synthesis snapshot must be an object');
  }
  return Object.freeze({
    text: String(source.text || ''),
    model: String(source.model || ''),
    voice: String(source.voice || ''),
    speed: Number(source.speed),
    textNormalization: String(source.textNormalization || 'default'),
    token: String(source.token || ''),
    engineParams: Object.freeze({ ...(source.engineParams || {}) }),
    promptAudioFile: source.promptAudioFile || null,
    promptText: String(source.promptText || '').trim(),
    supportsVoiceClone: Boolean(source.supportsVoiceClone),
    supportsProfiles: Boolean(source.supportsProfiles),
    requiresPromptText: Boolean(source.requiresPromptText),
    modelId: String(source.modelId || source.model || ''),
    prebufferSeconds: Number(source.prebufferSeconds) || 0.25,
  });
}

function isolateSocket(socket) {
  if (!socket) return;
  socket.onopen = null;
  socket.onmessage = null;
  socket.onerror = null;
  socket.onclose = null;
}

function closeSocket(socket) {
  try {
    socket.close();
  } catch (_) {
    // The injected socket may already be closed.
  }
}

export function createStreamSynthesisController({
  createSocket,
  readPromptAudio,
  cancelRequest,
  createPlayer,
  callbacks,
} = {}) {
  const socketFactory = requiredFunction(createSocket, 'createSocket');
  const promptReader = requiredFunction(readPromptAudio, 'readPromptAudio');
  const requestCanceller = requiredFunction(cancelRequest, 'cancelRequest');
  const playerFactory = requiredFunction(createPlayer, 'createPlayer');
  if (!callbacks || typeof callbacks !== 'object') {
    throw new TypeError('stream synthesis dependency callbacks must be an object');
  }

  const onBusyChange = requiredFunction(callbacks.onBusyChange, 'callbacks.onBusyChange');
  const onProgress = requiredFunction(callbacks.onProgress, 'callbacks.onProgress');
  const onOutputBegin = requiredFunction(callbacks.onOutputBegin, 'callbacks.onOutputBegin');
  const onBlob = requiredFunction(callbacks.onBlob, 'callbacks.onBlob');
  const onServerError = requiredFunction(callbacks.onServerError, 'callbacks.onServerError');
  const onPlaybackError = requiredFunction(callbacks.onPlaybackError, 'callbacks.onPlaybackError');
  const onSocketError = requiredFunction(callbacks.onSocketError, 'callbacks.onSocketError');
  const onPromptReadError = requiredFunction(callbacks.onPromptReadError, 'callbacks.onPromptReadError');
  const onSessionInvalid = requiredFunction(callbacks.onSessionInvalid, 'callbacks.onSessionInvalid');
  const onRefresh = requiredFunction(callbacks.onRefresh, 'callbacks.onRefresh');
  const onStateChange = requiredFunction(callbacks.onStateChange, 'callbacks.onStateChange');

  let generation = 0;
  let current = null;
  let player = null;
  let busy = false;
  let disposed = false;
  let terminalReceived = false;
  let totalSegments = 0;
  let totalAudioChunks = 0;

  const setBusy = value => {
    const next = Boolean(value);
    if (busy === next) return;
    busy = next;
    onBusyChange(next);
  };

  const emit = (key, params = null, options = {}) => {
    onProgress(Object.freeze({
      key,
      params: params ? Object.freeze({ ...params }) : null,
    }), options);
  };

  const isCurrent = operation => (
    !disposed
    && current === operation
    && generation === operation.generation
    && !operation.cleaned
  );

  const cancelRest = (operation, refreshGeneration = null) => {
    if (!operation.requestId || operation.restCancelSent) {
      return Promise.resolve(null);
    }
    operation.restCancelSent = true;
    let result;
    try {
      result = requestCanceller(operation.requestId);
    } catch (_) {
      return Promise.resolve(null);
    }
    return Promise.resolve(result).then(value => {
      if (
        refreshGeneration !== null
        && !disposed
        && generation === refreshGeneration
        && current === null
      ) {
        onRefresh();
      }
      return value;
    }).catch(() => null);
  };

  const cancelSocket = operation => {
    const socket = operation.socket;
    if (!socket) return;
    isolateSocket(socket);
    let cancelSent = false;
    const sendCancelAndClose = () => {
      if (cancelSent) return;
      cancelSent = true;
      try {
        socket.send(JSON.stringify({ type: 'cancel' }));
      } catch (_) {
        // A concurrently closed socket needs no further action.
      }
      closeSocket(socket);
      socket.onopen = null;
    };
    if (socket.readyState === OPEN) {
      sendCancelAndClose();
    } else if (socket.readyState === CONNECTING) {
      socket.onopen = sendCancelAndClose;
    }
  };

  const detachOperation = (operation, { refreshGeneration = null } = {}) => {
    if (!operation || operation.cleaned) return Promise.resolve(null);
    operation.cleaned = true;
    operation.player?.stop();
    const completion = cancelRest(operation, refreshGeneration);
    cancelSocket(operation);
    if (current === operation) current = null;
    onStateChange();
    return completion;
  };

  const cleanup = (operation, hadError) => {
    if (!isCurrent(operation)) return false;
    operation.cleaned = true;
    isolateSocket(operation.socket);
    closeSocket(operation.socket);
    current = null;
    setBusy(false);
    onStateChange();
    if (!hadError) onRefresh();
    return true;
  };

  const bindSocket = operation => {
    const { socket, snapshot, promptAudio } = operation;

    socket.onopen = () => {
      if (!isCurrent(operation)) return;
      const payload = {
        text: snapshot.text,
        model: snapshot.model,
        voice: snapshot.voice,
        speed: snapshot.speed,
        format: 'pcm_s16le',
        binary: false,
        text_normalization: snapshot.textNormalization,
        token: snapshot.token,
      };
      if (Object.keys(snapshot.engineParams).length) payload.engine_params = snapshot.engineParams;
      if (promptAudio) payload.prompt_audio = promptAudio;
      if (snapshot.requiresPromptText && !snapshot.voice && promptAudio) {
        payload.prompt_text = snapshot.promptText;
      }
      try {
        socket.send(JSON.stringify(payload));
      } catch (error) {
        onSocketError(error);
        cleanup(operation, true);
      }
    };

    socket.onmessage = event => {
      if (!isCurrent(operation) || typeof event.data !== 'string') return;
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_) {
        emit('studio.stream.invalid_message', null, { isError: true });
        cleanup(operation, true);
        return;
      }
      try {
        if (message.request_id) operation.requestId = message.request_id;
        if (message.type === 'started') {
          totalSegments = message.segments || 0;
          totalAudioChunks = 0;
          const prebuffer = message.recommended_prebuffer_seconds || snapshot.prebufferSeconds;
          operation.player.setPrebuffer(prebuffer);
          emit('studio.stream.started', {
            segments: totalSegments,
            prebuffer: operation.player.prebufferSeconds.toFixed(2),
          }, { kind: 'loading', sticky: true });
        } else if (message.type === 'audio') {
          totalAudioChunks = Number(message.index) + 1;
          operation.player.enqueuePCM(message.data, message.sample_rate, message.channels);
          const params = {
            chunks: totalAudioChunks,
            segments: totalSegments || '-',
            buffered: operation.player.bufferedSeconds().toFixed(2),
          };
          if (operation.player.underrunCount) {
            emit('studio.stream.audio_received_underrun', {
              ...params,
              underruns: operation.player.underrunCount,
            }, { kind: 'loading', sticky: true });
          } else {
            emit('studio.stream.audio_received', params, { kind: 'loading', sticky: true });
          }
        } else if (message.type === 'progress' && message.stage === 'waiting_audio') {
          const elapsed = Number(message.elapsed_seconds || 0);
          if (elapsed) {
            emit('studio.stream.waiting_audio_elapsed', { elapsed: elapsed.toFixed(1) }, { kind: 'loading', sticky: true });
          } else {
            emit('studio.stream.waiting_audio', null, { kind: 'loading', sticky: true });
          }
        } else if (message.type === 'done') {
          terminalReceived = true;
          operation.terminalReceived = true;
          const finalBlob = operation.player.buildWavBlob();
          if (finalBlob) onBlob(finalBlob, { autoplay: false });
          emit('studio.stream.completed', {
            segments: message.total_segments || totalSegments,
            chunks: message.total_audio_chunks || totalAudioChunks,
          });
          cleanup(operation, false);
        } else if (message.type === 'cancelled') {
          terminalReceived = true;
          operation.terminalReceived = true;
          emit('studio.synthesis.stopped', null, { isError: true });
          cleanup(operation, false);
        } else if (message.type === 'error' || message.type === 'segment_error') {
          terminalReceived = true;
          operation.terminalReceived = true;
          onServerError(message);
          cleanup(operation, true);
        }
      } catch (error) {
        onPlaybackError(error);
        cleanup(operation, true);
      }
    };

    socket.onerror = event => {
      if (!isCurrent(operation)) return;
      onSocketError(event);
      cleanup(operation, true);
    };

    socket.onclose = event => {
      if (!isCurrent(operation)) return;
      if (event.code === 1008) {
        onSessionInvalid(event);
        cleanup(operation, true);
        return;
      }
      if (!operation.terminalReceived && operation.player.hasAudio) {
        const partialBlob = operation.player.buildWavBlob();
        if (partialBlob) onBlob(partialBlob, { autoplay: false });
        emit('studio.stream.closed_partial', null, { isError: true, kind: 'warning' });
      }
      cleanup(operation, !operation.terminalReceived);
    };
  };

  const controller = {
    async start(sourceSnapshot) {
      if (disposed) return Object.freeze({ started: false, reason: 'disposed' });
      const snapshot = immutableSnapshot(sourceSnapshot);
      const operationGeneration = ++generation;
      setBusy(true);
      emit(
        snapshot.supportsProfiles
          ? 'studio.stream.connecting_conditioned'
          : 'studio.stream.connecting',
        null,
        { kind: 'loading', sticky: true },
      );

      const previous = current;
      if (previous) void detachOperation(previous);

      let promptAudio = null;
      if (
        snapshot.supportsVoiceClone
        && snapshot.promptAudioFile
        && (!snapshot.supportsProfiles || !snapshot.voice)
      ) {
        emit('studio.stream.reading_reference', null, { kind: 'loading', sticky: true });
        let data;
        try {
          data = await promptReader(snapshot.promptAudioFile);
        } catch (error) {
          if (!disposed && generation === operationGeneration) {
            onPromptReadError(error);
            setBusy(false);
          }
          return Object.freeze({ started: false, reason: 'prompt-read' });
        }
        if (disposed || generation !== operationGeneration) {
          return Object.freeze({ started: false, reason: 'stale' });
        }
        promptAudio = Object.freeze({
          filename: snapshot.promptAudioFile.name || 'prompt.wav',
          mime_type: snapshot.promptAudioFile.type || 'application/octet-stream',
          data,
        });
      }

      if (
        snapshot.requiresPromptText
        && !snapshot.voice
        && promptAudio
        && !snapshot.promptText
      ) {
        emit('studio.stream.prompt_text_required', null, { isError: true });
        setBusy(false);
        return Object.freeze({ started: false, reason: 'prompt-text' });
      }
      if (disposed || generation !== operationGeneration) {
        return Object.freeze({ started: false, reason: 'stale' });
      }

      let socket;
      try {
        socket = socketFactory(snapshot);
      } catch (error) {
        onSocketError(error);
        setBusy(false);
        return Object.freeze({ started: false, reason: 'socket' });
      }
      if (disposed || generation !== operationGeneration) {
        isolateSocket(socket);
        closeSocket(socket);
        return Object.freeze({ started: false, reason: 'stale' });
      }

      try {
        onOutputBegin();
      } catch (error) {
        isolateSocket(socket);
        closeSocket(socket);
        onPlaybackError(error);
        setBusy(false);
        return Object.freeze({ started: false, reason: 'output' });
      }

      const oldPlayer = player;
      if (oldPlayer) oldPlayer.dispose();
      let createdPlayer;
      try {
        createdPlayer = playerFactory({
          onStateChange: () => {
            if (player === createdPlayer && !disposed) onStateChange();
          },
        });
      } catch (error) {
        isolateSocket(socket);
        closeSocket(socket);
        player = null;
        onPlaybackError(error);
        setBusy(false);
        onStateChange();
        return Object.freeze({ started: false, reason: 'player' });
      }
      player = createdPlayer;
      terminalReceived = false;
      totalSegments = 0;
      totalAudioChunks = 0;
      const operation = {
        generation: operationGeneration,
        socket,
        player: createdPlayer,
        snapshot,
        promptAudio,
        requestId: '',
        terminalReceived: false,
        restCancelSent: false,
        cleaned: false,
      };
      current = operation;
      bindSocket(operation);
      onStateChange();
      return Object.freeze({ started: true, generation: operationGeneration });
    },

    stop() {
      if (disposed) return Object.freeze({ stopped: false, completion: Promise.resolve(null) });
      const stopGeneration = ++generation;
      const operation = current;
      const hadWork = Boolean(operation || player?.playing);
      if (player) player.stop();
      const completion = operation
        ? detachOperation(operation, { refreshGeneration: stopGeneration })
        : Promise.resolve(null);
      setBusy(false);
      onStateChange();
      return Object.freeze({ stopped: hadWork, completion });
    },

    retirePlayer() {
      const stopped = current ? controller.stop() : {
        stopped: false,
        completion: Promise.resolve(null),
      };
      const retired = Boolean(player);
      if (player) {
        const retiring = player;
        player = null;
        retiring.dispose();
        onStateChange();
      }
      return Object.freeze({ retired, completion: stopped.completion });
    },

    dispose() {
      if (disposed) return false;
      const operation = current;
      ++generation;
      disposed = true;
      if (operation) void detachOperation(operation);
      if (player) {
        const retiring = player;
        player = null;
        retiring.dispose();
      }
      current = null;
      busy = false;
      onBusyChange(false);
      onStateChange();
      return true;
    },

    get active() { return Boolean(current && !current.cleaned); },
    get requestId() { return current?.requestId || ''; },
    get player() { return player; },
    get busy() { return busy; },
    get terminalReceived() { return terminalReceived; },
    get totalSegments() { return totalSegments; },
    get totalAudioChunks() { return totalAudioChunks; },
    get generation() { return generation; },
    get disposed() { return disposed; },
  };

  return Object.freeze(controller);
}
