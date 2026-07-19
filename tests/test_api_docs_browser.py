from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_api_docs_hermetic_node_dom_browser_behavior_contract() -> None:
    script = r'''
import { createDocsPage } from "./src/kokoro_tts/static/docs/docs.js";
import { messages as zh } from "./src/kokoro_tts/static/locale/docs/messages.zh-cn.js";
import { messages as en } from "./src/kokoro_tts/static/locale/docs/messages.en.js";

class TextNode {
  constructor(value, ownerDocument) { this.value = value; this.ownerDocument = ownerDocument; this.parentElement = null; }
  get textContent() { return this.value; }
  set textContent(value) { this.value = value; }
}

class Element {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName.toLowerCase(); this.ownerDocument = ownerDocument; this.children = [];
    this.dataset = {}; this.listeners = new Map(); this.parentElement = null; this._text = '';
  }
  get textContent() { return this.children.length ? this.children.map(child => child.textContent).join('') : this._text; }
  set textContent(value) { this.children = []; this._text = String(value); }
  append(...nodes) { nodes.forEach(node => { node.parentElement = this; this.children.push(node); }); }
  replaceChildren(...nodes) { this.children = []; this._text = ''; this.append(...nodes); }
  setAttribute(name, value) { this[name] = String(value); }
  addEventListener(type, listener) { const items = this.listeners.get(type) || []; items.push(listener); this.listeners.set(type, items); }
  querySelector(selector) { return this._walk(node => node.tagName === selector); }
  closest(selector) { return selector === 'button[data-copy-id]' && this.tagName === 'button' && this.dataset.copyId ? this : null; }
  contains(node) { return node === this || this.children.some(child => child instanceof Element && child.contains(node)); }
  _walk(predicate) { for (const child of this.children) { if (child instanceof Element && predicate(child)) return child; const found = child instanceof Element && child._walk(predicate); if (found) return found; } return null; }
}

class Document {
  constructor() { this.elements = new Map(); this.listeners = new Map(); this.documentElement = new Element('html', this); this.title = ''; }
  createElement(tag) { return new Element(tag, this); }
  createTextNode(value) { return new TextNode(value, this); }
  getElementById(id) { return this.elements.get(id) || null; }
  addEventListener(type, listener) { const items = this.listeners.get(type) || []; items.push(listener); this.listeners.set(type, items); }
  dispatch(type) { (this.listeners.get(type) || []).forEach(listener => listener({ type })); }
  register(id, node) { node.id = id; this.elements.set(id, node); return node; }
}

function descendants(node, predicate, results = []) {
  if (predicate(node)) results.push(node);
  node.children?.forEach(child => descendants(child, predicate, results));
  return results;
}

function buildDocument(authRequired) {
  const documentRef = new Document();
  documentRef.register('docs-content', documentRef.createElement('div'));
  documentRef.register('docs-nav', documentRef.createElement('nav'));
  documentRef.register('auth-pill', documentRef.createElement('span'));
  documentRef.register('docs-hero-description', documentRef.createElement('p'));
  const bootstrap = documentRef.register('angevoice-docs-bootstrap', documentRef.createElement('script'));
  bootstrap.textContent = JSON.stringify({ authRequired });
  return documentRef;
}

const storage = new Map([['angevoice.locale.v1', 'en']]);
let locale = storage.get('angevoice.locale.v1') || 'zh-CN';
const timers = [];
const writes = [];
let rejectCopy = false;
const clipboard = { writeText: async value => { if (rejectCopy) throw new Error('denied'); writes.push(value); } };
const documentRef = buildDocument(true);
const translateText = key => (locale === 'en' ? en : zh)[key] || key;
const page = createDocsPage({
  documentRef,
  clipboard,
  getLocale: () => locale,
  translateText,
  initializeLocale: () => {},
  schedule: callback => timers.push(callback),
});

globalThis.fetch = () => { throw new Error('Docs rendering must not fetch'); };
page.initialize();
page.initialize();
const root = documentRef.getElementById('docs-content');
const buttons = () => descendants(root, node => node.tagName === 'button' && node.dataset.copyId);
const articles = () => descendants(root, node => node.tagName === 'article');
if (documentRef.title !== 'AngeVoice API Docs' || documentRef.documentElement.lang !== 'en') throw new Error('saved en locale was not restored');
if (articles().length !== 9 || buttons().length !== 14 || documentRef.getElementById('docs-nav').children.length !== 9) throw new Error('Docs structure is incomplete');
if (documentRef.getElementById('auth-pill').textContent !== en['docs.auth.required']) throw new Error('authRequired=true copy is wrong');
if ((root.listeners.get('click') || []).length !== 1) throw new Error('delegated listener was bound more than once');
if (!descendants(root, node => node.tagName === 'code').length || !descendants(root, node => node.tagName === 'strong').length) throw new Error('inline semantics were not rendered');
const tableCodes = descendants(root, node => node.tagName === 'table').flatMap(table => descendants(table, node => node.tagName === 'code').map(node => node.textContent));
for (const literal of ['kokoro', '.pt', 'prompt_audio.data', 'Junhao', 'FFMPEG_DISABLED']) {
  if (!tableCodes.includes(literal)) throw new Error(`table inline code is missing ${literal}`);
}
const modelTable = descendants(root, node => node.tagName === 'table').find(table => table.textContent.includes(en['docs.models.kokoro.use']));
if (!modelTable || !descendants(modelTable, node => node.tagName === 'td' && node.textContent === en['docs.models.kokoro.use']).length) throw new Error('ordinary table explanation was not preserved as text');

const first = buttons()[0];
const firstCode = first.parentElement.querySelector('code').textContent;
await page.copy(first);
if (writes.at(-1) !== firstCode || buttons()[0].textContent !== en['docs.copy.success']) throw new Error('copy success did not render current code');
const staleTimer = timers.shift();
await page.copy(buttons()[0]);
staleTimer();
if (buttons()[0].textContent !== en['docs.copy.success']) throw new Error('stale timer overwrote newer feedback');
timers.shift()();
if (buttons()[0].textContent !== en['docs.copy.idle']) throw new Error('latest timer did not reset feedback');

rejectCopy = true;
await page.copy(buttons()[1]);
if (buttons()[1].textContent !== en['docs.copy.failure'] || buttons()[0].textContent !== en['docs.copy.idle']) throw new Error('copy states are not independent');
rejectCopy = false;

locale = 'zh-CN'; storage.set('angevoice.locale.v1', locale); documentRef.dispatch('angevoice:locale-changed');
if (documentRef.title !== zh['docs.page.title'] || documentRef.documentElement.lang !== 'zh-CN') throw new Error('en to zh switch failed');
locale = 'en'; storage.set('angevoice.locale.v1', locale); documentRef.dispatch('angevoice:locale-changed');
if (documentRef.title !== en['docs.page.title'] || storage.size !== 1 || !storage.has('angevoice.locale.v1')) throw new Error('zh to en switch changed storage contract');

const openDocument = buildDocument(false);
const openPage = createDocsPage({ documentRef: openDocument, clipboard, getLocale: () => 'zh-CN', translateText: key => zh[key] || key, initializeLocale: () => {}, schedule: () => {} });
openPage.initialize();
if (openDocument.getElementById('auth-pill').textContent !== zh['docs.auth.open']) throw new Error('authRequired=false copy is wrong');
'''
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
