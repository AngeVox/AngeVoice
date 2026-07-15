function descriptor(key, params = null) {
  return { key, params };
}

function requireFunction(value, name) {
  if (typeof value !== 'function') {
    throw new TypeError(`${name} must be a function`);
  }
  return value;
}

function decodedResponseError(decoded) {
  if (decoded instanceof Error) return decoded;
  const isPresentation = Boolean(
    decoded
    && typeof decoded === 'object'
    && Object.prototype.hasOwnProperty.call(decoded, 'value')
  );
  const value = isPresentation ? decoded.value : decoded;
  const error = new Error(typeof value === 'string' ? value : '');
  if (isPresentation) {
    Object.defineProperty(error, 'presentation', {
      configurable: false,
      enumerable: false,
      value: decoded,
      writable: false,
    });
  }
  return error;
}

function normalizedSnapshot(snapshot = {}) {
  const engineParams = Object.freeze({ ...(snapshot.engineParams || {}) });
  return Object.freeze({
    model: String(snapshot.model || ''),
    text: String(snapshot.text || '').trim(),
    voice: String(snapshot.voice || ''),
    speed: Number(snapshot.speed),
    textNormalization: String(snapshot.textNormalization || 'default'),
    engineParams,
    promptAudioFile: snapshot.promptAudioFile || null,
    promptText: String(snapshot.promptText || '').trim(),
    supportsVoiceClone: Boolean(snapshot.supportsVoiceClone),
    supportsProfiles: Boolean(snapshot.supportsProfiles),
    requiresPromptText: Boolean(snapshot.requiresPromptText),
    requiresPromptAudio: Boolean(snapshot.requiresPromptAudio),
    autoplay: snapshot.autoplay !== false,
  });
}

function validationDescriptor(snapshot) {
  if (!snapshot.text) {
    return descriptor('studio.compose.text_required');
  }
  const uploadedReference = Boolean(
    snapshot.supportsVoiceClone
    && snapshot.promptAudioFile
    && (!snapshot.supportsProfiles || !snapshot.voice)
  );
  if (uploadedReference && snapshot.requiresPromptText && !snapshot.promptText) {
    return descriptor('studio.synthesis.http.prompt_text_required');
  }
  if (snapshot.requiresPromptAudio && !uploadedReference && !snapshot.voice) {
    return descriptor('studio.synthesis.http.reference_required');
  }
  return null;
}

export function createHttpSynthesisController({
  request,
  cancelRequest,
  readError,
  createRequestId,
  callbacks = {},
  environment = {},
} = {}) {
  const sendRequest = requireFunction(request, 'request');
  const cancel = requireFunction(cancelRequest, 'cancelRequest');
  const decodeError = requireFunction(readError, 'readError');
  const nextRequestId = requireFunction(createRequestId, 'createRequestId');
  const FormDataConstructor = environment.FormData || globalThis.FormData;
  const AbortControllerConstructor = environment.AbortController || globalThis.AbortController;
  if (typeof FormDataConstructor !== 'function') throw new TypeError('FormData is unavailable');
  if (typeof AbortControllerConstructor !== 'function') throw new TypeError('AbortController is unavailable');

  const onBusyChange = callbacks.onBusyChange || (() => {});
  const onStart = callbacks.onStart || (() => {});
  const onProgress = callbacks.onProgress || (() => {});
  const onRequestId = callbacks.onRequestId || (() => {});
  const onAuthRequired = callbacks.onAuthRequired || (() => {});
  const onRequestError = callbacks.onRequestError || (() => {});
  const onBlob = callbacks.onBlob || (() => {});
  const onRefresh = callbacks.onRefresh || (() => {});

  let generation = 0;
  let currentOperation = null;
  let disposed = false;

  const current = operation => (
    !disposed
    && currentOperation === operation
    && operation.generation === generation
  );

  const operationRequestId = operation => operation.serverRequestId || operation.clientRequestId;

  const cancelQuietly = requestId => {
    if (!requestId) return Promise.resolve(null);
    return Promise.resolve().then(() => cancel(requestId)).catch(() => null);
  };

  const retireForReplacement = operation => {
    if (!operation) return;
    if (currentOperation === operation) currentOperation = null;
    operation.abortController.abort();
    void cancelQuietly(operationRequestId(operation));
  };

  const buildFormData = snapshot => {
    const form = new FormDataConstructor();
    form.append('model', snapshot.model);
    form.append('text', snapshot.text);
    form.append('voice', snapshot.voice);
    form.append('speed', snapshot.speed);
    form.append('response_format', 'wav');
    form.append('text_normalization', snapshot.textNormalization);
    Object.entries(snapshot.engineParams).forEach(([key, value]) => {
      if (value !== '' && value !== null && value !== undefined) {
        form.append(key, String(value));
      }
    });
    const uploadedReference = Boolean(
      snapshot.supportsVoiceClone
      && snapshot.promptAudioFile
      && (!snapshot.supportsProfiles || !snapshot.voice)
    );
    if (uploadedReference) {
      form.append('prompt_audio', snapshot.promptAudioFile, snapshot.promptAudioFile.name);
    }
    if (uploadedReference && snapshot.requiresPromptText) {
      form.append('prompt_text', snapshot.promptText);
    }
    return form;
  };

  const controller = {
    validate(snapshot) {
      return validationDescriptor(normalizedSnapshot(snapshot));
    },

    async start(snapshotInput) {
      if (disposed) return { status: 'disposed' };
      const snapshot = normalizedSnapshot(snapshotInput);
      const invalid = validationDescriptor(snapshot);
      if (invalid) {
        onProgress(invalid, true);
        return { status: 'validation_error', descriptor: invalid };
      }

      const previous = currentOperation;
      if (previous) retireForReplacement(previous);

      const operation = {
        generation: ++generation,
        abortController: new AbortControllerConstructor(),
        clientRequestId: String(nextRequestId()),
        serverRequestId: '',
        snapshot,
      };
      currentOperation = operation;
      onBusyChange(true);
      onStart({ requestId: operation.clientRequestId });
      onRequestId(operation.clientRequestId);
      const generatingCopy = snapshot.requiresPromptText
        ? descriptor('studio.synthesis.http.generating_conditioned')
        : descriptor('studio.synthesis.http.generating');
      onProgress(generatingCopy);

      try {
        const response = await sendRequest('/api/tts', {
          method: 'POST',
          body: buildFormData(snapshot),
          headers: { 'X-Client-Request-ID': operation.clientRequestId },
          signal: operation.abortController.signal,
        });
        if (!current(operation)) return { status: 'superseded' };

        operation.serverRequestId = response.headers.get('X-Request-ID') || operation.clientRequestId;
        onRequestId(operation.serverRequestId);
        if (response.status === 401) {
          onAuthRequired(response);
          return { status: 'auth_required', requestId: operation.serverRequestId };
        }
        if (!response.ok) {
          throw decodedResponseError(await decodeError(response));
        }
        const blob = await response.blob();
        if (!current(operation)) return { status: 'superseded' };
        onBlob(blob, { autoplay: snapshot.autoplay, requestId: operation.serverRequestId });
        onProgress(descriptor('studio.synthesis.http.completed'));
        return { status: 'completed', blob, requestId: operation.serverRequestId };
      } catch (error) {
        if (!current(operation)) return { status: 'superseded' };
        if (error?.name === 'AbortError') return { status: 'aborted' };
        onRequestError(error);
        return { status: 'error', error };
      } finally {
        if (current(operation)) {
          currentOperation = null;
          onBusyChange(false);
          onRefresh();
        }
      }
    },

    stop() {
      if (disposed || !currentOperation) return { stopped: false, requestId: '', completion: Promise.resolve(null) };
      const operation = currentOperation;
      const requestId = operationRequestId(operation);
      currentOperation = null;
      const stoppedGeneration = ++generation;
      operation.abortController.abort();
      onBusyChange(false);
      const completion = cancelQuietly(requestId).then(result => {
        if (!disposed && !currentOperation && generation === stoppedGeneration) onRefresh();
        return result;
      });
      return { stopped: true, requestId, completion };
    },

    dispose() {
      if (disposed) return;
      const operation = currentOperation;
      disposed = true;
      currentOperation = null;
      generation += 1;
      if (operation) {
        operation.abortController.abort();
        void cancelQuietly(operationRequestId(operation));
      }
    },

    get active() {
      return !disposed && Boolean(currentOperation);
    },

    get requestId() {
      return currentOperation ? operationRequestId(currentOperation) : '';
    },
  };

  return Object.freeze(controller);
}
