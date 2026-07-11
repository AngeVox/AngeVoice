export function modelLabel(model) {
  if (!model) return '未知模型';
  return `${model.name || model.id}`;
}

export function runtimeProviderLabel(model) {
  const provider = String(model?.actual_provider || model?.provider || '').toLowerCase();
  const display = provider === 'cuda_pytorch' || provider === 'cuda' ? 'CUDA'
    : provider === 'cpu_onnx_int8' ? 'CPU ONNX INT8'
      : provider === 'cpu' ? 'CPU' : (provider || '已加载');
  return model?.fallback ? `${display} · 已回退` : display;
}
