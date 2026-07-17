"""Unified CPU/GPU/legacy image contracts and deployment contract tests."""

from pathlib import Path
import subprocess
import zipfile
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from kokoro_tts.config import TTSConfig
from kokoro_tts.server import create_app


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_all_compose_profiles_share_persistent_state_contract_and_zipvoice_provider_policy():
    root = _root()
    expected_mounts = ["/app/models", "/app/prompts", "/app/outputs", "/app/credentials", "/app/config", "/app/logs"]
    for profile in ("cpu", "gpu", "legacy-gpu"):
        compose = (root / f"docker/{profile}/docker-compose.yml").read_text(encoding="utf-8")
        assert f"angevoice-{profile}:v2.6.616" in compose
        assert f"ANGEVOICE_DEPLOYMENT_PROFILE: {profile}" in compose
        assert "zipvoice" in compose
        for mount in expected_mounts:
            assert mount in compose
    gpu = (root / "docker/gpu/docker-compose.yml").read_text(encoding="utf-8")
    legacy = (root / "docker/legacy-gpu/docker-compose.yml").read_text(encoding="utf-8")
    assert "ANGEVOICE_ENABLED_MODELS: kokoro,moss,zipvoice" in gpu
    assert 'MOSS_EXECUTION_PROVIDER: cuda' in gpu
    assert 'ZIPVOICE_EXECUTION_PROVIDER: cuda' in gpu
    assert 'ZIPVOICE_CUDA_ENABLED: "true"' in gpu
    assert "moss-nano-cuda" not in legacy and 'MOSS_EXECUTION_PROVIDER: cpu' in legacy
    assert 'ZIPVOICE_EXECUTION_PROVIDER: cpu' in legacy
    assert 'ZIPVOICE_CUDA_ENABLED: "false"' in legacy


def test_gpu_dockerfiles_bundle_zipvoice_cuda_adapter_and_cpu_fallback_without_overwriting_onnxruntime_gpu():
    root = _root()
    for profile in ("gpu", "legacy-gpu"):
        dockerfile = (root / f"docker/{profile}/Dockerfile").read_text(encoding="utf-8")
        assert "ARG INSTALL_ZIPVOICE=true" in dockerfile
        assert "COPY vendor/ZipVoice/ /opt/ZipVoice/" in dockerfile
        assert "CPUExecutionProvider" in dockerfile
        assert '.[zipvoice]' not in dockerfile
        assert "不额外安装 onnxruntime CPU 包" in dockerfile
    gpu = (root / "docker/gpu/Dockerfile").read_text(encoding="utf-8")
    assert "runtime_cuda_torch" in gpu
    assert "支持 PyTorch CUDA runtime" in gpu


def test_container_workflow_builds_arm64_cpu_and_publishes_latest_only_for_release_tags():
    workflow = (_root() / ".github/workflows/container.yml").read_text(encoding="utf-8")
    assert "branches: ['dev/**', 'release/**']" in workflow
    assert "workflow_dispatch" in workflow
    assert "type=raw,value=latest,enable=${{ steps.publish.outputs.release == 'true' }}" in workflow
    assert "startsWith(github.ref, 'refs/tags/v')" in workflow
    assert "Branch push built images without publishing" in workflow
    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "platforms: ${{ matrix.platforms }}" in workflow
    smoke = (_root() / ".github/workflows/docker-smoke.yml").read_text(encoding="utf-8")
    assert "cpu-arm64-build" in smoke
    assert "platforms: linux/arm64" in smoke
    cpu_dockerfile = (_root() / "docker/cpu/Dockerfile").read_text(encoding="utf-8")
    assert '"torch==${PYTORCH_VERSION}"' in cpu_dockerfile
    assert '"torchaudio==${PYTORCH_VERSION}"' in cpu_dockerfile
    assert '"torch==${PYTORCH_VERSION}+cpu"' not in cpu_dockerfile
    assert '"torchaudio==${PYTORCH_VERSION}+cpu"' not in cpu_dockerfile


def test_health_and_diagnostics_identify_runtime_deployment_profile(tmp_path):
    engine = MagicMock()
    engine.is_loaded = True
    engine.is_healthy = True
    engine.get_voices.return_value = ["zm_010"]
    engine.default_voice = "zm_010"
    engine.metadata.return_value = {"id": "kokoro", "loaded": True, "voice_clone_supported": False}
    cfg = TTSConfig(
        deployment_profile="gpu", enabled_models=["kokoro"], default_model="kokoro",
        output_dir=tmp_path / "outputs", credentials_dir=tmp_path / "credentials",
        admin_credentials_file=tmp_path / "credentials/admin-credentials.json",
        api_key_file=tmp_path / "credentials/.angevoice-api-key",
        runtime_config_file=tmp_path / "config/runtime-config.json",
        zipvoice_profiles_dir=tmp_path / "prompts/zipvoice",
        zipvoice_model_root=tmp_path / "models/zipvoice", model_idle_timeout_seconds=0,
    )
    app = create_app(config=cfg, engine=engine)
    try:
        with TestClient(app) as client:
            health = client.get("/health").json()
        assert health["deployment_profile"] == "gpu"
    finally:
        app.state.angevoice.model_manager.stop_idle_timer()


def test_admin_ui_exposes_first_entry_default_with_security_warning_and_inline_save_confirmation():
    root = _root()
    env_file = (root / "docker/angevoice.env").read_text(encoding="utf-8")
    html = (root / "src/kokoro_tts/templates/admin.html").read_text(encoding="utf-8")
    js = (root / "src/kokoro_tts/static/admin.js").read_text(encoding="utf-8")
    assert "KOKORO_ADMIN_ENABLED=true" in env_file
    assert "ANGEVOICE_ADMIN_USERNAME=admin" in env_file
    assert "ANGEVOICE_ADMIN_PASSWORD=admin123" in env_file
    assert "公网暴露前必须在安全页修改" in env_file
    smoke = (root / ".github/workflows/docker-smoke.yml").read_text(encoding="utf-8")
    assert "create_docker_admin_secret.py --quiet" not in smoke
    for profile in ("cpu", "gpu", "legacy-gpu"):
        compose = (root / f"docker/{profile}/docker-compose.yml").read_text(encoding="utf-8")
        assert "angevoice.local.env" in compose
        assert "required: false" in compose
    assert "confirm-admin-credentials-btn" in html
    credential_handler = js.split("$('save-admin-credentials-btn').onclick", 1)[1].split("$('download-diagnostics-btn')", 1)[0]
    assert "confirm(" not in credential_handler
    assert "toggleCredentialConfirmation" in credential_handler
    assert "credentials.save_failed" in credential_handler
