"""Product feature and packaging regression tests for stable public behavior."""

from __future__ import annotations

import base64
import json
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import soundfile as sf
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kokoro_tts.admin_credentials import AdminCredentialStore
from kokoro_tts.config import TTSConfig
from kokoro_tts.engine_manager import EngineManager
from kokoro_tts.routes.zipvoice import create_zipvoice_router
from kokoro_tts.service_state import ServiceState
from kokoro_tts.update_checker import UpdateChecker


def _cfg(tmp_path: Path) -> TTSConfig:
    return TTSConfig(
        enabled_models=["kokoro", "moss", "zipvoice"], default_model="kokoro",
        zipvoice_profiles_dir=tmp_path / "prompts/zipvoice",
        zipvoice_model_root=tmp_path / "models/zipvoice",
        zipvoice_distill_dir=tmp_path / "models/zipvoice/zipvoice_distill",
        zipvoice_vocos_dir=tmp_path / "models/zipvoice/vocos-mel-24khz",
        admin_credentials_file=tmp_path / "credentials/admin-credentials.json",
        model_idle_timeout_seconds=0,
    )


def _wav(seconds: float = 0.5) -> bytes:
    buffer = BytesIO()
    frames = max(1, int(24000 * seconds))
    sf.write(buffer, np.zeros(frames, dtype=np.float32), 24000, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def test_chinese_admin_username_is_persisted_as_hashed_credentials(tmp_path):
    cfg = _cfg(tmp_path)
    store = AdminCredentialStore(cfg)
    status = store.set_credentials("管理员01", "Strong-Pass-2026")
    assert status["persisted"] is True
    assert store.verify("管理员01", "Strong-Pass-2026") is True
    raw = cfg.admin_credentials_file.read_text(encoding="utf-8")
    assert "Strong-Pass-2026" not in raw


def test_stable_product_model_names_do_not_leak_runtime_provider(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.zipvoice_execution_provider = "cuda"
    cfg.zipvoice_cuda_enabled = True
    models = EngineManager(cfg).list_models()
    by_id = {item["id"]: item for item in models}
    assert by_id["moss"]["name"] == "MOSS-TTS-Nano"
    assert by_id["zipvoice"]["name"] == "ZipVoice"
    assert "CUDA" not in by_id["zipvoice"]["name"]
    assert "CPU" not in by_id["zipvoice"]["name"]
    assert by_id["zipvoice"]["requested_provider"] == "cuda"


def test_generic_voice_profile_route_can_save_preview_and_delete_without_zipvoice_route_branch(tmp_path):
    cfg = _cfg(tmp_path)
    manager = EngineManager(cfg)
    state = ServiceState(cfg, model_manager=manager)

    async def verify():
        return True

    app = FastAPI()
    app.include_router(create_zipvoice_router(state, verify))
    try:
        with TestClient(app) as client:
            saved = client.post(
                "/v1/voice-profiles/zipvoice",
                data={"voice_id": "1", "name": "霸总", "prompt_text": "这是参考文本。"},
                files={"reference_audio": ("reference.wav", _wav(), "audio/wav")},
            )
            assert saved.status_code == 200
            assert saved.json()["engine"] == "zipvoice"
            listed = client.get("/v1/voice-profiles?engine=zipvoice")
            assert listed.json()["profiles"][0]["voice_id"] == "1"
            renamed = client.patch("/v1/voice-profiles/zipvoice/1", json={"name": "霸总新版"})
            assert renamed.status_code == 200 and renamed.json()["profile"]["name"] == "霸总新版"
            preview = client.get("/v1/voice-profiles/zipvoice/1/reference.wav")
            assert preview.status_code == 200 and preview.headers["content-type"].startswith("audio/wav")
            prompts = client.get("/v1/reference-audio/zipvoice/recommended-prompts")
            assert prompts.status_code == 200 and prompts.json()["engine"] == "zipvoice"
            assert prompts.json()["items"]
            state.voice_profiles.register_recommended_prompts("zipvoice", ["新的通用提示词。"] )
            prompts_after_register = client.get("/v1/reference-audio/zipvoice/recommended-prompts")
            assert prompts_after_register.json()["items"] == ["新的通用提示词。"]
            deleted = client.delete("/v1/voice-profiles/zipvoice/1")
            assert deleted.json()["deleted"] is True
            assert not (cfg.zipvoice_profiles_dir / "1").exists()
    finally:
        manager.stop_idle_timer()


def test_zipvoice_allows_longer_reference_with_warning_but_rejects_over_product_limit(tmp_path):
    cfg = _cfg(tmp_path)
    assert cfg.zipvoice_prompt_audio_max_seconds == 15.0
    manager = EngineManager(cfg)
    state = ServiceState(cfg, model_manager=manager)

    async def verify():
        return True

    app = FastAPI()
    app.include_router(create_zipvoice_router(state, verify))
    try:
        with TestClient(app) as client:
            accepted = client.post(
                "/v1/voice-profiles/zipvoice",
                data={"voice_id": "long_ok", "name": "较长参考", "prompt_text": "这是参考文本。"},
                files={"reference_audio": ("reference.wav", _wav(4.0), "audio/wav")},
            )
            assert accepted.status_code == 200
            assert "官方建议" in accepted.json()["duration_warning"]
            preview = client.post(
                "/v1/reference-audio/zipvoice/preview",
                files={"reference_audio": ("reference.wav", _wav(4.0), "audio/wav")},
            )
            assert preview.status_code == 200
            assert preview.headers["X-AngeVoice-Reference-Warning"] == "exceeds-recommended-duration"
            rejected = client.post(
                "/v1/voice-profiles/zipvoice",
                data={"voice_id": "too_long", "prompt_text": "这是参考文本。"},
                files={"reference_audio": ("reference.wav", _wav(15.5), "audio/wav")},
            )
            assert rejected.status_code == 400
            assert "最长支持 15 秒" in rejected.json()["detail"]
            recommended = client.get("/v1/reference-audio/zipvoice/recommended-prompts")
            assert recommended.json()["recommended_duration_seconds"] == "<3"
            assert recommended.json()["maximum_duration_seconds"] == 15.0
    finally:
        manager.stop_idle_timer()


def test_api_docs_expose_zipvoice_http_examples_in_visible_navigation():
    root = Path(__file__).resolve().parents[1] / "src/kokoro_tts"
    html = (root / "templates/api_docs.html").read_text(encoding="utf-8")
    assert '<a href="#zipvoice-http">ZipVoice HTTP 克隆</a>' in html
    assert '<article class="doc-card" id="zipvoice-http">' in html
    assert 'model=zipvoice' in html
    assert 'prompt_audio=@reference.wav' in html
    assert 'response_format=telegram_voice' in html
    assert 'WebSocket 流式暂不输出 OGG/MP3/M4A' in html


def test_studio_recording_and_profile_delete_are_capability_driven():
    root = Path(__file__).resolve().parents[1] / "src/kokoro_tts"
    html = (root / "templates/index.html").read_text(encoding="utf-8")
    js = (root / "static/app.js").read_text(encoding="utf-8")
    imports = js[: js.index("const bootstrapEl")]
    assert 'id="record-reference-btn"' in html
    assert 'id="stop-record-reference-btn"' in html
    assert 'id="zipvoice-delete-profile"' in html
    assert 'id="zipvoice-update-profile"' in html
    assert 'id="zipvoice-toggle"' in html
    assert 'id="toast-stack"' in html
    assert "navigator.mediaDevices.getUserMedia" in js
    assert "window.isSecureContext" in js
    assert "showToast" in js and "setZipVoiceExpanded" in js
    assert "最长 15 秒" in js
    assert "encodeRecordedWav" in js
    assert "/v1/voice-profiles/${encodeURIComponent(profileEngineId())}" in js
    assert "modelSupportsProfiles()" in js
    assert "modelRequiresPromptText" in imports
    assert "modelRequiresPromptText(currentModel())" in js
    assert "modelSupportsVoiceClone(currentModel())" in js
    assert "deleteSelectedVoiceProfile" in js
    assert "updateSelectedVoiceProfileMetadata" in js
    assert "/v1/reference-audio/${encodeURIComponent(profileEngineId())}/recommended-prompts" in js
    assert "isZipVoice" not in js
    assert "const engineId = profileEngineId();" in js
    assert "profileEngineId() !== engineId" in js
    assert js.count("state.voices = state.zipvoiceProfiles.map(profile => profile.voice_id);") >= 2


def test_update_checker_reports_new_release_without_auto_update():
    class Response:
        def read(self):
            return json.dumps({
                "tag_name": "v9.9.9", "name": "Future release", "html_url": "https://github.com/angevox/AngeVoice/releases/tag/v9.9.9", "body": "notes"
            }).encode("utf-8")

    checker = UpdateChecker(TTSConfig(), opener=lambda *_args, **_kwargs: Response())
    status = checker.check(force=True)
    assert status["update_available"] is True
    assert status["latest_version"] == "9.9.9"
    assert status["auto_update"] is False


def test_version_and_fnos_wizards_expose_verified_profile_modes_and_safe_default_warning():
    from kokoro_tts import __version__
    assert __version__ == "2.6.616"
    root = Path(__file__).resolve().parents[1]
    install = json.loads((root / "packaging/fnos/AngeVoice/wizard/install").read_text(encoding="utf-8"))
    text = json.dumps(install, ensure_ascii=False)
    assert "NVIDIA GPU" in text and "legacy-gpu" in text and "CPU" in text
    assert "COMPOSE_PROFILES" in text and "wizard_run_mode" not in text and "wizard_container_runtime" not in text
    assert "admin123" in text and "公网暴露前必须完成修改" in text
    compose = (root / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml").read_text(encoding="utf-8")
    assert compose.count("profiles:") == 3
    assert 'profiles: ["cpu"]' in compose and 'profiles: ["gpu"]' in compose and 'profiles: ["legacy-gpu"]' in compose
    assert "angevoice-cpu:v2.6.616" in compose and "angevoice-gpu:v2.6.616" in compose and "angevoice-legacy-gpu:v2.6.616" in compose
    assert "${wizard_admin_password:-admin123}" in compose
    assert compose.count("${TRIM_PKGVAR}/credentials:/app/credentials") == 3
    assert compose.count("${TRIM_PKGVAR}/prompts:/app/prompts") == 3


def test_fnos_uses_verified_compose_profiles_and_release_workflow_uploads_fpk():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml").read_text(encoding="utf-8")
    install = (root / "packaging/fnos/AngeVoice/wizard/install").read_text(encoding="utf-8")
    callback = (root / "packaging/fnos/AngeVoice/cmd/install_callback").read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/container.yml").read_text(encoding="utf-8")
    assert compose.count("profiles:") == 3
    assert "angevoice-cpu:v2.6.616" in compose and "angevoice-gpu:v2.6.616" in compose and "angevoice-legacy-gpu:v2.6.616" in compose
    assert "COMPOSE_PROFILES" in install and "wizard_run_mode" not in install
    assert "COMPOSE_PROFILES" in callback and "wizard_run_mode" not in callback
    assert not (root / "packaging/fnos/AngeVoice/cmd/_mode_env.sh").exists()
    assert not (root / "packaging/fnos/AngeVoice/app/docker/.env").exists()
    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "Build fnOS FPK package and source archive" in workflow and '"dist/AngeVoice_v${VERSION}.fpk"' in workflow
    assert "release-assets:" in workflow
    assert "gh release upload" in workflow
    assert "scripts/build_source_release_zip.py" in workflow
    assert (root / "scripts/build_source_release_zip.py").exists()
