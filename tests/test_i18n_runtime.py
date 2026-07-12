from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src" / "kokoro_tts" / "static" / "common" / "i18n.js"
LOCALE_ROOT = ROOT / "src" / "kokoro_tts" / "static" / "locale"
CATALOG_DOMAINS = ("common", "studio", "admin")
APP = ROOT / "src" / "kokoro_tts" / "static" / "app.js"
ADMIN = ROOT / "src" / "kokoro_tts" / "static" / "admin.js"
SECURITY_NOTICE = ROOT / "src" / "kokoro_tts" / "static" / "security_notice.js"
INDEX = ROOT / "src" / "kokoro_tts" / "templates" / "index.html"
ADMIN_HTML = ROOT / "src" / "kokoro_tts" / "templates" / "admin.html"


def _portable_source_hash(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _runtime_result(*, saved: str = "", language: str = "unknown", ready_state: str = "complete", actions: str) -> dict[str, object]:
    script = f"""
      class FakeFragment {{
        constructor() {{ this.children = []; }}
        append(...nodes) {{ this.children.push(...nodes); }}
      }}

      class FakeNode {{
        constructor(dataset = {{}}) {{
          this.dataset = dataset;
          this.textContent = '';
          this.innerHTML = '';
          this.children = [];
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
        append(...nodes) {{ this.children.push(...nodes); }}
        replaceChildren(...nodes) {{
          this.children = nodes.length === 1 && nodes[0] instanceof FakeFragment
            ? [...nodes[0].children]
            : [...nodes];
        }}
        querySelectorAll(selector) {{
          if (selector !== '[data-i18n-slot]') return [];
          const matches = [];
          const visit = node => {{
            (node.children || []).forEach(child => {{
              if (child.dataset?.i18nSlot) matches.push(child);
              visit(child);
            }});
          }};
          visit(this);
          return matches;
        }}
        setAttribute(name, value) {{ this.attributes[name] = value; }}
        closest(selector) {{ return selector === '[data-locale-menu]' ? this.menu || null : null; }}
        contains(target) {{ return target === this; }}
      }}

      const textNode = new FakeNode({{ i18n: 'top.title' }});
      const placeholderNode = new FakeNode({{ i18nPlaceholder: 'compose.placeholder' }});
      const titleNode = new FakeNode({{ i18nTitle: 'top.theme' }});
      const ariaNode = new FakeNode({{ i18nAriaLabel: 'text_tools.eyebrow' }});
      const autoSlot = new FakeNode({{ i18nSlot: 'auto' }});
      autoSlot.textContent = 'KOKORO_API_KEY=auto';
      const adminSlot = new FakeNode({{ i18nSlot: 'admin', i18n: 'settings.admin_link' }});
      adminSlot.textContent = '管理后台';
      const sessionSlot = new FakeNode({{ i18nSlot: 'session', i18n: 'settings.session_notice' }});
      sessionSlot.textContent = '保存会话';
      const templateNode = new FakeNode({{ i18nTemplate: 'settings.hint' }});
      templateNode.append(autoSlot, adminSlot, sessionSlot);
      const currentNode = new FakeNode();
      const zhChoice = new FakeNode({{ localeChoice: 'zh-CN' }});
      const enChoice = new FakeNode({{ localeChoice: 'en' }});
      const firstMenu = new FakeNode();
      const secondMenu = new FakeNode();
      zhChoice.menu = firstMenu;
      enChoice.menu = firstMenu;
      const selectorNodes = {{
        '[data-i18n-template],[data-i18n],[data-i18n-placeholder],[data-i18n-title],[data-i18n-aria-label]': [templateNode, textNode, adminSlot, sessionSlot, placeholderNode, titleNode, ariaNode],
        '[data-locale-choice]': [zhChoice, enChoice],
        '[data-current-locale]': [currentNode],
        '[data-locale-menu]': [firstMenu, secondMenu]
      }};
      const documentListeners = {{}};
      const dispatched = [];
      const document = {{
        readyState: {json.dumps(ready_state)},
        documentElement: {{ lang: 'zh-CN', dataset: {{}} }},
        createDocumentFragment() {{ return new FakeFragment(); }},
        createTextNode(text) {{ return {{ textContent: text, dataset: {{}}, children: [] }}; }},
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
      const runtime = await import({json.dumps(RUNTIME.as_uri())});
      const fixture = {{
        runtime, storage, storageWrites, dispatched, document, documentListeners,
        FakeNode,
        nodes: {{ textNode, templateNode, autoSlot, adminSlot, sessionSlot, placeholderNode, titleNode, ariaNode, currentNode, zhChoice, enChoice, firstMenu, secondMenu }}
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
        "renderTranslationTemplate",
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


def test_default_restore_alias_and_private_catalog_contracts() -> None:
    default = _runtime_result(actions="console.log(JSON.stringify({ locale: fixture.runtime.getCurrentLocale() }));")
    restored = _runtime_result(saved="en", actions="console.log(JSON.stringify({ locale: fixture.runtime.getCurrentLocale() }));")
    aliases = _runtime_result(
        actions="""
          const values = ['zh', 'zh-cn', 'zh-CN', 'en', 'en-us', 'en-US', 'unknown'];
          const normalized = values.map(value => fixture.runtime.normalizeLocale(value));
          console.log(JSON.stringify({ normalized, globalCatalogType: typeof window.AngeVoiceLocales }));
        """,
    )
    assert default["locale"] == "zh-CN"
    assert restored["locale"] == "en"
    assert aliases["normalized"] == ["zh-CN", "zh-CN", "zh-CN", "en", "en", "en", "zh-CN"]
    assert aliases["globalCatalogType"] == "undefined"


def test_translate_and_apply_locale_contracts() -> None:
    result = _runtime_result(
        actions="""
          const translations = {
            current: fixture.runtime.translate('top.title', null, 'en'),
            normalizedFallback: fixture.runtime.translate('top.title', null, 'unknown'),
            unknown: fixture.runtime.translate('missing.key', null, 'en'),
            params: fixture.runtime.translate('confirm.force_unload_model', { model: 'kokoro' }, 'en')
          };
          fixture.runtime.applyLocale('en-US');
          const n = fixture.nodes;
          console.log(JSON.stringify({
            translations,
            stored: fixture.storage.get('angevoice.locale.v1'),
            lang: fixture.document.documentElement.lang,
            datasetLocale: fixture.document.documentElement.dataset.locale,
            text: n.textNode.textContent,
            richText: n.templateNode.children.map(child => child.textContent).join(''),
            richSlots: n.templateNode.children.filter(child => child.dataset?.i18nSlot).map(child => child.dataset.i18nSlot),
            richInnerHTML: n.templateNode.innerHTML,
            placeholder: n.placeholderNode.attributes.placeholder,
            title: n.titleNode.attributes.title,
            ariaLabel: n.titleNode.attributes['aria-label'],
            ariaOnlyLabel: n.ariaNode.attributes['aria-label'],
            ariaOnlyTitle: n.ariaNode.attributes.title || null,
            activeZh: n.zhChoice.classList.values.has('active'),
            activeEn: n.enChoice.classList.values.has('active'),
            currentLabel: n.currentNode.textContent,
            lastEvent: fixture.dispatched.at(-1)
          }));
        """,
    )
    assert result["translations"] == {
        "current": "Chinese TTS Studio",
        "normalizedFallback": "中文 TTS 控制台",
        "unknown": "missing.key",
        "params": "Terminate the model process for kokoro? Running requests will be interrupted.",
    }
    assert result["stored"] == result["lang"] == result["datasetLocale"] == "en"
    assert result["text"] == "Chinese TTS Studio"
    assert result["richText"] == (
        "Production templates can use KOKORO_API_KEY=auto to generate a key on first start. "
        "If Admin is enabled, view or rotate it in Admin. After saving, Studio remembers this browser "
        "with a secure HttpOnly session cookie; clear access here or rotate the API Key to revoke it."
    )
    assert result["richSlots"] == ["auto", "admin", "session"]
    assert result["richInnerHTML"] == ""
    assert result["placeholder"] == "Enter text to synthesize"
    assert result["title"] == result["ariaLabel"] == "Toggle theme"
    assert result["ariaOnlyLabel"] == "Text Preprocessing"
    assert result["ariaOnlyTitle"] is None
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
    assert "window.AngeVoiceLocales" not in source
    assert "const catalogs = Object.freeze(" in source
    assert source.count("window.AngeVoiceI18n =") == 1
    assert "angevoice.locale.v1" in source
    assert "data-i18n-html" not in source
    assert "innerHTML" not in source


def test_rich_translation_templates_fail_closed_for_missing_or_unused_slots() -> None:
    result = _runtime_result(
        actions="""
          const slot = new fixture.FakeNode();
          const host = new fixture.FakeNode();
          let missing = '';
          let unused = '';
          try {
            fixture.runtime.renderTranslationTemplate(host, 'settings.hint', { auto: slot }, 'en');
          } catch (error) {
            missing = String(error.message || error);
          }
          try {
            fixture.runtime.renderTranslationTemplate(host, 'top.title', { extra: slot }, 'en');
          } catch (error) {
            unused = String(error.message || error);
          }
          console.log(JSON.stringify({ missing, unused }));
        """,
    )
    assert result["missing"] == "Missing i18n template slot for settings.hint: admin"
    assert result["unused"] == "Unused i18n template slots for top.title: extra"


def test_catalogs_are_frozen_side_effect_free_native_esm_modules() -> None:
    forbidden = ("window", "document", "localStorage", "sessionStorage", "globalThis")
    catalog_paths = {
        locale: [LOCALE_ROOT / domain / f"messages.{locale}.js" for domain in CATALOG_DOMAINS]
        for locale in ("zh-cn", "en")
    }
    for path in [*catalog_paths["zh-cn"], *catalog_paths["en"]]:
        source = path.read_text(encoding="utf-8")
        assert re.findall(r"\bexport\s+const\s+(\w+)", source) == ["messages"]
        assert "export default" not in source
        assert "export const messages = Object.freeze({" in source
        assert "(function" not in source
        assert "}());" not in source
        assert all(name not in source for name in forbidden)

    script = f"""
      const zhDomains = await Promise.all({json.dumps([path.as_uri() for path in catalog_paths['zh-cn']])}.map(path => import(path)));
      const enDomains = await Promise.all({json.dumps([path.as_uri() for path in catalog_paths['en']])}.map(path => import(path)));
      const zh = Object.assign({{}}, ...zhDomains.map(domain => domain.messages));
      const en = Object.assign({{}}, ...enDomains.map(domain => domain.messages));
      console.log(JSON.stringify({{
        exportsOnlyMessages: [...zhDomains, ...enDomains].every(domain => JSON.stringify(Object.keys(domain)) === '["messages"]'),
        allFrozen: [...zhDomains, ...enDomains].every(domain => Object.isFrozen(domain.messages)),
        zhDomainCounts: zhDomains.map(domain => Object.keys(domain.messages).length),
        enDomainCounts: enDomains.map(domain => Object.keys(domain.messages).length),
        zhCount: Object.keys(zh).length, enCount: Object.keys(en).length,
        sameKeys: JSON.stringify(Object.keys(zh).sort()) === JSON.stringify(Object.keys(en).sort())
      }}));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == {
        "exportsOnlyMessages": True,
        "allFrozen": True,
        "zhDomainCounts": [15, 56, 7],
        "enDomainCounts": [15, 56, 7],
        "zhCount": 78,
        "enCount": 78,
        "sameKeys": True,
    }


def test_consumers_use_relative_imports_and_templates_use_the_asset_manifest() -> None:
    runtime_source = RUNTIME.read_text(encoding="utf-8")
    catalog_imports = re.findall(
        r"""^import \{ messages as (\w+Messages) \} from ['"]\.\./locale/(common|studio|admin)/(messages\.(?:zh-cn|en)\.js)['"];""",
        runtime_source,
        re.MULTILINE,
    )
    assert catalog_imports == [
        ("commonZhCNMessages", "common", "messages.zh-cn.js"),
        ("commonEnMessages", "common", "messages.en.js"),
        ("studioZhCNMessages", "studio", "messages.zh-cn.js"),
        ("studioEnMessages", "studio", "messages.en.js"),
        ("adminZhCNMessages", "admin", "messages.zh-cn.js"),
        ("adminEnMessages", "admin", "messages.en.js"),
    ]
    consumers = (APP, ADMIN, SECURITY_NOTICE)
    for path in consumers:
        source = path.read_text(encoding="utf-8")
        imports = re.findall(
            r"^import \{ ([^}]+) \} from ['\"]\.\/common\/i18n\.js['\"];",
            source,
            re.MULTILINE,
        )
        assert len(imports) == 1, path.name
        assert "translate as t" in imports[0]
        assert "?h=" not in source
        assert "window.AngeVoiceI18n" not in source
        assert "window.AngeVoiceLocaleMessages" not in source

    index = INDEX.read_text(encoding="utf-8")
    admin_html = ADMIN_HTML.read_text(encoding="utf-8")
    entries = {
        APP: (index, "app.js"),
        SECURITY_NOTICE: (index, "security_notice.js"),
        ADMIN: (admin_html, "admin.js"),
    }
    for path, (html, asset) in entries.items():
        marker = f'<script type="module" src="{{{{ asset_url(\'{asset}\') }}}}"></script>'
        assert marker in html, path.name
        assert "defer" not in marker
        assert "async" not in marker

    assert index.count("asset_url('common/i18n.js')") == 1
    assert admin_html.count("asset_url('common/i18n.js')") == 1
    for html in (index, admin_html):
        assert "/static/locale/messages.zh-cn.js" not in html
        assert "/static/locale/messages.en.js" not in html
        assert 'type="importmap"' in html
        assert "asset_import_map_json()" in html

    assert index.index("common/i18n.js") < index.index("security_notice.js") < index.index("app.js")
    assert admin_html.index("common/i18n.js") < admin_html.index("admin.js")


def test_admin_removes_lite_map_and_rerenders_only_locale_dependent_dynamic_regions() -> None:
    source = ADMIN.read_text(encoding="utf-8")
    assert "const messages =" not in source
    assert "labelKey: 'nav.config.text'" in source
    assert "tab.labelKey ? t(tab.labelKey) : tab.label" in source
    assert "function renderRuntimeConfigNote(payload)" in source
    runtime_note = source[source.index("function renderRuntimeConfigNote") : source.index("function renderConfigForms")]
    assert "renderTranslationTemplate(note, 'config.runtime.has_overrides', { count: countNode, path: pathNode })" in runtime_note
    assert "document.createElement('b')" in runtime_note
    assert "document.createElement('code')" in runtime_note
    assert "innerHTML" not in runtime_note
    render_config = source[source.index("function renderConfigForms") : source.index("function renderProfiles")]
    assert "renderRuntimeConfigNote(payload)" in render_config
    listener = re.search(
        r"document\.addEventListener\('angevoice:locale-changed', \(\) => \{(?P<body>.*?)\n\}\);",
        source,
        re.DOTALL,
    )
    assert listener
    body = listener.group("body")
    assert "renderAdminSubnav()" in body
    assert "if (lastData) renderModels(lastData)" in body
    assert "if (lastConfigPayload) renderRuntimeConfigNote(lastConfigPayload)" in body
    assert "renderConfigForms" not in body


def test_security_notice_module_prefers_shared_translation_and_rerenders() -> None:
    script = f"""
      const listeners = {{}};
      const storage = new Map([['angevoice.locale.v1', 'en']]);
      const bootstrap = {{ textContent: JSON.stringify({{
        adminDefaultCredentialsActive: true,
        adminSecurityWarning: '固定中文后端警告'
      }}) }};
      const banner = {{ hidden: true }};
      const message = {{ textContent: '' }};
      globalThis.window = globalThis;
      globalThis.localStorage = {{
        getItem: key => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value)
      }};
      Object.defineProperty(globalThis, 'navigator', {{ value: {{ language: 'zh-CN' }}, configurable: true }});
      globalThis.CustomEvent = class {{ constructor(type, options) {{ this.type = type; this.detail = options.detail; }} }};
      globalThis.document = {{
        readyState: 'complete',
        documentElement: {{ lang: 'zh-CN', dataset: {{}} }},
        querySelectorAll: () => [],
        getElementById(id) {{ return {{ 'angevoice-bootstrap': bootstrap, 'security-banner': banner, 'security-banner-message': message }}[id] || null; }},
        addEventListener(name, callback) {{ (listeners[name] ||= []).push(callback); }},
        dispatchEvent(event) {{ (listeners[event.type] || []).forEach(callback => callback(event)); return true; }}
      }};
      await import({json.dumps(SECURITY_NOTICE.as_uri())});
      const initial = message.textContent;
      window.AngeVoiceI18n.apply('zh-CN');
      console.log(JSON.stringify({{ initial, after: message.textContent, visible: !banner.hidden }}));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == {
        "initial": "The first-run default admin credentials are still active. Change them in Admin Security before exposing this service to untrusted networks.",
        "after": "当前仍在使用首次默认管理员账号密码。请进入管理后台安全页修改后再暴露到不可信网络。",
        "visible": True,
    }
