import { translate as t } from './common/i18n.js?h=e8cc950b72ef';

function bootstrap() {
  try {
    return JSON.parse(document.getElementById('angevoice-bootstrap')?.textContent || '{}');
  } catch (_) {
    return {};
  }
}

function render() {
  const data = bootstrap();
  const banner = document.getElementById('security-banner');
  const message = document.getElementById('security-banner-message');
  if (!banner) return;
  const active = Boolean(data.adminDefaultCredentialsActive);
  banner.hidden = !active;
  if (active && message) {
    const translated = t('security.default_desc');
    message.textContent = translated === 'security.default_desc'
      ? (data.adminSecurityWarning || translated)
      : translated;
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', render);
} else {
  render();
}
document.addEventListener('angevoice:locale-changed', render);
