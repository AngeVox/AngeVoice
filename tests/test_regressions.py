from pathlib import Path

from kokoro_tts.admin_config_schema import ADMIN_CONFIG_FIELDS, validate_admin_config_values
from kokoro_tts.config import TTSConfig
from kokoro_tts.engine_manager import EngineManager, EngineSpec
from kokoro_tts.kokoro_assets import is_valid_kokoro_config_file


def test_mixed_english_policy_is_choice_and_validated():
    field = ADMIN_CONFIG_FIELDS["moss_mixed_english_policy"]
    assert field.type == "choice"
    validated = validate_admin_config_values({"moss_mixed_english_policy": "preserve"})
    assert validated["moss_mixed_english_policy"] == "preserve"


def test_compact_json_config_not_misclassified(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"sample_rate":24000,"foo":"bar"}', encoding="utf-8")
    assert is_valid_kokoro_config_file(cfg_file) is True


def test_text_rules_false_not_reported_as_enabled():
    cfg = TTSConfig(moss_apply_angevoice_rules="false", enabled_models=["kokoro"], default_model="kokoro")
    manager = EngineManager(cfg)
    try:
        spec = EngineSpec("moss-nano-cpu", "MOSS-TTS-Nano CPU", "moss-tts-nano-onnx", "cpu")
        snap = manager._static_capabilities(spec)
        assert snap["text_rules_enabled"] is False
    finally:
        manager.stop_idle_timer()


def _make_request_with_headers(headers: list[tuple[bytes, bytes]]):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/tts",
        "raw_path": b"/api/tts",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive=receive)


def test_api_tts_size_guard_requires_content_length():
    import pytest
    from fastapi import HTTPException
    from kokoro_tts.routes.audio import _enforce_request_size_limit

    req = _make_request_with_headers([])
    with pytest.raises(HTTPException) as exc:
        _enforce_request_size_limit(req, 1024)
    assert exc.value.status_code == 411


def test_api_tts_size_guard_rejects_empty_content_length():
    import pytest
    from fastapi import HTTPException
    from kokoro_tts.routes.audio import _enforce_request_size_limit

    req = _make_request_with_headers([(b"content-length", b"0")])
    with pytest.raises(HTTPException) as exc:
        _enforce_request_size_limit(req, 1024)
    assert exc.value.status_code == 400


def test_api_tts_size_guard_rejects_oversized_content_length():
    import pytest
    from fastapi import HTTPException
    from kokoro_tts.routes.audio import _enforce_request_size_limit

    req = _make_request_with_headers([(b"content-length", b"2048")])
    with pytest.raises(HTTPException) as exc:
        _enforce_request_size_limit(req, 1024)
    assert exc.value.status_code == 413


def test_api_tts_size_guard_accepts_content_length_within_limit():
    from kokoro_tts.routes.audio import _enforce_request_size_limit

    req = _make_request_with_headers([(b"content-length", b"512")])
    _enforce_request_size_limit(req, 1024)
