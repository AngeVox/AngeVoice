export function modelNeedsWake(model) {
  return Boolean(
    model &&
    model.available !== false &&
    (model.loaded === false || model.idle_unloaded === true)
  );
}

export function modelParameterSchema(model) {
  return Array.isArray(model?.parameter_schema) ? model.parameter_schema : [];
}

export function modelRequiresPromptAudio(model) {
  return Boolean(model?.requires_prompt_audio);
}

export function modelRequiresPromptText(model) {
  return Boolean(model?.requires_prompt_text);
}

export function modelSupportsVoiceClone(model) {
  const modes = Array.isArray(model?.modes) ? model.modes : [];
  return Boolean(
    model?.voice_clone_supported ||
    modes.includes('voice_clone') ||
    model?.backend === 'moss-tts-nano-onnx' ||
    String(model?.id || '').startsWith('moss')
  );
}
