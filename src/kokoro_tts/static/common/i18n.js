import { messages as zhCNMessages } from '../locale/messages.zh-cn.js?h=4766bfa75faa';
import { messages as enMessages } from '../locale/messages.en.js?h=822654bf71a7';

const storageKey = 'angevoice.locale.v1';
const catalogs = Object.freeze({
  'zh-CN': zhCNMessages,
  en: enMessages
});
const aliases = {
  'zh': 'zh-CN',
  'zh-cn': 'zh-CN',
  'zh-CN': 'zh-CN',
  'en': 'en',
  'en-us': 'en',
  'en-US': 'en'
};

const boundLocaleChoices = new WeakSet();
const boundLocaleMenus = new WeakSet();
let documentListenersBound = false;
let domContentLoadedRegistered = false;
let initialized = false;

function available(locale) {
  return Boolean(catalogs[locale]);
}

export function normalizeLocale(locale) {
  const key = aliases[String(locale || '').trim()] || 'zh-CN';
  return available(key) ? key : 'zh-CN';
}

export function getCurrentLocale() {
  const saved = localStorage.getItem(storageKey);
  return normalizeLocale(saved || navigator.language || 'zh-CN');
}

export function translate(key, params, locale) {
  const lang = normalizeLocale(locale || getCurrentLocale());
  const messages = catalogs[lang] || {};
  const fallback = catalogs['zh-CN'] || {};
  let template = messages[key] || fallback[key] || key;
  Object.keys(params || {}).forEach(name => {
    template = template.replaceAll(`{${name}}`, String(params[name]));
  });
  return template;
}

function applyNode(node, locale) {
  if (node.dataset.i18n) {
    node.textContent = translate(node.dataset.i18n, null, locale);
  }
  if (node.dataset.i18nHtml) {
    node.innerHTML = translate(node.dataset.i18nHtml, null, locale);
  }
  if (node.dataset.i18nPlaceholder) {
    node.setAttribute('placeholder', translate(node.dataset.i18nPlaceholder, null, locale));
  }
  if (node.dataset.i18nTitle) {
    const value = translate(node.dataset.i18nTitle, null, locale);
    node.setAttribute('title', value);
    node.setAttribute('aria-label', value);
  }
}

export function applyLocale(locale) {
  const lang = normalizeLocale(locale);
  localStorage.setItem(storageKey, lang);
  document.documentElement.lang = lang;
  document.documentElement.dataset.locale = lang;
  document.querySelectorAll('[data-i18n],[data-i18n-html],[data-i18n-placeholder],[data-i18n-title]').forEach(node => {
    applyNode(node, lang);
  });
  document.querySelectorAll('[data-locale-choice]').forEach(node => {
    node.classList.toggle('active', node.dataset.localeChoice === lang);
  });
  document.querySelectorAll('[data-current-locale]').forEach(node => {
    node.textContent = translate('language.current', null, lang);
  });
  document.dispatchEvent(new CustomEvent('angevoice:locale-changed', { detail: { locale: lang } }));
}

export function bindLocaleControls() {
  document.querySelectorAll('[data-locale-choice]').forEach(node => {
    if (boundLocaleChoices.has(node)) return;
    boundLocaleChoices.add(node);
    node.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      applyLocale(node.dataset.localeChoice || 'zh-CN');
      const menu = node.closest('[data-locale-menu]');
      if (menu) menu.open = false;
    });
  });
  document.querySelectorAll('[data-locale-menu]').forEach(node => {
    if (boundLocaleMenus.has(node)) return;
    boundLocaleMenus.add(node);
    node.addEventListener('toggle', () => {
      if (node.open) {
        document.querySelectorAll('[data-locale-menu]').forEach(other => {
          if (other !== node) other.open = false;
        });
      }
    });
  });
  if (documentListenersBound) return;
  documentListenersBound = true;
  document.addEventListener('click', event => {
    document.querySelectorAll('[data-locale-menu]').forEach(node => {
      if (node.open && !node.contains(event.target)) {
        node.open = false;
      }
    });
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('[data-locale-menu]').forEach(node => {
      node.open = false;
    });
  });
}

function completeInitialization() {
  if (initialized) return;
  initialized = true;
  bindLocaleControls();
  applyLocale(getCurrentLocale());
}

export function initializeI18n() {
  if (initialized) return;
  if (document.readyState === 'loading') {
    if (!domContentLoadedRegistered) {
      domContentLoadedRegistered = true;
      document.addEventListener('DOMContentLoaded', completeInitialization, { once: true });
    }
    return;
  }
  completeInitialization();
}

window.AngeVoiceI18n = {
  t: translate,
  apply: applyLocale,
  locale: getCurrentLocale
};

initializeI18n();
