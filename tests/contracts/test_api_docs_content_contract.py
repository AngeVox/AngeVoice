from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "kokoro_tts"
SNAPSHOT = Path(__file__).with_name("data") / "api_docs_content_2_6_7.json"


def _schema() -> dict:
    script = f"""import {{ DOCS_CONTENT, DOCS_DYNAMIC_KEYS, DOCS_SHELL_KEYS, INLINE_FRAGMENT_TYPES, collectDocsTranslationKeys }} from {json.dumps((PACKAGE / 'static/docs/docs-content.js').as_uri())};
const blocks = DOCS_CONTENT.sections.flatMap(section => section.blocks);
const inlineContents = blocks.flatMap(block => block.type === 'table'
  ? [...block.headers, ...block.rows.flat()].filter(value => typeof value === 'object' && value?.key)
  : block.content ? [block.content] : []);
const fragments = inlineContents.flatMap(content => content.fragments.map(fragment => ({{ key: content.key, fragment }})));
console.log(JSON.stringify({{anchors:DOCS_CONTENT.sections.map(section => section.id), copyIds:blocks.filter(block => block.type === 'codeBlock').map(block => block.copyId), contentKeys:[...collectDocsTranslationKeys()].sort(), shellKeys:[...DOCS_SHELL_KEYS].sort(), dynamicKeys:[...DOCS_DYNAMIC_KEYS].sort(), fragmentTypes:fragments.map(item => item.fragment.type), fragments, inlineContentKeys:inlineContents.map(content => content.key), supportedFragmentTypes:[...INLINE_FRAGMENT_TYPES], source:JSON.stringify(DOCS_CONTENT)}}));"""
    return json.loads(subprocess.run(["node", "--input-type=module", "--eval", script], check=True, capture_output=True, text=True).stdout)


def _catalog(locale: str) -> set[str]:
    source = (PACKAGE / f"static/locale/docs/messages.{locale}.js").read_text(encoding="utf-8")
    return set(__import__("re").findall(r"'((?:docs)\.[\w.]+)'\s*:", source))


def _messages(locale: str) -> dict[str, str]:
    script = f"""import {{ messages }} from {json.dumps((PACKAGE / f'static/locale/docs/messages.{locale}.js').as_uri())};
console.log(JSON.stringify(messages));"""
    return json.loads(subprocess.run(["node", "--input-type=module", "--eval", script], check=True, capture_output=True, text=True).stdout)


def test_api_docs_content_shape_and_technical_contract():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    schema = _schema()
    assert schema["anchors"] == snapshot["anchors"]
    assert schema["copyIds"] == snapshot["copy_recipes"]
    assert len(schema["copyIds"]) == len(set(schema["copyIds"])) == 14
    zh_source = (PACKAGE / "static/locale/docs/messages.zh-cn.js").read_text(encoding="utf-8")
    shell_source = (PACKAGE / "templates/api_docs.html").read_text(encoding="utf-8")
    for literal in [item for values in snapshot["technical_literals"].values() for item in values]:
        assert literal in schema["source"] or literal in zh_source or literal in shell_source
    assert set(schema["fragmentTypes"]) <= set(schema["supportedFragmentTypes"])
    assert {"text", "code", "strong", "link"} == set(schema["supportedFragmentTypes"])


def test_docs_catalogs_are_symmetric_and_cover_schema_keys():
    schema = _schema()
    zh, en = _catalog("zh-cn"), _catalog("en")
    assert zh == en
    owned = set(schema["shellKeys"]) | set(schema["dynamicKeys"]) | set(schema["contentKeys"])
    assert owned == zh


def test_inline_fragments_are_present_and_ordered_in_both_docs_catalogs():
    schema = _schema()
    declared = schema["fragments"]
    assert declared
    assert {"docs.models.kokoro.id", "docs.moss_clone.ws.location", "docs.moss_http.field.voice"} <= set(schema["inlineContentKeys"])

    for locale in ("zh-cn", "en"):
        messages = _messages(locale)
        cursors: dict[str, int] = {}
        for item in declared:
            key = item["key"]
            fragment = item["fragment"]
            value = messages[fragment["key"]] if "key" in fragment else fragment["value"]
            index = messages[key].find(value, cursors.get(key, 0))
            assert index >= 0, f"{locale} {key} is missing inline fragment {value!r}"
            cursors[key] = index + len(value)
