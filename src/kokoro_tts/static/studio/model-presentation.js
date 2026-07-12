function translated(translate, key, params = null) {
  if (typeof translate !== 'function') {
    throw new TypeError('A translation function is required for model presentation');
  }
  return translate(key, params);
}

export function modelLabel(model, translate) {
  if (!model) return translated(translate, 'studio.model.unknown');
  return `${model.name || model.id}`;
}

export function runtimeProviderLabel(model, translate) {
  const provider = String(model?.actual_provider || model?.provider || '').toLowerCase();
  const display = provider === 'cuda_pytorch' || provider === 'cuda' ? 'CUDA'
    : provider === 'cpu_onnx_int8' ? 'CPU ONNX INT8'
      : provider === 'cpu' ? 'CPU' : (provider || translated(translate, 'studio.model.loaded'));
  return model?.fallback
    ? translated(translate, 'studio.model.fallback', { provider: display })
    : display;
}
