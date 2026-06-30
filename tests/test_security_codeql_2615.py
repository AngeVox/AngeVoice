from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kokoro_tts.prompt_audio import (
    PROMPT_AUDIO_STALE_SECONDS,
    cleanup_stale_prompt_audio_files,
    delete_prompt_audio_path,
    prompt_audio_temp_dir,
    save_prompt_audio_bytes,
)
from kokoro_tts.rate_limit import RateLimitMiddleware


def test_2615_prompt_audio_safe_delete_allows_only_generated_temp_files(monkeypatch, tmp_path):
    import kokoro_tts.prompt_audio as module

    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path))
    path, _digest = save_prompt_audio_bytes(
        content=b"prompt-audio",
        filename="sample.wav",
        request_id="reqsafe",
        max_bytes=1024,
    )
    prompt_path = Path(path)

    assert prompt_path.exists()
    assert prompt_path.parent == prompt_audio_temp_dir()
    assert delete_prompt_audio_path(prompt_path) is True
    assert not prompt_path.exists()
    assert delete_prompt_audio_path(prompt_path) is False


def test_2615_prompt_audio_safe_delete_rejects_outside_traversal_symlink_and_bad_names(monkeypatch, tmp_path):
    import kokoro_tts.prompt_audio as module

    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    root = prompt_audio_temp_dir()
    root.mkdir(parents=True)

    outside = tmp_path / "outside" / "reqsafe_0123456789abcdef.wav"
    outside.parent.mkdir()
    outside.write_bytes(b"outside")
    assert delete_prompt_audio_path(outside) is False
    assert outside.read_bytes() == b"outside"

    traversal = root / ".." / "outside" / outside.name
    assert delete_prompt_audio_path(traversal) is False
    assert outside.read_bytes() == b"outside"

    illegal_name = root / "manual.wav"
    illegal_name.write_bytes(b"manual")
    assert delete_prompt_audio_path(illegal_name) is False
    assert illegal_name.read_bytes() == b"manual"

    symlink = root / "reqsafe_0123456789abcdef.wav"
    try:
        symlink.symlink_to(outside)
    except OSError as exc:
        import pytest

        pytest.skip(f"current platform cannot create symlinks: {exc}")
    assert delete_prompt_audio_path(symlink) is False
    assert symlink.is_symlink()
    assert outside.read_bytes() == b"outside"


def test_2615_prompt_audio_stale_cleanup_remains_internal_root_only(monkeypatch, tmp_path):
    import kokoro_tts.prompt_audio as module

    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path))
    root = prompt_audio_temp_dir()
    root.mkdir()
    stale = root / "abandoned.wav"
    fresh = root / "fresh.wav"
    stale.write_bytes(b"old")
    fresh.write_bytes(b"new")
    old = time.time() - PROMPT_AUDIO_STALE_SECONDS - 10
    os.utime(stale, (old, old))

    assert cleanup_stale_prompt_audio_files(root) == 1
    assert not stale.exists()
    assert fresh.exists()


def _rate_limited_client() -> TestClient:
    app = FastAPI()

    @app.get("/")
    async def ok():
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, qps=0.001, burst=1)
    return TestClient(app)


def test_2615_rate_limit_logs_key_presence_not_x_api_key_or_token_fragments(caplog):
    token = "av_secret_token_abcdefghijklmnopqrstuvwxyz"
    caplog.set_level(logging.WARNING, logger="kokoro_tts.rate_limit")
    client = _rate_limited_client()

    assert client.get("/", headers={"x-api-key": token}).status_code == 200
    assert client.get("/", headers={"x-api-key": token}).status_code == 429

    log_text = caplog.text
    assert token not in log_text
    assert token[:6] not in log_text
    assert token[-4:] not in log_text
    assert "key:present" in log_text
    assert ("key_" + "hash:") not in log_text


def test_2615_rate_limit_logs_key_presence_not_bearer_token_or_token_fragments(caplog):
    token = "bearer_secret_token_1234567890"
    caplog.set_level(logging.WARNING, logger="kokoro_tts.rate_limit")
    client = _rate_limited_client()

    assert client.get("/", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/", headers={"Authorization": f"Bearer {token}"}).status_code == 429

    log_text = caplog.text
    assert token not in log_text
    assert token[:6] not in log_text
    assert token[-4:] not in log_text
    assert "Bearer" not in log_text
    assert "key:present" in log_text
    assert ("key_" + "hash:") not in log_text


def test_2615_studio_token_is_session_only_and_legacy_storage_is_cleared():
    app_js = (Path(__file__).resolve().parents[1] / "src" / "kokoro_tts" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert ("localStorage." + "getItem('angevoice.apiToken.v1')") not in app_js
    assert ("localStorage." + "setItem('angevoice.apiToken.v1'") not in app_js
    assert "localStorage.removeItem('angevoice.apiToken.v1')" in app_js
    assert "token: ''," in app_js
    assert "HttpOnly" in app_js
    assert "/v1/auth/session" in app_js
