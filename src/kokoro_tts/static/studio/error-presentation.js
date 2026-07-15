function requiredFunction(value, name) {
  if (typeof value !== 'function') {
    throw new TypeError(`${name} must be a function`);
  }
  return value;
}

function record(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value
    : null;
}

function errorCode(payload) {
  const root = record(payload);
  if (!root) return '';
  const detail = record(root.detail);
  return root.code || root.error_code || detail?.code || '';
}

function backendMessage(payload) {
  const root = record(payload);
  if (!root) return '';
  const detail = record(root.detail);
  const candidates = [
    root.message,
    detail?.message,
    typeof root.detail === 'string' ? root.detail : '',
    root.error,
  ];
  return candidates.find(value => typeof value === 'string' && value.length > 0) || '';
}

function presentation(value, source, code, message, rawBackend) {
  return Object.freeze({
    value,
    source,
    code,
    backendMessage: message,
    rawBackend,
  });
}

export function createErrorPresentationPolicy({
  resolveKnownCode,
  isRawBackendError,
} = {}) {
  const resolveCode = requiredFunction(resolveKnownCode, 'resolveKnownCode');
  const detectsRawBackendError = requiredFunction(isRawBackendError, 'isRawBackendError');

  const present = (payload, {
    fallback,
    rawFallback = fallback,
    fallbackSource = 'fallback',
  } = {}) => {
    const code = errorCode(payload);
    const message = backendMessage(payload);
    const rawBackend = Boolean(message && detectsRawBackendError(message));
    const known = code ? resolveCode(code) : undefined;
    if (known !== undefined && known !== null) {
      return presentation(known, 'known_code', code, message, rawBackend);
    }
    if (rawBackend) {
      return presentation(rawFallback, 'raw_backend_fallback', code, message, true);
    }
    if (message) {
      return presentation(message, 'backend_message', code, message, false);
    }
    return presentation(fallback, fallbackSource, code, '', false);
  };

  const readResponseError = async (response, {
    fallback,
    rawFallback = fallback,
  } = {}) => {
    const statusText = typeof response?.statusText === 'string' ? response.statusText : '';
    const transportFallback = statusText || fallback;
    const fallbackSource = statusText ? 'transport_status' : 'fallback';
    let payload;
    try {
      payload = await response.json();
    } catch (_) {
      return presentation(transportFallback, fallbackSource, '', '', false);
    }
    return present(payload, {
      fallback: transportFallback,
      rawFallback,
      fallbackSource,
    });
  };

  return Object.freeze({ present, readResponseError });
}
