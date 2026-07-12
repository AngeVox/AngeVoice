from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src" / "kokoro_tts" / "static" / "common" / "i18n.js"


def _runtime_result(*, saved: str = "", language: str = "unknown", ready_state: str = "complete", actions: str) -> dict[str, object]:
    script = f"""
      class FakeNode {{
        constructor(dataset = {{}}) {{
          this.dataset = dataset;
          this.textContent = '';
          this.innerHTML = '';
          this.attributes = {{}};
          this.listeners = {{}};
          this.open = false;
          this.classList = {{
            values: new Set(),
            toggle: (name, active) => active ? this.classList.values.add(name) : this.classList.values.delete(name)
          }};
        }}
        addEventListener(name, callback) {{
          (this.listeners[name] ||= []).push(callback);
        }}
        fire(name, event = {{}}) {{
          (this.listeners[name] || []).forEach(callback => callback(event));
        }}
        setAttribute(name, value) {{ this.attributes[name] = value; }}
        closest(selector) {{ return selector === '[data-locale-menu]' ? this.menu || null : null; }}
        contains(target) {{ return target === this; }}
      }}

      const textNode = new FakeNode({{ i18n: 'hello' }});
      const htmlNode = new FakeNode({{ i18nHtml: 'html' }});
      const placeholderNode = new FakeNode({{ i18nPlaceholder: 'placeholder' }});
      const titleNode = new FakeNode({{ i18nTitle: 'title' }});
      const currentNode = new FakeNode();
      const zhChoice = new FakeNode({{ localeChoice: 'zh-CN' }});
      const enChoice = new FakeNode({{ localeChoice: 'en' }});
      const firstMenu = new FakeNode();
      const secondMenu = new FakeNode();
      zhChoice.menu = firstMenu;
      enChoice.menu = firstMenu;
      const selectorNodes = {{
        '[data-i18n],[data-i18n-html],[data-i18n-placeholder],[data-i18n-title]': [textNode, htmlNode, placeholderNode, titleNode],
        '[data-locale-choice]': [zhChoice, enChoice],
        '[data-current-locale]': [currentNode],
        '[data-locale-menu]': [firstMenu, secondMenu]
      }};
      const documentListeners = {{}};
      const dispatched = [];
      const document = {{
        readyState: {json.dumps(ready_state)},
        documentElement: {{ lang: 'zh-CN', dataset: {{}} }},
        querySelectorAll(selector) {{ return selectorNodes[selector] || []; }},
        addEventListener(name, callback, options = {{}}) {{
          (documentListeners[name] ||= []).push({{ callback, once: Boolean(options.once) }});
        }},
        dispatchEvent(event) {{
          dispatched.push({{ type: event.type, detail: event.detail }});
          (documentListeners[event.type] || []).forEach(item => item.callback(event));
          return true;
        }},
        fire(name, event = {{}}) {{
          const listeners = [...(documentListeners[name] || [])];
          listeners.forEach(item => item.callback(event));
          documentListeners[name] = (documentListeners[name] || []).filter(item => !item.once);
        }}
      }};
      const storage = new Map();
      if ({json.dumps(saved)}) storage.set('angevoice.locale.v1', {json.dumps(saved)});
      const storageWrites = [];
      globalThis.window = globalThis;
      globalThis.document = document;
      globalThis.localStorage = {{
        getItem(key) {{ return storage.get(key) || null; }},
        setItem(key, value) {{ storage.set(key, value); storageWrites.push([key, value]); }}
      }};
      Object.defineProperty(globalThis, 'navigator', {{ value: {{ language: {json.dumps(language)} }}, configurable: true }});
      globalThis.CustomEvent = class {{ constructor(type, options) {{ this.type = type; this.detail = options.detail; }} }};
      window.AngeVoiceLocales = {{
        'zh-CN': {{
          'language.current': '简体中文', hello: '你好', html: '<b>中文</b>', placeholder: '中文占位', title: '中文标题',
          'fallback.only': '中文回退', greet: '你好，{{name}}！{{name}}！'
        }},
        en: {{
          'language.current': 'English', hello: 'Hello', html: '<b>English</b>', placeholder: 'English placeholder', title: 'English title',
          greet: 'Hello, {{name}}! {{name}}!'
        }}
      }};

      const runtime = await import({json.dumps(RUNTIME.as_uri())});
      const fixture = {{
        runtime, storage, storageWrites, dispatched, document, documentListeners,
        nodes: {{ textNode, htmlNode, placeholderNode, titleNode, currentNode, zhChoice, enChoice, firstMenu, secondMenu }}
      }};
      {actions}
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_runtime_exports_facade_and_loading_initialization_are_synchronous_and_idempotent() -> None:
    result = _runtime_result(
        ready_state="loading",
        actions="""
          const facadeReady = Boolean(window.AngeVoiceI18n);
          const facadeIdentity = window.AngeVoiceI18n.t === runtime.translate
            && window.AngeVoiceI18n.apply === runtime.applyLocale
            && window.AngeVoiceI18n.locale === runtime.getCurrentLocale;
          runtime.initializeI18n();
          runtime.initializeI18n();
          runtime.bindLocaleControls();
          runtime.bindLocaleControls();
          const beforeReady = {
            events: dispatched.length,
            writes: storageWrites.length,
            domReadyListeners: (documentListeners.DOMContentLoaded || []).length
          };
          document.fire('DOMContentLoaded');
          runtime.initializeI18n();
          const clickEvent = { preventDefault() {}, stopPropagation() {} };
          fixture.nodes.enChoice.fire('click', clickEvent);
          console.log(JSON.stringify({
            exports: Object.keys(runtime).sort(), facadeReady, facadeIdentity, beforeReady,
            domReadyListeners: (documentListeners.DOMContentLoaded || []).length,
            clickListeners: fixture.nodes.enChoice.listeners.click.length,
            toggleListeners: fixture.nodes.firstMenu.listeners.toggle.length,
            documentClickListeners: documentListeners.click.length,
            documentKeydownListeners: documentListeners.keydown.length,
            events: dispatched,
            writes: storageWrites
          }));
        """,
    )
    assert result["exports"] == [
        "applyLocale",
        "bindLocaleControls",
        "getCurrentLocale",
        "initializeI18n",
        "normalizeLocale",
        "translate",
    ]
    assert result["facadeReady"] is True
    assert result["facadeIdentity"] is True
    assert result["beforeReady"] == {"events": 0, "writes": 0, "domReadyListeners": 1}
    assert result["domReadyListeners"] == 0
    assert result["clickListeners"] == 1
    assert result["toggleListeners"] == 1
    assert result["documentClickListeners"] == 1
    assert result["documentKeydownListeners"] == 1
    assert [event["detail"]["locale"] for event in result["events"]] == ["zh-CN", "en"]
    assert [write[1] for write in result["writes"]] == ["zh-CN", "en"]


def test_default_restore_alias_and_unavailable_locale_contracts() -> None:
    default = _runtime_result(actions="console.log(JSON.stringify({ locale: fixture.runtime.getCurrentLocale() }));")
    restored = _runtime_result(saved="en", actions="console.log(JSON.stringify({ locale: fixture.runtime.getCurrentLocale() }));")
    aliases = _runtime_result(
        actions="""
          const values = ['zh', 'zh-cn', 'zh-CN', 'en', 'en-us', 'en-US', 'unknown'];
          const normalized = values.map(value => fixture.runtime.normalizeLocale(value));
          delete window.AngeVoiceLocales.en;
          const unavailable = fixture.runtime.normalizeLocale('en');
          console.log(JSON.stringify({ normalized, unavailable }));
        """,
    )
    assert default["locale"] == "zh-CN"
    assert restored["locale"] == "en"
    assert aliases["normalized"] == ["zh-CN", "zh-CN", "zh-CN", "en", "en", "en", "zh-CN"]
    assert aliases["unavailable"] == "zh-CN"


def test_translate_and_apply_locale_contracts() -> None:
    result = _runtime_result(
        actions="""
          const translations = {
            current: fixture.runtime.translate('hello', null, 'en'),
            fallback: fixture.runtime.translate('fallback.only', null, 'en'),
            unknown: fixture.runtime.translate('missing.key', null, 'en'),
            params: fixture.runtime.translate('greet', { name: 7 }, 'en')
          };
          fixture.runtime.applyLocale('en-US');
          const n = fixture.nodes;
          console.log(JSON.stringify({
            translations,
            stored: fixture.storage.get('angevoice.locale.v1'),
            lang: fixture.document.documentElement.lang,
            datasetLocale: fixture.document.documentElement.dataset.locale,
            text: n.textNode.textContent,
            html: n.htmlNode.innerHTML,
            placeholder: n.placeholderNode.attributes.placeholder,
            title: n.titleNode.attributes.title,
            ariaLabel: n.titleNode.attributes['aria-label'],
            activeZh: n.zhChoice.classList.values.has('active'),
            activeEn: n.enChoice.classList.values.has('active'),
            currentLabel: n.currentNode.textContent,
            lastEvent: fixture.dispatched.at(-1)
          }));
        """,
    )
    assert result["translations"] == {
        "current": "Hello",
        "fallback": "中文回退",
        "unknown": "missing.key",
        "params": "Hello, 7! 7!",
    }
    assert result["stored"] == result["lang"] == result["datasetLocale"] == "en"
    assert result["text"] == "Hello"
    assert result["html"] == "<b>English</b>"
    assert result["placeholder"] == "English placeholder"
    assert result["title"] == result["ariaLabel"] == "English title"
    assert result["activeZh"] is False
    assert result["activeEn"] is True
    assert result["currentLabel"] == "English"
    assert result["lastEvent"] == {"type": "angevoice:locale-changed", "detail": {"locale": "en"}}


def test_runtime_source_has_no_async_readiness_or_second_runtime() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert not re.search(r"\bimport\s*\(", source)
    assert not re.search(r"^\s*await\b", source, re.MULTILINE)
    assert "setTimeout" not in source
    assert "setInterval" not in source
    assert "Promise" not in source
    assert source.count("window.AngeVoiceI18n =") == 1
    assert "angevoice.locale.v1" in source
