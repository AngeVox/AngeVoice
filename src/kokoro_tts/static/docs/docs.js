import { DOCS_CONTENT, DOCS_SHELL_INLINE_CONTENT } from './docs-content.js';
import { getCurrentLocale, initializeI18n, translate } from '../common/i18n.js';

function element(documentRef, tag, className = '') {
  const node = documentRef.createElement(tag);
  if (className) node.className = className;
  return node;
}

function fragmentText(fragment, translateText) {
  return fragment.key ? translateText(fragment.key) : fragment.value;
}

function appendInline(parent, content, translateText) {
  const source = translateText(content.key);
  const marks = content.fragments
    .map(fragment => ({ fragment, value: fragmentText(fragment, translateText) }))
    .filter(({ value }) => value)
    .map(({ fragment, value }) => ({ fragment, value, index: source.indexOf(value) }))
    .filter(({ index }) => index >= 0)
    .sort((left, right) => left.index - right.index);
  let cursor = 0;

  marks.forEach(({ fragment, value, index }) => {
    if (index < cursor) return;
    parent.append(parent.ownerDocument.createTextNode(source.slice(cursor, index)));
    const node = fragment.type === 'link'
      ? element(parent.ownerDocument, 'a')
      : element(parent.ownerDocument, fragment.type);
    if (fragment.type === 'link') node.href = fragment.href;
    node.textContent = value;
    parent.append(node);
    cursor = index + value.length;
  });
  parent.append(parent.ownerDocument.createTextNode(source.slice(cursor)));
}

function appendCell(parent, value, translateText) {
  if (typeof value === 'string') {
    const code = element(parent.ownerDocument, 'code');
    code.textContent = value;
    parent.append(code);
    return;
  }
  appendInline(parent, value, translateText);
}

export function createDocsPage({
  documentRef = document,
  clipboard = navigator.clipboard,
  getLocale = getCurrentLocale,
  translateText = translate,
  initializeLocale = initializeI18n,
  schedule = setTimeout,
} = {}) {
  const root = documentRef.getElementById('docs-content');
  const nav = documentRef.getElementById('docs-nav');
  const bootstrap = JSON.parse(documentRef.getElementById('angevoice-docs-bootstrap')?.textContent || '{}');
  const copyStates = new Map();
  let listenerBound = false;
  let initialized = false;

  const text = key => translateText(key);
  const interpolate = template => template.replace(/\{\{(docs\.[\w.]+)\}\}/g, (_, key) => text(key));

  function renderBlock(block) {
    if (block.type === 'paragraph' || block.type === 'heading' || block.type === 'callout') {
      const tag = block.type === 'heading' ? 'h3' : block.type === 'callout' ? 'div' : 'p';
      const className = block.type === 'callout' ? `callout${block.tone === 'warn' ? ' warn' : ''}` : '';
      const node = element(documentRef, tag, className);
      appendInline(node, block.content, text);
      return node;
    }
    if (block.type === 'table') {
      const wrap = element(documentRef, 'div', 'table-wrap');
      const table = element(documentRef, 'table');
      const head = element(documentRef, 'thead');
      const headRow = element(documentRef, 'tr');
      block.headers.forEach(value => {
        const th = element(documentRef, 'th');
        appendCell(th, value, text);
        headRow.append(th);
      });
      head.append(headRow);
      const body = element(documentRef, 'tbody');
      block.rows.forEach(row => {
        const tr = element(documentRef, 'tr');
        row.forEach(value => {
          const td = element(documentRef, 'td');
          appendCell(td, value, text);
          tr.append(td);
        });
        body.append(tr);
      });
      table.append(head, body);
      wrap.append(table);
      return wrap;
    }
    if (block.type === 'codeBlock') {
      const shell = element(documentRef, 'div', 'code-block');
      const state = copyStates.get(block.copyId)?.kind || 'idle';
      const button = element(documentRef, 'button', 'copy-btn');
      button.type = 'button';
      button.dataset.copyId = block.copyId;
      button.setAttribute('aria-label', text(`docs.copy.${state}`));
      button.textContent = text(`docs.copy.${state}`);
      const pre = element(documentRef, 'pre');
      const code = element(documentRef, 'code');
      code.textContent = interpolate(block.template);
      pre.append(code);
      shell.append(button, pre);
      return shell;
    }
    throw new Error(`Unknown Docs block type: ${block.type}`);
  }

  function render() {
    if (!root || !nav) return;
    documentRef.title = text('docs.page.title');
    const locale = getLocale();
    nav.replaceChildren();
    nav.setAttribute('aria-label', text('docs.nav.aria'));
    DOCS_CONTENT.nav.forEach(([id, key]) => {
      const anchor = element(documentRef, 'a');
      anchor.href = `#${id}`;
      anchor.textContent = text(key);
      nav.append(anchor);
    });
    root.replaceChildren();
    DOCS_CONTENT.sections.forEach(section => {
      const article = element(documentRef, 'article', 'doc-card');
      article.id = section.id;
      const heading = element(documentRef, 'h2');
      heading.textContent = text(section.title);
      article.append(heading);
      section.blocks.forEach(block => article.append(renderBlock(block)));
      root.append(article);
    });
    const pill = documentRef.getElementById('auth-pill');
    if (pill) pill.textContent = text(bootstrap.authRequired ? 'docs.auth.required' : 'docs.auth.open');
    Object.entries(DOCS_SHELL_INLINE_CONTENT).forEach(([id, content]) => {
      const node = documentRef.getElementById(id);
      if (!node) return;
      node.replaceChildren();
      appendInline(node, content, text);
    });
    documentRef.documentElement.lang = locale;
  }

  async function copy(button) {
    const copyId = button.dataset.copyId;
    const code = button.parentElement?.querySelector('code')?.textContent || '';
    const previous = copyStates.get(copyId) || { kind: 'idle', generation: 0 };
    const generation = previous.generation + 1;
    try {
      await clipboard.writeText(code);
      copyStates.set(copyId, { kind: 'success', generation });
    } catch (_) {
      copyStates.set(copyId, { kind: 'failure', generation });
    }
    render();
    schedule(() => {
      const current = copyStates.get(copyId);
      if (current?.generation !== generation) return;
      copyStates.set(copyId, { kind: 'idle', generation });
      render();
    }, 1100);
  }

  function bind() {
    if (listenerBound || !root) return;
    listenerBound = true;
    root.addEventListener('click', event => {
      const button = event.target.closest('button[data-copy-id]');
      if (button && root.contains(button)) copy(button);
    });
  }

  function initialize() {
    if (initialized) return;
    initialized = true;
    initializeLocale();
    bind();
    render();
    documentRef.addEventListener('angevoice:locale-changed', render);
  }

  return Object.freeze({ bind, copy, initialize, render });
}

let page;

export function initializeDocsPage() {
  if (!page) page = createDocsPage();
  page.initialize();
  return page;
}

if (typeof document !== 'undefined') initializeDocsPage();
