export function builtinVoiceKindKey(voice) {
  const value = String(voice ?? '');
  if (value.startsWith('zf_')) return 'voices.female_zh';
  if (value.startsWith('zm_')) return 'voices.male_zh';
  if (/^[ab]f_/.test(value)) return 'studio.voices.female_en';
  if (/^[ab]m_/.test(value)) return 'studio.voices.male_en';
  return 'studio.voices.other';
}

export function builtinVoiceKind(voice, translate) {
  if (typeof translate !== 'function') {
    throw new TypeError('A translation function is required for voice presentation');
  }
  return translate(builtinVoiceKindKey(voice));
}
