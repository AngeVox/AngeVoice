"""ZipVoice CUDA provider routing and managed artifact integrity contract."""

import hashlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoro_tts.config import TTSConfig
from kokoro_tts.engines.registry import EngineRegistry
from kokoro_tts.zipvoice.assets import ZipVoiceAssetIntegrityError, ZipVoiceAssetManager
from kokoro_tts.zipvoice.engine import ZipVoiceEngine


def _cfg(tmp_path: Path, *, provider: str = "cuda", fallback: bool = True) -> TTSConfig:
    return TTSConfig(
        enabled_models=["zipvoice"], default_model="zipvoice",
        zipvoice_execution_provider=provider, zipvoice_cuda_enabled=provider == "cuda",
        zipvoice_auto_fallback_cpu=fallback,
        zipvoice_model_root=tmp_path / "models/zipvoice",
        zipvoice_distill_dir=tmp_path / "models/zipvoice/zipvoice_distill",
        zipvoice_vocos_dir=tmp_path / "models/zipvoice/vocos-mel-24khz",
        zipvoice_profiles_dir=tmp_path / "prompts/zipvoice",
    )


def _asset_cfg(tmp_path: Path, *, download_enabled: bool = True) -> SimpleNamespace:
    root = tmp_path / "models" / "zipvoice"
    return SimpleNamespace(
        zipvoice_model_root=root,
        zipvoice_distill_dir=root / "zipvoice_distill",
        zipvoice_vocos_dir=root / "vocos-mel-24khz",
        zipvoice_download_enabled=download_enabled,
    )


def _asset_item(
    *, asset_id: str = "model", sha256: str | None, filename: str = "zipvoice_distill/model.pt", install_root: str = "model_root"
) -> dict:
    return {
        "id": asset_id,
        "repo": "k2-fsa/ZipVoice",
        "revision": "test-immutable-revision",
        "license": "Apache-2.0",
        "filename": filename,
        "install_root": install_root,
        "destination": filename,
        "sha256": sha256,
        "verification_policy": "strict_sha256" if sha256 else "record_first_verified_download",
    }


def _asset_manager(tmp_path: Path, item: dict, *, download_enabled: bool = True) -> tuple[ZipVoiceAssetManager, Path]:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": 1, "runtime": "test", "assets": [item]}), encoding="utf-8")
    cfg = _asset_cfg(tmp_path, download_enabled=download_enabled)
    root = cfg.zipvoice_model_root if item["install_root"] == "model_root" else cfg.zipvoice_vocos_dir
    return ZipVoiceAssetManager(cfg, manifest_path=manifest_path), root / item["destination"]


def _install_fake_downloader(monkeypatch, callback):
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(hf_hub_download=callback))


def _production_cuda_assets() -> dict[str, dict]:
    root = Path(__file__).resolve().parents[1] / "src/kokoro_tts/zipvoice"
    return {item["id"]: item for item in json.loads((root / "assets_manifest_cuda.json").read_text(encoding="utf-8"))["assets"]}


def test_registry_exposes_zipvoice_cuda_under_stable_product_name_without_new_public_model(tmp_path):
    cfg = _cfg(tmp_path)
    spec = EngineRegistry().list_specs(cfg)[0]
    assert spec.id == "zipvoice"
    assert spec.provider == "cuda"
    assert spec.backend == "zipvoice-distill-pytorch-cuda"
    assert spec.name == "ZipVoice"
    assert spec.experimental is False


def test_zipvoice_cuda_load_failure_falls_back_to_frozen_cpu_runtime(tmp_path, monkeypatch):
    engine = ZipVoiceEngine(_cfg(tmp_path), requested_provider="cuda")

    def fail_cuda():
        raise RuntimeError("CUDA unavailable for test")

    def load_cpu():
        engine._cpu_runtime.loaded = True
        return engine._cpu_runtime

    monkeypatch.setattr(engine._cuda_runtime, "load", fail_cuda)
    monkeypatch.setattr(engine._cuda_runtime, "unload", lambda: None)
    monkeypatch.setattr(engine._cpu_runtime, "load", load_cpu)
    monkeypatch.setattr(engine._cpu_runtime.assets, "status", lambda: {"ready": True, "status_file": "status.json"})

    engine.load()
    metadata = engine.metadata()
    assert metadata["requested_provider"] == "cuda"
    assert metadata["actual_provider"] == "cpu_onnx_int8"
    assert metadata["fallback"] is True
    assert "CUDA unavailable for test" in metadata["fallback_reason"]
    assert metadata["provider_fallback"] is True


def test_zipvoice_isolated_cuda_metadata_does_not_treat_fallback_capability_as_active_fallback(tmp_path, monkeypatch):
    engine = ZipVoiceEngine(_cfg(tmp_path), requested_provider="cuda", process_isolation=True)

    class DummyWorker:
        is_loaded = True
        is_healthy = True
        alive = True
        pid = 1234
        last_exit_reason = ""
        last_metadata = {}

        def load(self, *, timeout):
            self.last_metadata = {
                "actual_provider": "cuda_pytorch",
                "provider_fallback": True,
                "fallback": False,
                "fallback_reason": "",
            }
            return self.last_metadata

    engine._worker = DummyWorker()
    monkeypatch.setattr(engine.assets, "status", lambda: {"ready": True, "status_file": "status.json"})

    engine.load()
    metadata = engine.metadata()
    assert metadata["requested_provider"] == "cuda"
    assert metadata["actual_provider"] == "cuda_pytorch"
    assert metadata["fallback"] is False
    assert metadata["fallback_reason"] == ""
    assert metadata["provider_fallback"] is True


def test_zipvoice_cuda_asset_manifest_adds_checkpoint_without_altering_cpu_manifest():
    root = Path(__file__).resolve().parents[1] / "src/kokoro_tts/zipvoice"
    cpu = (root / "assets_manifest.json").read_text(encoding="utf-8")
    cuda = (root / "assets_manifest_cuda.json").read_text(encoding="utf-8")
    assets = _production_cuda_assets()
    assert "model.pt" not in cpu
    assert "model.pt" in cuda
    assert "PyTorch CUDA" in cuda
    assert "Experimental" not in cuda
    assert assets["zipvoice_distill_model_pt"]["sha256"] == "745855037478eb888cfa7a3603c1aa9f663f22a72d94cc1c37787228ff422095"
    assert assets["zipvoice_distill_model_pt"]["verification_policy"] == "strict_sha256"
    assert assets["zipvoice_distill_model_pt"]["revision"] == "3baef9f2f52009cac656f4f8445b6e8f618a8235"
    assert assets["vocos_weights"]["revision"] == "a91e656a21df4e98ed0640ece71211deadd67933"
    assert assets["vocos_weights"]["sha256"] == "97ec976ad1fd67a33ab2682d29c0ac7df85234fae875aefcc5fb215681a91b2a"
    assert assets["vocos_weights"]["verification_policy"] == "strict_sha256"


def test_declared_existing_mismatch_fails_closed_without_download_or_status_write(tmp_path, monkeypatch):
    expected = hashlib.sha256(b"expected-model").hexdigest()
    manager, destination = _asset_manager(tmp_path, _asset_item(sha256=expected))
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"tampered-model")
    before = destination.read_bytes()
    calls = []
    _install_fake_downloader(monkeypatch, lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ZipVoiceAssetIntegrityError, match="declared"):
        manager.ensure()
    assert calls == []
    assert destination.read_bytes() == before
    assert not manager.status_path.exists()


def test_declared_existing_asset_is_verified_without_download(tmp_path, monkeypatch):
    payload = b"verified-model"
    manager, destination = _asset_manager(tmp_path, _asset_item(sha256=hashlib.sha256(payload).hexdigest()))
    destination.parent.mkdir(parents=True)
    destination.write_bytes(payload)
    calls = []
    _install_fake_downloader(monkeypatch, lambda **kwargs: calls.append(kwargs))
    result = manager.ensure()
    saved = json.loads(manager.status_path.read_text(encoding="utf-8"))
    assert calls == []
    assert result["ready"] is True
    assert saved["files"]["model"]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_missing_declared_asset_downloads_once_and_verifies_manifest_identity(tmp_path, monkeypatch):
    payload = b"downloaded-model"
    item = _asset_item(sha256=hashlib.sha256(payload).hexdigest())
    manager, destination = _asset_manager(tmp_path, item)
    calls = []

    def download(*, repo_id, filename, revision, local_dir):
        calls.append((repo_id, filename, revision, local_dir))
        output = Path(local_dir) / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        return str(output)

    _install_fake_downloader(monkeypatch, download)
    assert manager.ensure()["ready"] is True
    assert destination.read_bytes() == payload
    assert calls == [(item["repo"], item["filename"], item["revision"], str(manager.model_root))]


def test_downloaded_declared_mismatch_preserves_artifact_without_retry_or_status(tmp_path, monkeypatch):
    expected = hashlib.sha256(b"expected-model").hexdigest()
    manager, destination = _asset_manager(tmp_path, _asset_item(sha256=expected))
    calls = []

    def download(*, local_dir, filename, **_kwargs):
        calls.append("download")
        output = Path(local_dir) / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"wrong-model")
        return str(output)

    _install_fake_downloader(monkeypatch, download)
    with pytest.raises(ZipVoiceAssetIntegrityError, match="declared"):
        manager.ensure()
    assert calls == ["download"]
    assert destination.read_bytes() == b"wrong-model"
    assert not manager.status_path.exists()


def test_manifest_declared_digest_overrides_forged_status_digest(tmp_path, monkeypatch):
    declared_payload = b"declared-model"
    forged_payload = b"forged-model"
    manager, destination = _asset_manager(tmp_path, _asset_item(sha256=hashlib.sha256(declared_payload).hexdigest()))
    destination.parent.mkdir(parents=True)
    destination.write_bytes(forged_payload)
    manager.status_path.write_text(json.dumps({"files": {"model": {"sha256": hashlib.sha256(forged_payload).hexdigest(), "verification_status": "verified"}}}), encoding="utf-8")
    calls = []
    _install_fake_downloader(monkeypatch, lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ZipVoiceAssetIntegrityError, match="declared"):
        manager.ensure()
    assert calls == []
    assert destination.read_bytes() == forged_payload


def test_declared_vocos_mismatch_uses_same_fail_closed_verifier(tmp_path, monkeypatch):
    expected = hashlib.sha256(b"expected-vocos").hexdigest()
    item = _asset_item(asset_id="vocos_weights", sha256=expected, filename="pytorch_model.bin", install_root="vocos_dir")
    manager, destination = _asset_manager(tmp_path, item)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"wrong-vocos")
    calls = []
    _install_fake_downloader(monkeypatch, lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ZipVoiceAssetIntegrityError, match="declared"):
        manager.ensure()
    assert calls == []
    assert destination.read_bytes() == b"wrong-vocos"


def test_existing_undeclared_metadata_downloads_once_before_learning_digest(tmp_path, monkeypatch):
    manager, destination = _asset_manager(tmp_path, _asset_item(asset_id="tokens", sha256=None, filename="zipvoice_distill/tokens.txt"))
    destination.parent.mkdir(parents=True)
    untrusted = b"untrusted-local-tokens"
    trusted = b"trusted-downloaded-tokens"
    destination.write_bytes(untrusted)
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        output = Path(kwargs["local_dir"]) / kwargs["filename"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(trusted)
        return str(output)

    _install_fake_downloader(monkeypatch, download)
    result = manager.ensure()
    saved = json.loads(manager.status_path.read_text(encoding="utf-8"))["files"]["tokens"]
    assert calls == [{
        "repo_id": "k2-fsa/ZipVoice",
        "filename": "zipvoice_distill/tokens.txt",
        "revision": "test-immutable-revision",
        "local_dir": str(manager.model_root),
        "force_download": True,
    }]
    assert result["ready"] is True
    assert saved["sha256"] == hashlib.sha256(trusted).hexdigest()
    assert saved["sha256"] != hashlib.sha256(untrusted).hexdigest()


def test_existing_undeclared_metadata_is_unverifiable_when_downloads_disabled(tmp_path):
    manager, destination = _asset_manager(
        tmp_path, _asset_item(asset_id="tokens", sha256=None, filename="zipvoice_distill/tokens.txt"), download_enabled=False
    )
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"untrusted-local-tokens")
    before = destination.read_bytes()
    with pytest.raises(FileNotFoundError, match="unavailable or unverifiable"):
        manager.ensure()
    assert destination.read_bytes() == before
    assert not manager.status_path.exists()


def test_missing_undeclared_metadata_download_does_not_force_refresh(tmp_path, monkeypatch):
    manager, destination = _asset_manager(tmp_path, _asset_item(asset_id="tokens", sha256=None, filename="zipvoice_distill/tokens.txt"))
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        output = Path(kwargs["local_dir"]) / kwargs["filename"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"first-downloaded-tokens")
        return str(output)

    _install_fake_downloader(monkeypatch, download)
    assert manager.ensure()["ready"] is True
    assert destination.read_bytes() == b"first-downloaded-tokens"
    assert len(calls) == 1
    assert "force_download" not in calls[0]


def test_existing_undeclared_metadata_reuses_matching_recorded_digest(tmp_path, monkeypatch):
    payload = b"recorded-tokens"
    digest = hashlib.sha256(payload).hexdigest()
    manager, destination = _asset_manager(tmp_path, _asset_item(asset_id="tokens", sha256=None, filename="zipvoice_distill/tokens.txt"))
    destination.parent.mkdir(parents=True)
    destination.write_bytes(payload)
    manager.status_path.write_text(json.dumps({"files": {"tokens": {"sha256": digest, "verification_status": "verified"}}}), encoding="utf-8")
    calls = []
    _install_fake_downloader(monkeypatch, lambda **kwargs: calls.append(kwargs))
    assert manager.ensure()["ready"] is True
    assert calls == []
    assert json.loads(manager.status_path.read_text(encoding="utf-8"))["files"]["tokens"]["sha256"] == digest


def test_existing_undeclared_metadata_rejects_mismatched_recorded_digest(tmp_path, monkeypatch):
    expected = hashlib.sha256(b"recorded-tokens").hexdigest()
    manager, destination = _asset_manager(tmp_path, _asset_item(asset_id="tokens", sha256=None, filename="zipvoice_distill/tokens.txt"))
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"tampered-tokens")
    manager.status_path.write_text(json.dumps({"files": {"tokens": {"sha256": expected, "verification_status": "verified"}}}), encoding="utf-8")
    status_before = manager.status_path.read_bytes()
    file_before = destination.read_bytes()
    calls = []
    _install_fake_downloader(monkeypatch, lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ZipVoiceAssetIntegrityError, match="recorded"):
        manager.ensure()
    assert calls == []
    assert destination.read_bytes() == file_before
    assert manager.status_path.read_bytes() == status_before


def test_cuda_asset_integrity_failure_prevents_vendor_checkpoint_loading(tmp_path, monkeypatch):
    from kokoro_tts.zipvoice.runtime_cuda_torch import ZipVoiceTorchCudaRuntime

    cfg = _cfg(tmp_path)
    cfg.zipvoice_repo_path = tmp_path / "vendor"
    (cfg.zipvoice_repo_path / "zipvoice").mkdir(parents=True)
    runtime = ZipVoiceTorchCudaRuntime(cfg)
    calls = {"model": 0, "checkpoint": 0}

    class FakeModel:
        def __init__(self, *_args, **_kwargs):
            calls["model"] += 1

    def fake_checkpoint(**_kwargs):
        calls["checkpoint"] += 1

    modules = {
        "zipvoice": types.ModuleType("zipvoice"),
        "zipvoice.bin": types.ModuleType("zipvoice.bin"),
        "zipvoice.bin.infer_zipvoice": types.SimpleNamespace(get_vocoder=lambda *_args: None, generate_sentence=lambda **_kwargs: None),
        "zipvoice.models": types.ModuleType("zipvoice.models"),
        "zipvoice.models.zipvoice_distill": types.SimpleNamespace(ZipVoiceDistill=FakeModel),
        "zipvoice.tokenizer": types.ModuleType("zipvoice.tokenizer"),
        "zipvoice.tokenizer.tokenizer": types.SimpleNamespace(EmiliaTokenizer=object),
        "zipvoice.utils": types.ModuleType("zipvoice.utils"),
        "zipvoice.utils.checkpoint": types.SimpleNamespace(load_checkpoint=fake_checkpoint),
        "zipvoice.utils.feature": types.SimpleNamespace(VocosFbank=object),
        "torch": types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True, device_count=lambda: 1)),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(runtime.assets, "ensure", lambda: (_ for _ in ()).throw(ZipVoiceAssetIntegrityError("model.pt mismatch")))
    with pytest.raises(ZipVoiceAssetIntegrityError, match="model.pt mismatch"):
        runtime.load()
    assert calls == {"model": 0, "checkpoint": 0}
    assert runtime.model is None


def test_zipvoice_cuda_synthesis_runtime_error_retries_cpu_and_records_fallback(tmp_path, monkeypatch):
    engine = ZipVoiceEngine(_cfg(tmp_path), requested_provider="cuda")
    engine._cuda_runtime.loaded = True
    engine.runtime = engine._cuda_runtime
    engine._actual_provider = "cuda_pytorch"

    monkeypatch.setattr(engine._cuda_runtime, "synthesize", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("CUDA out of memory")))
    monkeypatch.setattr(engine._cuda_runtime, "unload", lambda: setattr(engine._cuda_runtime, "loaded", False))
    monkeypatch.setattr(engine._cpu_runtime, "load", lambda: setattr(engine._cpu_runtime, "loaded", True) or engine._cpu_runtime)
    monkeypatch.setattr(engine._cpu_runtime, "synthesize", lambda **_kwargs: b"RIFFcpu-fallback")
    monkeypatch.setattr(engine._cpu_runtime.assets, "status", lambda: {"ready": True, "status_file": "status.json"})

    result = engine.synthesize("测试", prompt_audio_path="prompt.wav", prompt_text="参考文本")
    metadata = engine.metadata()
    assert result == b"RIFFcpu-fallback"
    assert metadata["requested_provider"] == "cuda"
    assert metadata["actual_provider"] == "cpu_onnx_int8"
    assert metadata["fallback"] is True
    assert "CUDA synthesis failed" in metadata["fallback_reason"]
    assert "out of memory" in metadata["fallback_reason"]


def test_zipvoice_cuda_unloaded_metadata_does_not_claim_actual_cuda(tmp_path, monkeypatch):
    engine = ZipVoiceEngine(_cfg(tmp_path), requested_provider="cuda")
    monkeypatch.setattr(engine._cuda_runtime.assets, "status", lambda: {"ready": False, "status_file": "status.json"})
    metadata = engine.metadata()
    assert metadata["requested_provider"] == "cuda"
    assert metadata["actual_provider"] is None
    assert metadata["loaded"] is False
