from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from tests.quality.test_i18n_contract import DynamicKeyAllowance, scan_i18n_references


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
APP = PACKAGE_ROOT / "static" / "app.js"
MODULE = PACKAGE_ROOT / "static" / "studio" / "model-presentation.js"
CAPABILITIES_MODULE = PACKAGE_ROOT / "static" / "studio" / "model-capabilities.js"
VOICE_MODULE = PACKAGE_ROOT / "static" / "studio" / "voice-presentation.js"
I18N_MODULE = PACKAGE_ROOT / "static" / "common" / "i18n.js"
INDEX = PACKAGE_ROOT / "templates" / "index.html"


def _portable_source_hash(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _node(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )


def _module_results() -> dict[str, object]:
    cases = [
        ["model-null", None],
        ["model-name", {"id": "fallback-id", "name": "Named model"}],
        ["model-id", {"id": "model-id", "name": ""}],
        ["provider-cuda-pytorch", {"actual_provider": "cuda_pytorch"}],
        ["provider-cuda", {"provider": "cuda"}],
        ["provider-onnx", {"provider": "cpu_onnx_int8"}],
        ["provider-cpu", {"provider": "cpu"}],
        ["provider-unknown", {"provider": "custom_accelerator"}],
        ["provider-empty", {}],
        ["provider-fallback", {"provider": "cuda", "fallback": True}],
        ["provider-empty-fallback", {"fallback": True}],
    ]
    script = f"""
      import {{ modelLabel, runtimeProviderLabel }} from {json.dumps(MODULE.as_uri())};
      const cases = {json.dumps(cases, ensure_ascii=False)};
      const output = Object.fromEntries(cases.map(([name, value]) => [
        name,
        name.startsWith('model-') ? modelLabel(value) : runtimeProviderLabel(value)
      ]));
      output['model-undefined'] = modelLabel(undefined);
      console.log(JSON.stringify(output));
    """
    return json.loads(_node(script).stdout)


def _capability_results() -> dict[str, object]:
    script = f"""
      import * as capabilities from {json.dumps(CAPABILITIES_MODULE.as_uri())};
      const {{
        modelNeedsWake,
        modelParameterSchema,
        modelRequiresPromptAudio,
        modelRequiresPromptText,
        modelSupportsVoiceClone
      }} = capabilities;
      const emptySchema = [];
      const populatedSchema = [{{ key: 'temperature', type: 'number' }}];
      const populatedBefore = JSON.stringify(populatedSchema);
      const output = {{
        exports: Object.keys(capabilities).sort(),
        wake: [
          modelNeedsWake(null),
          modelNeedsWake({{}}),
          modelNeedsWake({{ available: false, loaded: false }}),
          modelNeedsWake({{ loaded: false }}),
          modelNeedsWake({{ loaded: true, idle_unloaded: true }}),
          modelNeedsWake({{ loaded: true }})
        ],
        schema: {{
          nullValue: modelParameterSchema(null),
          missing: modelParameterSchema({{}}),
          nonArray: modelParameterSchema({{ parameter_schema: 'invalid' }}),
          emptySameReference: modelParameterSchema({{ parameter_schema: emptySchema }}) === emptySchema,
          populatedSameReference: modelParameterSchema({{ parameter_schema: populatedSchema }}) === populatedSchema,
          populatedValue: modelParameterSchema({{ parameter_schema: populatedSchema }}),
          populatedUnchanged: JSON.stringify(populatedSchema) === populatedBefore
        }},
        promptAudio: [
          modelRequiresPromptAudio({{ requires_prompt_audio: true }}),
          modelRequiresPromptAudio({{ requires_prompt_audio: false }}),
          modelRequiresPromptAudio({{}})
        ],
        promptText: [
          modelRequiresPromptText({{ requires_prompt_text: true }}),
          modelRequiresPromptText({{ requires_prompt_text: false }}),
          modelRequiresPromptText({{}})
        ],
        clone: [
          modelSupportsVoiceClone({{ voice_clone_supported: true }}),
          modelSupportsVoiceClone({{ modes: ['voice_clone'] }}),
          modelSupportsVoiceClone({{ backend: 'moss-tts-nano-onnx' }}),
          modelSupportsVoiceClone({{ id: 'moss-demo' }}),
          modelSupportsVoiceClone({{ id: 'kokoro', backend: 'kokoro', modes: [] }})
        ]
      }};
      console.log(JSON.stringify(output));
    """
    return json.loads(_node(script).stdout)


def _voice_results() -> dict[str, object]:
    script = f"""
      import * as presentation from {json.dumps(VOICE_MODULE.as_uri())};
      const values = ['zf_xiaobei', 'zm_yunxi', 'af_maple', 'bf_emma', 'am_adam', 'bm_george', 'custom', '', null];
      console.log(JSON.stringify({{
        exports: Object.keys(presentation).sort(),
        kinds: values.map(value => presentation.builtinVoiceKind(value))
      }}));
    """
    return json.loads(_node(script).stdout)


def test_model_label_contract_and_native_esm_import() -> None:
    results = _module_results()
    assert results["model-null"] == "未知模型"
    assert results["model-undefined"] == "未知模型"
    assert results["model-name"] == "Named model"
    assert results["model-id"] == "model-id"


def test_runtime_provider_label_contract() -> None:
    results = _module_results()
    assert results["provider-cuda-pytorch"] == "CUDA"
    assert results["provider-cuda"] == "CUDA"
    assert results["provider-onnx"] == "CPU ONNX INT8"
    assert results["provider-cpu"] == "CPU"
    assert results["provider-unknown"] == "custom_accelerator"
    assert results["provider-empty"] == "已加载"
    assert results["provider-fallback"] == "CUDA · 已回退"
    assert results["provider-empty-fallback"] == "已加载 · 已回退"


def test_model_capability_contracts_and_native_esm_import() -> None:
    results = _capability_results()
    assert results["exports"] == [
        "modelNeedsWake",
        "modelParameterSchema",
        "modelRequiresPromptAudio",
        "modelRequiresPromptText",
        "modelSupportsVoiceClone",
    ]
    assert results["wake"] == [False, False, False, True, True, False]
    assert results["promptAudio"] == [True, False, False]
    assert results["promptText"] == [True, False, False]
    assert results["clone"] == [True, True, True, True, False]


def test_model_parameter_schema_preserves_array_identity_and_content() -> None:
    schema = _capability_results()["schema"]
    assert schema["nullValue"] == []
    assert schema["missing"] == []
    assert schema["nonArray"] == []
    assert schema["emptySameReference"] is True
    assert schema["populatedSameReference"] is True
    assert schema["populatedValue"] == [{"key": "temperature", "type": "number"}]
    assert schema["populatedUnchanged"] is True


def test_builtin_voice_kind_contract_and_native_esm_import() -> None:
    results = _voice_results()
    assert results["exports"] == ["builtinVoiceKind"]
    assert results["kinds"] == [
        "中文女声",
        "中文男声",
        "英文女声",
        "英文女声",
        "英文男声",
        "英文男声",
        "其他音色",
        "其他音色",
        "其他音色",
    ]


def test_presentation_module_is_pure_and_exports_only_the_contract() -> None:
    source = MODULE.read_text(encoding="utf-8")
    forbidden = ("window", "document", "localStorage", "sessionStorage", "globalThis", "state", "bootstrap", "currentModel")
    assert not any(re.search(rf"\b{word}\b", source) for word in forbidden)
    assert re.findall(r"\bexport\s+function\s+(\w+)", source) == ["modelLabel", "runtimeProviderLabel"]


def test_extracted_capability_and_voice_modules_are_pure() -> None:
    forbidden = (
        "window",
        "document",
        "localStorage",
        "sessionStorage",
        "globalThis",
        "state",
        "bootstrap",
        "currentModel",
        "profileForVoiceId",
        "modelSupportsProfiles",
    )
    expected_exports = {
        CAPABILITIES_MODULE: [
            "modelNeedsWake",
            "modelParameterSchema",
            "modelRequiresPromptAudio",
            "modelRequiresPromptText",
            "modelSupportsVoiceClone",
        ],
        VOICE_MODULE: ["builtinVoiceKind"],
    }
    for path, exports in expected_exports.items():
        source = path.read_text(encoding="utf-8")
        assert not any(re.search(rf"\b{word}\b", source) for word in forbidden), path.name
        assert re.findall(r"\bexport\s+function\s+(\w+)", source) == exports


def test_app_imports_the_module_once_without_old_function_definitions() -> None:
    source = APP.read_text(encoding="utf-8")
    for module_name in ("model-presentation", "model-capabilities", "voice-presentation"):
        imports = re.findall(
            rf"^import\s+\{{[^;]+\}}\s+from\s+['\"]\.\/studio\/{module_name}\.js\?h=([0-9a-f]{{12}})['\"];",
            source,
            re.MULTILINE,
        )
        assert len(imports) == 1, module_name
    assert source.startswith("import ")
    removed = (
        "modelLabel",
        "runtimeProviderLabel",
        "currentModelNeedsWake",
        "currentParameterSchema",
        "modelRequiresPromptAudio",
        "modelRequiresPromptText",
        "modelSupportsVoiceClone",
    )
    assert not re.search(rf"function\s+(?:{'|'.join(removed)})\s*\(", source)
    assert "runtimeProviderLabel(model)" in source
    assert not re.search(r"window\.(?:modelNeedsWake|modelParameterSchema|builtinVoiceKind)\b", source)


def test_app_voice_kind_keeps_profile_and_moss_branches_before_builtin_fallback() -> None:
    source = APP.read_text(encoding="utf-8")
    match = re.search(r"function voiceKind\(voice\) \{(?P<body>.*?)\n\}", source, re.DOTALL)
    assert match
    body = match.group("body")
    profile = body.index("modelSupportsProfiles()")
    moss = body.index("state.selectedModel.startsWith('moss')")
    builtin = body.index("builtinVoiceKind(voice)")
    assert profile < moss < builtin
    assert not re.search(r"startsWith\(['\"](?:zf_|zm_)|\^\[ab\][fm]_", body)


def test_index_has_one_module_entry_in_dependency_order() -> None:
    html = INDEX.read_text(encoding="utf-8")
    entry = re.findall(r'<script\s+type="module"\s+src="(/static/app\.js\?h=[0-9a-f]{12})"></script>', html)
    assert len(entry) == 1
    assert html.count("/static/app.js?h=") == 1
    assert not re.search(r'<script[^>]+src="/static/app\.js[^>]+\bdefer\b', html)
    ordered = [
        "/static/locale/messages.zh-cn.js",
        "/static/locale/messages.en.js",
        "/static/common/i18n.js",
        "/static/security_notice.js",
        "/static/app.js",
    ]
    assert [html.index(item) for item in ordered] == sorted(html.index(item) for item in ordered)


def test_all_studio_cache_queries_match_portable_sha256() -> None:
    app_source = APP.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    presentation_hash = _portable_source_hash(MODULE)
    capabilities_hash = _portable_source_hash(CAPABILITIES_MODULE)
    voice_hash = _portable_source_hash(VOICE_MODULE)
    i18n_hash = _portable_source_hash(I18N_MODULE)
    app_hash = _portable_source_hash(APP)
    assert f"model-presentation.js?h={presentation_hash}" in app_source
    assert f"model-capabilities.js?h={capabilities_hash}" in app_source
    assert f"voice-presentation.js?h={voice_hash}" in app_source
    assert f"/static/common/i18n.js?h={i18n_hash}" in html
    assert f"/static/app.js?h={app_hash}" in html


def test_portable_source_hash_is_independent_of_line_endings(tmp_path: Path) -> None:
    lf_source = tmp_path / "lf.js"
    crlf_source = tmp_path / "crlf.js"
    logical_source = "export const first = 1;\nexport const second = 2;\n"
    lf_source.write_bytes(logical_source.encode("utf-8"))
    crlf_source.write_bytes(logical_source.replace("\n", "\r\n").encode("utf-8"))
    assert _portable_source_hash(lf_source) == _portable_source_hash(crlf_source)


def _temporary_source_tree(tmp_path: Path, javascript: str) -> Path:
    nested = tmp_path / "static" / "studio" / "nested"
    nested.mkdir(parents=True)
    (tmp_path / "templates").mkdir()
    (nested / "unimported.js").write_text(javascript, encoding="utf-8")
    return tmp_path


def test_scanner_finds_missing_key_in_unimported_nested_studio_script(tmp_path: Path) -> None:
    root = _temporary_source_tree(tmp_path, 'const value = t("missing.nested.key");')
    report = scan_i18n_references(root, catalog_keys={"known.key"})
    assert "missing.nested.key" in report.referenced
    assert any("Missing translation keys" in error and "missing.nested.key" in error for error in report.errors)


def test_scanner_fails_closed_for_unregistered_dynamic_key(tmp_path: Path) -> None:
    root = _temporary_source_tree(tmp_path, "const value = t(dynamicKey);")
    report = scan_i18n_references(root, catalog_keys=set())
    assert any("Unallowlisted dynamic translation key" in error and "dynamicKey" in error for error in report.errors)


def test_scanner_reports_stale_dynamic_allowlist(tmp_path: Path) -> None:
    root = _temporary_source_tree(tmp_path, 'const value = t("known.key");')
    allowlist = {
        "static/studio/nested/unimported.js": (
            DynamicKeyAllowance("unused.key", "deliberate stale-entry test", frozenset({"known.key"})),
        )
    }
    report = scan_i18n_references(root, catalog_keys={"known.key"}, dynamic_allowlist=allowlist)
    assert any("Stale dynamic-key allowance" in error and "unused.key" in error for error in report.errors)


def test_catalogs_remain_75_key_symmetric_with_matching_placeholders() -> None:
    locale = PACKAGE_ROOT / "static" / "locale"
    pair = re.compile(r"^\s*'([^']+)'\s*:\s*'((?:\\'|[^'])*)'", re.MULTILINE)
    placeholder = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
    catalogs = [dict(pair.findall((locale / name).read_text(encoding="utf-8"))) for name in ("messages.zh-cn.js", "messages.en.js")]
    assert len(catalogs[0]) == len(catalogs[1]) == 75
    assert catalogs[0].keys() == catalogs[1].keys()
    assert all(placeholder.findall(catalogs[0][key]) == placeholder.findall(catalogs[1][key]) for key in catalogs[0])
