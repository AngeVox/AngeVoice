import { messages as commonZhCNMessages } from '../locale/common/messages.zh-cn.js';
import { messages as commonEnMessages } from '../locale/common/messages.en.js';
import { messages as studioZhCNMessages } from '../locale/studio/messages.zh-cn.js';
import { messages as studioEnMessages } from '../locale/studio/messages.en.js';
import { messages as adminZhCNMessages } from '../locale/admin/messages.zh-cn.js';
import { messages as adminEnMessages } from '../locale/admin/messages.en.js';

function mergeDomains(locale, domains) {
  const merged = {};
  domains.forEach(domain => {
    Object.entries(domain).forEach(([key, value]) => {
      if (Object.prototype.hasOwnProperty.call(merged, key)) {
        throw new Error(`Duplicate ${locale} i18n key across catalog domains: ${key}`);
      }
      merged[key] = value;
    });
  });
  return Object.freeze(merged);
}

const storageKey = 'angevoice.locale.v1';
const catalogs = Object.freeze({
  'zh-CN': mergeDomains('zh-CN', [commonZhCNMessages, studioZhCNMessages, adminZhCNMessages]),
  en: mergeDomains('en', [commonEnMessages, studioEnMessages, adminEnMessages])
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

function templateSlots(node, slots) {
  const entries = slots
    ? Object.entries(slots)
    : Array.from(node.querySelectorAll('[data-i18n-slot]'), slot => [slot.dataset.i18nSlot, slot]);
  const resolved = new Map();
  entries.forEach(([name, slot]) => {
    if (!name || resolved.has(name)) throw new Error(`Duplicate or unnamed i18n template slot: ${name || '<empty>'}`);
    resolved.set(name, slot);
  });
  return resolved;
}

export function renderTranslationTemplate(node, key, slots = null, locale = null) {
  const owner = node.ownerDocument || document;
  const available = templateSlots(node, slots);
  const used = new Set();
  const fragment = owner.createDocumentFragment();
  const template = translate(key, null, locale || getCurrentLocale());
  const pattern = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;
  let cursor = 0;
  for (const match of template.matchAll(pattern)) {
    const name = match[1];
    if (!available.has(name)) throw new Error(`Missing i18n template slot for ${key}: ${name}`);
    if (used.has(name)) throw new Error(`Repeated i18n template slot for ${key}: ${name}`);
    fragment.append(owner.createTextNode(template.slice(cursor, match.index)), available.get(name));
    used.add(name);
    cursor = match.index + match[0].length;
  }
  fragment.append(owner.createTextNode(template.slice(cursor)));
  const unused = [...available.keys()].filter(name => !used.has(name));
  if (unused.length) throw new Error(`Unused i18n template slots for ${key}: ${unused.join(', ')}`);
  node.replaceChildren(fragment);
}

function applyNode(node, locale) {
  if (node.dataset.i18nTemplate) {
    renderTranslationTemplate(node, node.dataset.i18nTemplate, null, locale);
  } else if (node.dataset.i18n) {
    node.textContent = translate(node.dataset.i18n, null, locale);
  }
  if (node.dataset.i18nPlaceholder) {
    node.setAttribute('placeholder', translate(node.dataset.i18nPlaceholder, null, locale));
  }
  if (node.dataset.i18nTitle) {
    const value = translate(node.dataset.i18nTitle, null, locale);
    node.setAttribute('title', value);
    node.setAttribute('aria-label', value);
  }
  if (node.dataset.i18nAriaLabel) {
    node.setAttribute('aria-label', translate(node.dataset.i18nAriaLabel, null, locale));
  }
}

export function applyLocale(locale) {
  const lang = normalizeLocale(locale);
  localStorage.setItem(storageKey, lang);
  document.documentElement.lang = lang;
  document.documentElement.dataset.locale = lang;
  document.querySelectorAll('[data-i18n-template],[data-i18n],[data-i18n-placeholder],[data-i18n-title],[data-i18n-aria-label]').forEach(node => {
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
