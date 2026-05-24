"""ZipVoice CUDA provider routing and safe CPU fallback contract."""

from pathlib import Path

from kokoro_tts.config import TTSConfig
from kokoro_tts.engines.registry import EngineRegistry
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


def test_zipvoice_cuda_asset_manifest_adds_checkpoint_without_altering_cpu_manifest():
    root = Path(__file__).resolve().parents[1] / "src/kokoro_tts/zipvoice"
    cpu = (root / "assets_manifest.json").read_text(encoding="utf-8")
    cuda = (root / "assets_manifest_cuda.json").read_text(encoding="utf-8")
    assert "model.pt" not in cpu
    assert "model.pt" in cuda
    assert "PyTorch CUDA" in cuda
    assert "Experimental" not in cuda


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
