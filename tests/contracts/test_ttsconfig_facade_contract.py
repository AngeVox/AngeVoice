"""Characterization contracts for the public TTSConfig compatibility facade.

KNOWN LIMITATION 1: an explicit ``runtime_config_file`` override cannot choose
the JSON file read during that same ``load_config`` call.
KNOWN LIMITATION 2: named parameters use truthiness while ``**kwargs`` uses a
non-``None`` check.
KNOWN LIMITATION 3: a named ``model_dir`` override can bypass ``expanduser``.
KNOWN LIMITATION 4: unknown keyword arguments are silently ignored.

These contracts describe current compatibility behavior. Any future change needs
separate authorization, explicit compatibility review, and a contract update.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kokoro_tts.config import TTSConfig, load_config
from kokoro_tts.server import create_app


pytestmark = pytest.mark.contract


def _write_runtime_config(path: Path, values: dict[str, object]) -> None:
    serialized = json.dumps(
        {"version": 1, "values": values}, ensure_ascii=False, sort_keys=True
    )
    path.write_bytes((serialized + "\n").encode("utf-8"))


def _isolate_load_config_environment(monkeypatch, tmp_path: Path, runtime_path: Path) -> None:
    """Make facade tests independent from operator files and relevant ENV state."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("ANGEVOICE_RUNTIME_CONFIG_FILE", str(runtime_path))
    monkeypatch.setenv("ANGEVOICE_CREDENTIALS_DIR", str(tmp_path / "credentials"))
    monkeypatch.setenv("ANGEVOICE_API_KEY_FILE", str(tmp_path / "credentials" / "api-key"))
    monkeypatch.setenv(
        "ANGEVOICE_ADMIN_CREDENTIALS_FILE",
        str(tmp_path / "credentials" / "admin-credentials.json"),
    )
    monkeypatch.setenv("ANGEVOICE_OUTPUT_DIR", str(tmp_path / "output-from-env"))
    monkeypatch.setenv("KOKORO_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.delenv("ANGEVOICE_MODELS_ROOT", raising=False)
    monkeypatch.delenv("KOKORO_CACHE_MAX_ITEMS", raising=False)
    monkeypatch.delenv("KOKORO_PORT", raising=False)
    monkeypatch.delenv("KOKORO_API_KEY", raising=False)
    monkeypatch.delenv("KOKORO_AUTO_API_KEY", raising=False)
    monkeypatch.setenv("ANGEVOICE_MODEL_SOURCE", "auto")


def _disable_validation(monkeypatch) -> None:
    """Keep non-validation contracts focused on facade ordering and paths."""
    monkeypatch.setattr(TTSConfig, "validate_security", lambda _self: None)


def test_explicit_runtime_config_path_applies_after_current_runtime_file_is_loaded(
    monkeypatch, tmp_path
) -> None:
    """KNOWN LIMITATION: explicit runtime_config_file cannot select this load's JSON."""
    runtime_a = tmp_path / "runtime-a.json"
    runtime_b = tmp_path / "runtime-b.json"
    explicit_output = tmp_path / "explicit-output"
    _write_runtime_config(
        runtime_a,
        {
            "cache_max_items": 71,
            "output_dir": "~/runtime-output-must-not-win",
        },
    )
    _write_runtime_config(runtime_b, {"cache_max_items": 72})
    _isolate_load_config_environment(monkeypatch, tmp_path, runtime_a)
    _disable_validation(monkeypatch)

    config = load_config(
        runtime_config_file=str(runtime_b), output_dir=str(explicit_output)
    )

    assert config.cache_max_items == 71
    assert config.runtime_config_file == runtime_b
    # Runtime JSON may override allowlisted cache settings, but Admin does not
    # own output_dir; the explicit facade override therefore remains final.
    assert config.output_dir == explicit_output


def test_runtime_config_only_applies_admin_writable_facade_fields(
    monkeypatch, tmp_path
) -> None:
    """Freeze only the facade/application allowlist boundary.

    Admin metadata, labels, choices and writable-surface design remain P2D.
    """
    runtime = tmp_path / "runtime.json"
    _write_runtime_config(
        runtime,
        {
            "cache_max_items": 81,
            "output_dir": "~/runtime-output-must-not-win",
        },
    )
    _isolate_load_config_environment(monkeypatch, tmp_path, runtime)
    _disable_validation(monkeypatch)

    config = load_config()

    expected_output = tmp_path / "output-from-env"
    assert config.cache_max_items == 81
    assert config.output_dir == expected_output
    assert config.output_dir != Path("~/runtime-output-must-not-win").expanduser()


def test_recognized_none_and_unknown_kwargs_keep_current_compatibility_behavior(
    monkeypatch, tmp_path
) -> None:
    runtime = tmp_path / "runtime.json"
    _write_runtime_config(runtime, {"cache_max_items": 81})
    _isolate_load_config_environment(monkeypatch, tmp_path, runtime)
    _disable_validation(monkeypatch)

    assert load_config(cache_max_items=91).cache_max_items == 91
    assert load_config(cache_max_items=None).cache_max_items == 81

    unknown = load_config(p2c_unknown_compat_probe="ignored")
    assert unknown.cache_max_items == 81
    assert not hasattr(unknown, "p2c_unknown_compat_probe")


def test_named_port_override_uses_current_truthy_compatibility_rule(
    monkeypatch, tmp_path
) -> None:
    """KNOWN LIMITATION: named ``port`` is truthy, unlike non-None kwargs."""
    runtime = tmp_path / "runtime.json"
    _write_runtime_config(runtime, {})
    _isolate_load_config_environment(monkeypatch, tmp_path, runtime)
    monkeypatch.setenv("KOKORO_PORT", "8123")
    _disable_validation(monkeypatch)

    assert load_config(port=0).port == 8123
    assert load_config(port=9000).port == 9000


def test_explicit_path_overrides_keep_current_normalization_asymmetry(
    monkeypatch, tmp_path
) -> None:
    """KNOWN LIMITATION: model_dir is converted before the later str expansion pass."""
    runtime = tmp_path / "runtime.json"
    _write_runtime_config(runtime, {})
    _isolate_load_config_environment(monkeypatch, tmp_path, runtime)
    _disable_validation(monkeypatch)

    output_dir = load_config(output_dir="~/angevoice-p2c-output").output_dir
    model_dir = load_config(model_dir="~/angevoice-p2c-model").model_dir

    assert isinstance(output_dir, Path)
    assert output_dir == Path("~/angevoice-p2c-output").expanduser()
    assert isinstance(model_dir, Path)
    assert model_dir == Path("~/angevoice-p2c-model")
    assert model_dir != Path("~/angevoice-p2c-model").expanduser()


def test_load_config_validates_after_explicit_overrides_and_path_normalization(
    monkeypatch, tmp_path
) -> None:
    runtime_a = tmp_path / "runtime-a.json"
    runtime_b = tmp_path / "runtime-b.json"
    _write_runtime_config(runtime_a, {"cache_max_items": 81})
    _write_runtime_config(runtime_b, {"cache_max_items": 82})
    _isolate_load_config_environment(monkeypatch, tmp_path, runtime_a)
    observed: dict[str, object] = {}

    def validation_spy(config: TTSConfig) -> None:
        observed.update(
            cache_max_items=config.cache_max_items,
            output_dir=config.output_dir,
            runtime_config_file=config.runtime_config_file,
        )

    monkeypatch.setattr(TTSConfig, "validate_security", validation_spy)

    config = load_config(
        cache_max_items=91,
        output_dir="~/angevoice-p2c-validation-output",
        runtime_config_file=str(runtime_b),
    )

    assert config.cache_max_items == 91
    assert observed == {
        "cache_max_items": 91,
        "output_dir": Path("~/angevoice-p2c-validation-output").expanduser(),
        "runtime_config_file": runtime_b,
    }


def test_create_app_preserves_injected_config_identity_without_reloading_sources(
    monkeypatch, tmp_path
) -> None:
    import kokoro_tts.server as server

    provided = TTSConfig(
        model_dir=tmp_path / "models",
        cache_max_items=123,
        model_idle_timeout_seconds=0,
        startup_preload_enabled=False,
        update_check_enabled=False,
        output_dir=tmp_path / "outputs",
        credentials_dir=tmp_path / "credentials",
        api_key_file=tmp_path / "credentials" / "api-key",
        admin_credentials_file=tmp_path / "credentials" / "admin-credentials.json",
        runtime_config_file=tmp_path / "runtime.json",
    )
    validation_calls: list[TTSConfig] = []

    def fail_load_config(*_args, **_kwargs):
        pytest.fail("create_app(config=provided) must not call load_config")

    def validation_spy() -> None:
        validation_calls.append(provided)

    monkeypatch.setattr(server, "load_config", fail_load_config)
    monkeypatch.setattr(provided, "validate_security", validation_spy)

    app = create_app(config=provided)
    try:
        assert validation_calls == [provided]
        assert app.state.angevoice.cfg is provided
    finally:
        app.state.angevoice.model_manager.stop_idle_timer()
