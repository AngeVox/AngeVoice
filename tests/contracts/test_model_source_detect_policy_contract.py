"""P2E contracts for the existing ModelSource detect and policy behavior.

These tests characterize current behavior without performing network access,
downloads, service startup, or model loading. P2F downloader execution and P2G
worker/deployment behavior remain explicitly outside this contract.
"""

from __future__ import annotations

import ast
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoro_tts import model_sources
from kokoro_tts.admin_config.schema import apply_admin_config_values
from kokoro_tts.config import TTSConfig
from kokoro_tts.model_source_metadata import MODEL_SOURCE_METADATA


PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "kokoro_tts"


def _module_tree(relative: str) -> ast.Module:
    return ast.parse((PACKAGE_ROOT / relative).read_text(encoding="utf-8"))


def _definition(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == name
    )


def _call_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    for call in (item for item in ast.walk(node) if isinstance(item, ast.Call)):
        if isinstance(call.func, ast.Name):
            names.append(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            names.append(call.func.attr)
    return names


def _assigned_attributes(node: ast.AST) -> set[str]:
    attributes: set[str] = set()
    for item in ast.walk(node):
        targets: list[ast.expr] = []
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
        for target in targets:
            if isinstance(target, ast.Attribute):
                attributes.add(target.attr)
    return attributes


class _FakeResponse:
    def __init__(self, *, status: int = 200, payload: bytes = b"") -> None:
        self.status = status
        self.payload = payload
        self.read_limits: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        self.read_limits.append(limit)
        return self.payload[:limit]


def _resolver_config(
    *,
    requested: str = "auto",
    cached: str = "",
    country: str = "",
    hf_reachable: bool | None = None,
    modelscope_reachable: bool | None = None,
):
    return SimpleNamespace(
        model_source=requested,
        model_source_effective=cached,
        model_source_country=country,
        model_source_hf_reachable=hf_reachable,
        model_source_modelscope_reachable=modelscope_reachable,
    )


def test_canonical_model_source_owners_and_metadata_scope_are_frozen():
    assert TTSConfig._normalize_model_source.__module__ == "kokoro_tts.config"
    assert TTSConfig._normalize_model_source.__qualname__ == "TTSConfig._normalize_model_source"
    assert model_sources.resolve_model_source.__module__ == "kokoro_tts.model_sources"
    assert model_sources._generic_download_plan.__module__ == "kokoro_tts.model_sources"
    assert MODEL_SOURCE_METADATA.runtime_normalization_owner == "TTSConfig._normalize_model_source"
    assert MODEL_SOURCE_METADATA.resolver_owner == "model_sources.resolve_model_source"
    assert MODEL_SOURCE_METADATA.engine_scope == frozenset(
        {"kokoro", "moss", "moss_audio_tokenizer"}
    )
    assert MODEL_SOURCE_METADATA.excluded_engine_scope == "zipvoice"


def test_model_source_metadata_remains_declaration_only_not_a_behavior_owner():
    tree = _module_tree("model_source_metadata.py")
    imported_modules = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert imported_modules == {"dataclasses"}
    assert not {
        "resolve_model_source",
        "_probe_url",
        "_detect_country",
        "urlopen",
        "snapshot_download",
    } & set(_call_names(tree))


@pytest.mark.parametrize("requested", ["huggingface", "modelscope", "offline"])
def test_explicit_mode_is_selected_without_auto_detection_characterization(
    requested, monkeypatch
):
    """Characterization of current behavior, not endorsement."""

    cfg = _resolver_config(
        requested=requested,
        cached="stale",
        country="CN",
        hf_reachable=False,
        modelscope_reachable=True,
    )
    monkeypatch.setattr(
        model_sources,
        "_probe_reachability",
        lambda _cfg: pytest.fail("explicit mode must not probe reachability"),
    )
    monkeypatch.setattr(
        model_sources,
        "_detect_country",
        lambda _cfg: pytest.fail("explicit mode must not detect country"),
    )

    assert model_sources.resolve_model_source(cfg) == requested
    assert cfg.model_source_effective == requested
    # Current explicit-mode selection leaves stale observability fields intact.
    assert cfg.model_source_country == "CN"
    assert cfg.model_source_hf_reachable is False
    assert cfg.model_source_modelscope_reachable is True


@pytest.mark.parametrize("cached", ["huggingface", "modelscope", "offline"])
def test_auto_valid_effective_cache_bypasses_detection_without_mutation(
    cached, monkeypatch
):
    cfg = _resolver_config(
        requested="auto",
        cached=cached,
        country="US",
        hf_reachable=False,
        modelscope_reachable=True,
    )
    monkeypatch.setattr(
        model_sources,
        "_probe_reachability",
        lambda _cfg: pytest.fail("valid effective cache must not probe"),
    )
    monkeypatch.setattr(
        model_sources,
        "_detect_country",
        lambda _cfg: pytest.fail("valid effective cache must not detect country"),
    )

    assert model_sources.resolve_model_source(cfg) == cached
    assert cfg.model_source_effective == cached
    assert cfg.model_source_country == "US"
    assert cfg.model_source_hf_reachable is False
    assert cfg.model_source_modelscope_reachable is True


@pytest.mark.parametrize("cached", ["auto", "unknown", ""])
def test_auto_invalid_effective_cache_reenters_policy_decision(cached, monkeypatch):
    cfg = _resolver_config(requested="auto", cached=cached)
    calls: list[str] = []

    def fake_probe(target):
        calls.append("probe")
        target.model_source_hf_reachable = True
        target.model_source_modelscope_reachable = False
        return True, False

    monkeypatch.setattr(model_sources, "_probe_reachability", fake_probe)
    monkeypatch.setattr(
        model_sources,
        "_detect_country",
        lambda _cfg: pytest.fail("single-provider reachability must not use country"),
    )

    assert model_sources.resolve_model_source(cfg) == "huggingface"
    assert cfg.model_source_effective == "huggingface"
    assert calls == ["probe"]


@pytest.mark.parametrize(
    (
        "requested",
        "cached",
        "hf_reachable",
        "modelscope_reachable",
        "country",
        "expected",
        "country_called",
    ),
    [
        pytest.param(
            "auto", "unknown", False, True, "", "modelscope", False, id="modelscope-only"
        ),
        pytest.param(
            "auto", "unknown", True, False, "", "huggingface", False, id="hf-only"
        ),
        pytest.param(
            "auto", "unknown", True, True, "CN", "modelscope", True, id="both-cn"
        ),
        pytest.param(
            "auto", "unknown", True, True, "US", "huggingface", True, id="both-us"
        ),
        pytest.param(
            "auto", "unknown", True, True, "", "huggingface", True, id="both-no-country"
        ),
        pytest.param(
            "auto", "unknown", False, False, "CN", "modelscope", True, id="neither-cn"
        ),
        pytest.param(
            "auto", "unknown", False, False, "US", "huggingface", True, id="neither-us"
        ),
        pytest.param(
            "auto", "unknown", False, False, "", "huggingface", True, id="neither-no-country"
        ),
    ],
)
def test_auto_policy_decision_table_mutates_only_owned_state(
    requested,
    cached,
    hf_reachable,
    modelscope_reachable,
    country,
    expected,
    country_called,
    monkeypatch,
):
    cfg = _resolver_config(
        requested=requested,
        cached=cached,
        country="unchanged-unless-detected",
    )
    calls: list[str] = []

    def fake_probe(target):
        calls.append("probe")
        # Reachability state is owned and mutated by _probe_reachability.
        target.model_source_hf_reachable = hf_reachable
        target.model_source_modelscope_reachable = modelscope_reachable
        return hf_reachable, modelscope_reachable

    def fake_country(target):
        calls.append("country")
        target.model_source_country = country
        return country

    monkeypatch.setattr(model_sources, "_probe_reachability", fake_probe)
    monkeypatch.setattr(model_sources, "_detect_country", fake_country)

    assert model_sources.resolve_model_source(cfg) == expected
    assert cfg.model_source_effective == expected
    assert cfg.model_source_hf_reachable is hf_reachable
    assert cfg.model_source_modelscope_reachable is modelscope_reachable
    assert ("country" in calls) is country_called
    assert calls == (["probe", "country"] if country_called else ["probe"])
    assert cfg.model_source_country == (
        country if country_called else "unchanged-unless-detected"
    )


def test_reachability_mutation_is_owned_by_probe_not_duplicated_by_resolver():
    tree = _module_tree("model_sources.py")
    resolver = _definition(tree, "resolve_model_source")
    probe = _definition(tree, "_probe_reachability")
    cache_fields = {
        "model_source_hf_reachable",
        "model_source_modelscope_reachable",
    }
    assert cache_fields <= _assigned_attributes(probe)
    assert not cache_fields & _assigned_attributes(resolver)


def test_country_detection_uses_normalized_config_cache_without_env_or_url(
    monkeypatch,
):
    class ExplodingEnvironment(dict):
        def get(self, *_args, **_kwargs):
            pytest.fail("config country cache must bypass environment reads")

    cfg = SimpleNamespace(model_source_country="  cn  ")
    monkeypatch.setattr(model_sources.os, "environ", ExplodingEnvironment())
    monkeypatch.setattr(
        model_sources.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("config country cache must bypass URL"),
    )

    assert model_sources._detect_country(cfg) == "CN"


def test_country_detection_prefers_canonical_alias_over_legacy(monkeypatch):
    cfg = SimpleNamespace(model_source_country="", model_source_detect_url="")
    monkeypatch.setenv("ANGEVOICE_MODEL_SOURCE_COUNTRY", "cn")
    monkeypatch.setenv("MODEL_SOURCE_COUNTRY", "us")
    monkeypatch.setattr(
        model_sources.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("environment alias must bypass URL"),
    )

    assert model_sources._detect_country(cfg) == "CN"
    assert cfg.model_source_country == "CN"


def test_country_detection_accepts_legacy_alias_when_canonical_is_absent(monkeypatch):
    cfg = SimpleNamespace(model_source_country="", model_source_detect_url="")
    monkeypatch.delenv("ANGEVOICE_MODEL_SOURCE_COUNTRY", raising=False)
    monkeypatch.setenv("MODEL_SOURCE_COUNTRY", "cn")

    assert model_sources._detect_country(cfg) == "CN"
    assert cfg.model_source_country == "CN"


def test_country_canonical_alias_whitespace_blocks_legacy_characterization(
    monkeypatch,
):
    """Alias whitespace edge characterization, not endorsement of final design."""

    cfg = SimpleNamespace(model_source_country="", model_source_detect_url="")
    monkeypatch.setenv("ANGEVOICE_MODEL_SOURCE_COUNTRY", " ")
    monkeypatch.setenv("MODEL_SOURCE_COUNTRY", "CN")
    monkeypatch.setattr(
        model_sources.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("truthy canonical alias bypasses URL"),
    )

    assert model_sources._detect_country(cfg) == ""
    assert cfg.model_source_country == ""


def test_country_detection_url_contract_reads_at_most_sixteen_bytes(monkeypatch):
    cfg = SimpleNamespace(
        model_source_country="",
        model_source_detect_url="https://country.invalid/value",
        model_source_detect_timeout_seconds=2.75,
    )
    monkeypatch.delenv("ANGEVOICE_MODEL_SOURCE_COUNTRY", raising=False)
    monkeypatch.delenv("MODEL_SOURCE_COUNTRY", raising=False)
    response = _FakeResponse(payload=b"cn\nignored trailing bytes")
    calls: list[tuple[object, float]] = []

    def fake_urlopen(url, *, timeout):
        calls.append((url, timeout))
        return response

    monkeypatch.setattr(model_sources.urllib.request, "urlopen", fake_urlopen)

    assert model_sources._detect_country(cfg) == "CN\nIGNORED TRAIL"
    assert calls == [("https://country.invalid/value", 2.75)]
    assert response.read_limits == [16]
    assert cfg.model_source_country == "CN\nIGNORED TRAIL"


def test_country_detection_url_normalizes_short_response(monkeypatch):
    cfg = SimpleNamespace(
        model_source_country="",
        model_source_detect_url="https://country.invalid/value",
        model_source_detect_timeout_seconds=1.25,
    )
    monkeypatch.delenv("ANGEVOICE_MODEL_SOURCE_COUNTRY", raising=False)
    monkeypatch.delenv("MODEL_SOURCE_COUNTRY", raising=False)
    response = _FakeResponse(payload=b"cn\n")
    monkeypatch.setattr(
        model_sources.urllib.request,
        "urlopen",
        lambda _url, *, timeout: response,
    )

    assert model_sources._detect_country(cfg) == "CN"
    assert response.read_limits == [16]
    assert cfg.model_source_country == "CN"


def test_country_detection_empty_url_does_not_open_network(monkeypatch):
    cfg = SimpleNamespace(model_source_country="", model_source_detect_url="  ")
    monkeypatch.delenv("ANGEVOICE_MODEL_SOURCE_COUNTRY", raising=False)
    monkeypatch.delenv("MODEL_SOURCE_COUNTRY", raising=False)
    monkeypatch.setattr(
        model_sources.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("empty detect URL must not be opened"),
    )

    assert model_sources._detect_country(cfg) == ""


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("unreachable"),
        TimeoutError("timeout"),
        OSError("socket"),
        RuntimeError("generic"),
    ],
)
def test_country_detection_failures_cache_empty_result(error, monkeypatch):
    cfg = SimpleNamespace(
        model_source_country="stale",
        model_source_detect_url="https://country.invalid/value",
        model_source_detect_timeout_seconds=1.0,
    )
    # Force the URL branch after proving that failure overwrites transient state.
    cfg.model_source_country = ""
    monkeypatch.delenv("ANGEVOICE_MODEL_SOURCE_COUNTRY", raising=False)
    monkeypatch.delenv("MODEL_SOURCE_COUNTRY", raising=False)

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(model_sources.urllib.request, "urlopen", fail)

    assert model_sources._detect_country(cfg) == ""
    assert cfg.model_source_country == ""


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, True),
        (302, True),
        (401, True),
        (404, True),
        (499, True),
        (500, False),
        (503, False),
    ],
)
def test_probe_url_uses_head_request_and_stable_user_agent(
    status, expected, monkeypatch
):
    calls: list[tuple[object, float]] = []

    def fake_urlopen(request, *, timeout):
        calls.append((request, timeout))
        return _FakeResponse(status=status)

    monkeypatch.setattr(model_sources.urllib.request, "urlopen", fake_urlopen)

    assert model_sources._probe_url("https://provider.invalid", 3.5) is expected
    request, timeout = calls[0]
    assert isinstance(request, model_sources.urllib.request.Request)
    assert request.full_url == "https://provider.invalid"
    assert request.get_method() == "HEAD"
    assert request.get_header("User-agent") == "AngeVoice/model-source-probe"
    assert timeout == 3.5


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, True), (403, True), (404, True), (500, False), (503, False)],
)
def test_probe_url_classifies_http_errors_by_reachability(
    status, expected, monkeypatch
):
    def fail(request, *, timeout):
        raise urllib.error.HTTPError(
            request.full_url, status, "fake", hdrs=None, fp=None
        )

    monkeypatch.setattr(model_sources.urllib.request, "urlopen", fail)
    assert model_sources._probe_url("https://provider.invalid", 1.0) is expected


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("unreachable"),
        TimeoutError("timeout"),
        OSError("socket"),
        RuntimeError("generic"),
    ],
)
def test_probe_url_treats_non_http_failures_as_unreachable(error, monkeypatch):
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(model_sources.urllib.request, "urlopen", fail)
    assert model_sources._probe_url("https://provider.invalid", 1.0) is False


def test_probe_url_empty_input_does_not_construct_or_open_request(monkeypatch):
    monkeypatch.setattr(
        model_sources.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("empty URL must not be opened"),
    )
    assert model_sources._probe_url("", 1.0) is False


def test_probe_reachability_is_serial_hf_then_modelscope_and_mutates_cache(
    monkeypatch,
):
    cfg = SimpleNamespace(
        model_source_probe_timeout_seconds=2.25,
        model_source_probe_hf_url="https://hf.invalid",
        model_source_probe_modelscope_url="https://ms.invalid",
        model_source_hf_reachable=None,
        model_source_modelscope_reachable=None,
    )
    calls: list[tuple[str, float]] = []
    outcomes = iter([True, False])

    def fake_probe(url, timeout):
        calls.append((url, timeout))
        return next(outcomes)

    monkeypatch.setattr(model_sources, "_probe_url", fake_probe)

    assert model_sources._probe_reachability(cfg) == (True, False)
    assert calls == [
        ("https://hf.invalid", 2.25),
        ("https://ms.invalid", 2.25),
    ]
    assert cfg.model_source_hf_reachable is True
    assert cfg.model_source_modelscope_reachable is False


def test_admin_model_source_change_resets_all_resolver_cache_without_restart():
    cfg = TTSConfig(model_source="auto")
    cfg.model_source_effective = "huggingface"
    cfg.model_source_country = "US"
    cfg.model_source_hf_reachable = True
    cfg.model_source_modelscope_reachable = False

    changed, restart_required, rebuild_moss = apply_admin_config_values(
        cfg, {"model_source": "modelscope"}
    )

    assert changed == ["model_source"]
    assert restart_required == []
    assert rebuild_moss is False
    assert cfg.model_source == "modelscope"
    assert cfg.model_source_effective == "auto"
    assert cfg.model_source_country == ""
    assert cfg.model_source_hf_reachable is None
    assert cfg.model_source_modelscope_reachable is None


def test_admin_same_model_source_value_preserves_resolver_cache_characterization():
    """Characterization: a same-value Admin save does not request a reprobe."""

    cfg = TTSConfig(model_source="auto")
    cfg.model_source_effective = "modelscope"
    cfg.model_source_country = "CN"
    cfg.model_source_hf_reachable = False
    cfg.model_source_modelscope_reachable = True

    changed, restart_required, rebuild_moss = apply_admin_config_values(
        cfg, {"model_source": "auto"}
    )

    assert changed == []
    assert restart_required == []
    assert rebuild_moss is False
    assert cfg.model_source_effective == "modelscope"
    assert cfg.model_source_country == "CN"
    assert cfg.model_source_hf_reachable is False
    assert cfg.model_source_modelscope_reachable is True


def test_programmatic_direct_mutation_can_hit_sticky_effective_cache_characterization(
    monkeypatch,
):
    """Programmatic direct-mutation characterization; Admin mutation resets cache."""

    cfg = TTSConfig(model_source="modelscope")
    cfg.model_source_effective = "offline"
    cfg.model_source = "auto"
    monkeypatch.setattr(
        model_sources,
        "_probe_reachability",
        lambda _cfg: pytest.fail("sticky effective cache must bypass probing"),
    )

    assert model_sources.resolve_model_source(cfg) == "offline"
    assert cfg.model_source_effective == "offline"


@pytest.mark.parametrize(
    ("effective", "hf_repo", "ms_repo", "expected"),
    [
        pytest.param("offline", "hf/repo", "ms/repo", [], id="offline-no-plan"),
        pytest.param(
            "modelscope",
            "hf/repo",
            "ms/repo",
            [("modelscope", "ms/repo"), ("huggingface", "hf/repo")],
            id="modelscope-preferred-hf-fallback",
        ),
        pytest.param(
            "huggingface",
            "hf/repo",
            "ms/repo",
            [("huggingface", "hf/repo"), ("modelscope", "ms/repo")],
            id="hf-preferred-modelscope-fallback",
        ),
        pytest.param(
            "modelscope",
            "hf/repo",
            "",
            [("huggingface", "hf/repo")],
            id="empty-preferred-repo-is-omitted",
        ),
        pytest.param(
            "huggingface",
            "",
            "ms/repo",
            [("modelscope", "ms/repo")],
            id="empty-preferred-repo-uses-fallback-only",
        ),
        pytest.param("huggingface", "", "", [], id="both-repositories-empty"),
    ],
)
def test_provider_plan_uses_preferred_then_fallback_without_download_execution(
    effective, hf_repo, ms_repo, expected, monkeypatch
):
    cfg = SimpleNamespace(hf_repo=hf_repo, ms_repo=ms_repo)
    resolver_calls: list[object] = []

    def fake_resolver(target):
        resolver_calls.append(target)
        return effective

    monkeypatch.setattr(model_sources, "resolve_model_source", fake_resolver)
    monkeypatch.setattr(
        model_sources,
        "_huggingface_snapshot_download",
        lambda *_args, **_kwargs: pytest.fail("plan must not execute P2F download"),
    )
    monkeypatch.setattr(
        model_sources,
        "_modelscope_snapshot_download",
        lambda *_args, **_kwargs: pytest.fail("plan must not execute P2F download"),
    )

    plan = model_sources._generic_download_plan(
        cfg, hf_attr="hf_repo", ms_attr="ms_repo"
    )
    assert plan == expected
    assert resolver_calls == [cfg]
    assert len(plan) == len(set(plan))


def test_same_repo_string_for_different_providers_remains_two_fallback_entries(
    monkeypatch,
):
    cfg = SimpleNamespace(hf_repo="shared/repo", ms_repo="shared/repo")
    monkeypatch.setattr(
        model_sources, "resolve_model_source", lambda _cfg: "modelscope"
    )

    assert model_sources._generic_download_plan(
        cfg, hf_attr="hf_repo", ms_attr="ms_repo"
    ) == [
        ("modelscope", "shared/repo"),
        ("huggingface", "shared/repo"),
    ]


def test_provider_plan_delegates_policy_once_without_copying_auto_or_p2f_execution():
    tree = _module_tree("model_sources.py")
    plan = _definition(tree, "_generic_download_plan")
    calls = _call_names(plan)
    assert calls.count("resolve_model_source") == 1
    assert "_probe_reachability" not in calls
    assert "_detect_country" not in calls
    assert "_huggingface_snapshot_download" not in calls
    assert "_modelscope_snapshot_download" not in calls


def test_model_source_resolution_is_lazy_and_owned_by_asset_or_load_paths():
    config_tree = _module_tree("config.py")
    server_tree = _module_tree("server.py")
    engine_tree = _module_tree("engine.py")
    moss_tree = _module_tree("moss/runtime.py")
    assets_tree = _module_tree("model_assets.py")

    load_config = _definition(config_tree, "load_config")
    create_app = _definition(server_tree, "create_app")
    prepare_kokoro = _definition(engine_tree, "_prepare_kokoro_load")
    load_kokoro = _definition(engine_tree, "load")
    create_moss_runtime = _definition(moss_tree, "create_runtime")
    repair_assets = _definition(assets_tree, "repair")

    assert "resolve_model_source" not in _call_names(load_config)
    assert not {
        "resolve_model_source",
        "_probe_reachability",
        "_detect_country",
    } & set(_call_names(create_app))
    assert "ensure_kokoro_model_dir" in _call_names(prepare_kokoro)
    assert "resolve_model_source" in _call_names(load_kokoro)
    assert {
        "ensure_moss_model_dir",
        "ensure_moss_audio_tokenizer_dir",
    } <= set(_call_names(create_moss_runtime))
    assert {
        "ensure_kokoro_model_dir",
        "ensure_moss_model_dir",
        "ensure_moss_audio_tokenizer_dir",
    } <= set(_call_names(repair_assets))


def test_startup_preload_is_the_explicit_model_load_trigger_not_unconditional_probe():
    create_app = _definition(_module_tree("server.py"), "create_app")
    preload_guards = [
        node
        for node in ast.walk(create_app)
        if isinstance(node, ast.If)
        and "startup_preload_enabled" in ast.unparse(node.test)
        and "warm_model" in _call_names(node)
    ]
    assert len(preload_guards) == 1
    assert _call_names(create_app).count("warm_model") == 1
    assert "switch_model" in _call_names(create_app)


def test_zipvoice_remains_outside_generic_model_source_policy():
    forbidden_identifiers = {
        "model_sources",
        "resolve_model_source",
        "model_source_effective",
        "model_source_country",
        "model_source_hf_reachable",
        "model_source_modelscope_reachable",
    }
    for path in sorted((PACKAGE_ROOT / "zipvoice").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        attributes = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        imported = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not forbidden_identifiers & (names | attributes)
        assert not any("model_sources" in module for module in imported)

    assert MODEL_SOURCE_METADATA.excluded_engine_scope == "zipvoice"


def test_zipvoice_owns_independent_manifest_revision_integrity_and_download_policy():
    zipvoice_root = PACKAGE_ROOT / "zipvoice"
    assert (zipvoice_root / "assets_manifest.json").is_file()
    assert (zipvoice_root / "assets_manifest_cuda.json").is_file()
    assets_tree = _module_tree("zipvoice/assets.py")
    calls = set(_call_names(assets_tree))
    imported_names = {
        alias.name
        for node in ast.walk(assets_tree)
        if isinstance(node, ast.ImportFrom) and node.module == "huggingface_hub"
        for alias in node.names
    }
    attributes = {
        node.attr
        for node in ast.walk(assets_tree)
        if isinstance(node, ast.Attribute)
    }
    assert "hf_hub_download" in imported_names
    assert "_download_asset" in calls
    assert "file_sha256" in calls
    assert "revision" in attributes or "revision" in (
        PACKAGE_ROOT / "zipvoice" / "assets.py"
    ).read_text(encoding="utf-8")


def test_p2e_resolver_does_not_claim_p2f_download_or_p2g_worker_execution():
    model_sources_tree = _module_tree("model_sources.py")
    resolver = _definition(model_sources_tree, "resolve_model_source")
    resolver_calls = set(_call_names(resolver))
    assert not {
        "_modelscope_snapshot_download",
        "_huggingface_snapshot_download",
        "snapshot_download",
        "hf_hub_download",
        "_export_config_for_workers",
        "run_server",
    } & resolver_calls

    server_tree = _module_tree("server.py")
    worker_exports = next(
        node.value
        for node in server_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_WORKER_ENV_EXPORTS"
            for target in node.targets
        )
    )
    exported = {
        ast.literal_eval(key): ast.literal_eval(value)
        for key, value in zip(worker_exports.keys, worker_exports.values)
        if key is not None
    }
    # These propagation facts exist, but their synchronization and cache
    # consistency remain P2G rather than P2E behavior.
    assert exported["ANGEVOICE_MODEL_SOURCE"] == "model_source"
    assert (
        exported["ANGEVOICE_MODEL_SOURCE_PROBE_TIMEOUT_SECONDS"]
        == "model_source_probe_timeout_seconds"
    )
