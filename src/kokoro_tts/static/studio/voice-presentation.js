export function builtinVoiceKind(voice) {
  const value = String(voice ?? '');
  if (value.startsWith('zf_')) return '中文女声';
  if (value.startsWith('zm_')) return '中文男声';
  if (/^[ab]f_/.test(value)) return '英文女声';
  if (/^[ab]m_/.test(value)) return '英文男声';
  return '其他音色';
}
