from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kokoro_tts.config import TTSConfig
from kokoro_tts.engine_manager import EngineManager
from kokoro_tts.engines.registry import EngineRegistry
from kokoro_tts.service_state import ServiceState
from kokoro_tts.zipvoice.assets import ZipVoiceAssetManager, file_sha256
from kokoro_tts.zipvoice.profiles import ZipVoiceProfileStore
from tests.quality.test_i18n_contract import _catalog


def _cfg(tmp_path: Path) -> TTSConfig:
    return TTSConfig(
        enabled_models=["kokoro", "moss-nano-cpu", "zipvoice"],
        default_model="kokoro",
        moss_cuda_enabled=False,
        zipvoice_model_root=tmp_path / "models" / "zipvoice",
        zipvoice_distill_dir=tmp_path / "models" / "zipvoice" / "zipvoice_distill",
        zipvoice_vocos_dir=tmp_path / "models" / "zipvoice" / "vocos-mel-24khz",
        zipvoice_profiles_dir=tmp_path / "prompts" / "zipvoice",
        model_idle_timeout_seconds=0,
    )


def test_registry_exposes_zipvoice_capabilities_without_breaking_moss_alias(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.validate_security()
    manager = EngineManager(cfg)
    try:
        ids = [model["id"] for model in manager.list_models()]
        assert ids == ["kokoro", "moss", "zipvoice"]
        model = next(item for item in manager.list_models() if item["id"] == "zipvoice")
        assert model["requested_provider"] == "cpu"
        assert model["requires_prompt_audio"] is True
        assert model["requires_prompt_text"] is True
        assert model["supports_saved_voice_profiles"] is True
        assert model["stream_mode"] == "segmented"
        assert EngineRegistry().resolve("moss-nano-cpu").canonical_id == "moss"
    finally:
        manager.stop_idle_timer()


def test_zipvoice_cache_key_separates_prompt_profile_and_inference_params(tmp_path):
    manager = EngineManager(_cfg(tmp_path))
    state = ServiceState(_cfg(tmp_path), model_manager=manager)
    try:
        base = state.cache_key("zipvoice", "测试", "voice_001", 1.0, "wav", "audio", "文本一", "r1", {"zipvoice_num_steps": 8})
        assert base != state.cache_key("zipvoice", "测试", "voice_001", 1.0, "wav", "audio", "文本二", "r1", {"zipvoice_num_steps": 8})
        assert base != state.cache_key("zipvoice", "测试", "voice_001", 1.0, "wav", "audio", "文本一", "r2", {"zipvoice_num_steps": 8})
        assert base != state.cache_key("zipvoice", "测试", "voice_001", 1.0, "wav", "audio", "文本一", "r1", {"zipvoice_num_steps": 12})
    finally:
        manager.stop_idle_timer()


def test_profile_store_creates_exact_persistent_layout_and_revision(tmp_path):
    store = ZipVoiceProfileStore(_cfg(tmp_path))
    saved = store.save(voice_id="voice_001", name="测试音色", prompt_text="你好，欢迎体验我的声音。", audio_bytes=b"RIFF-test", filename="ref.wav")
    folder = tmp_path / "prompts" / "zipvoice" / "voice_001"
    assert (folder / "reference.wav").read_bytes() == b"RIFF-test"
    assert json.loads((folder / "profile.json").read_text(encoding="utf-8"))["revision"] == saved["revision"]
    assert store.load("voice_001")["prompt_text"] == "你好，欢迎体验我的声音。"
    assert store.list()[0]["voice_id"] == "voice_001"


def test_asset_manager_downloads_to_persistent_layout_and_writes_verification_status(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    manifest = {
        "schema_version": 1,
        "runtime": "test",
        "assets": [
            {"id": "text", "repo": "r", "revision": "pin", "license": "Apache-2.0", "filename": "zipvoice_distill/tokens.txt", "install_root": "model_root", "destination": "zipvoice_distill/tokens.txt", "sha256": None, "verification_policy": "record_first_verified_download"}
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    def fake_download(*, repo_id, filename, revision, local_dir):
        output = Path(local_dir) / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"tokens")
        return str(output)
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(hf_hub_download=fake_download))
    manager = ZipVoiceAssetManager(cfg, manifest_path=manifest_path)
    result = manager.ensure()
    path = cfg.zipvoice_model_root / "zipvoice_distill" / "tokens.txt"
    assert result["ready"] is True
    assert path.is_file()
    assert result["files"][0]["downloaded_sha256"] == file_sha256(path)
    assert (cfg.zipvoice_model_root / "assets_status.json").is_file()


def test_saved_profile_is_resolved_for_zipvoice_synthesis_and_cache_clear_is_observable(tmp_path):
    cfg = _cfg(tmp_path)
    manager = EngineManager(cfg)
    state = ServiceState(cfg, model_manager=manager)
    state.zipvoice_profiles.save(voice_id="voice_001", prompt_text="参考文本", audio_bytes=b"wav")
    fake = MagicMock()
    fake.is_loaded = True
    fake.is_healthy = True
    fake.sample_rate = 24000
    fake.metadata.return_value = {"voice_clone_supported": True, "modes": ["voice_clone"]}
    fake.synthesize.return_value = b"generated-audio"
    manager._engines["zipvoice"] = fake
    try:
        output, mime = state.synthesize_response_bytes("测试内容", "voice_001", 1.0, "wav", "zipvoice", generation_params={"zipvoice_num_steps": 8})
        assert output == b"generated-audio" and mime == "audio/wav"
        kwargs = fake.synthesize.call_args.kwargs
        assert kwargs["prompt_text"] == "参考文本"
        assert Path(kwargs["prompt_audio_path"]).as_posix().endswith("/voice_001/reference.wav")
        assert state.cache_size() == 1
        released = state.release_resources(clear_cache=True, unload_models=False)
        assert released["cleared_cache_items"] == 1
        assert released["after"]["cache_items"] == 0
        assert "rss_bytes" in released["after"]
    finally:
        manager.stop_idle_timer()


def test_vendored_zipvoice_inference_common_does_not_import_training_only_tensorboard(monkeypatch):
    """ONNX CPU 推理不应依赖训练界面栈。"""
    import builtins
    import importlib.util

    pytest.importorskip("torch")
    common_path = Path(__file__).parents[1] / "vendor" / "ZipVoice" / "zipvoice" / "utils" / "common.py"
    original_import = builtins.__import__

    def block_tensorboard(name, *args, **kwargs):
        if name == "torch.utils.tensorboard" or name.startswith("tensorboard"):
            raise ModuleNotFoundError("blocked tensorboard import for inference regression test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_tensorboard)
    spec = importlib.util.spec_from_file_location("zipvoice_common_no_tensorboard_test", common_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.AttributeDict({"ok": True}).ok is True


def test_unloaded_zipvoice_snapshot_retains_last_runtime_metrics_for_rss_evidence(tmp_path):
    cfg = _cfg(tmp_path)
    manager = EngineManager(cfg)
    engine = MagicMock()
    engine.is_loaded = False
    engine.is_healthy = True
    engine.metadata.return_value = {
        "loaded": False,
        "actual_provider": "cpu_onnx_int8",
        "last_generation_seconds": 4.2,
        "last_audio_seconds": 1.4,
        "last_rtf": 3.0,
    }
    manager._engines["zipvoice"] = engine
    try:
        snapshot = next(item for item in manager.list_models() if item["id"] == "zipvoice")
        assert snapshot["loaded"] is False
        assert snapshot["actual_provider"] == "cpu_onnx_int8"
        assert snapshot["last_generation_seconds"] == 4.2
        assert snapshot["last_audio_seconds"] == 1.4
        assert snapshot["last_rtf"] == 3.0
    finally:
        manager.stop_idle_timer()


def _wav_format_tag(payload: bytes) -> tuple[int, int, int, int]:
    import struct

    assert payload[:4] == b"RIFF" and payload[8:12] == b"WAVE"
    offset = 12
    while offset + 8 <= len(payload):
        chunk_id = payload[offset : offset + 4]
        size = struct.unpack_from("<I", payload, offset + 4)[0]
        body = offset + 8
        if chunk_id == b"fmt ":
            format_tag, channels, sample_rate, _byte_rate, _align, bits = struct.unpack_from("<HHIIHH", payload, body)
            return format_tag, channels, sample_rate, bits
        offset = body + size + (size % 2)
    raise AssertionError("WAV fmt chunk missing")


def test_zipvoice_public_wav_normalizer_converts_float_to_pcm16():
    from io import BytesIO

    import numpy as np
    import soundfile as sf

    from kokoro_tts.audio import normalize_wav_to_pcm16_bytes

    upstream = BytesIO()
    sf.write(upstream, np.array([0.0, 0.25, -0.25], dtype=np.float32), 24000, format="WAV", subtype="FLOAT")
    assert _wav_format_tag(upstream.getvalue())[0] == 3
    product_wav = normalize_wav_to_pcm16_bytes(upstream.getvalue(), expected_sample_rate=24000)
    assert _wav_format_tag(product_wav) == (1, 1, 24000, 16)


def test_zipvoice_runtime_synthesize_returns_pcm16_even_when_upstream_writes_float(tmp_path):
    import contextlib

    import numpy as np
    import soundfile as sf

    from kokoro_tts.zipvoice.runtime_cpu_onnx import ZipVoiceOnnxCpuRuntime

    runtime = ZipVoiceOnnxCpuRuntime(_cfg(tmp_path))
    runtime.loaded = True
    runtime.load = lambda: runtime
    runtime.torch = types.SimpleNamespace(inference_mode=lambda: contextlib.nullcontext())
    runtime.model = object()
    runtime.vocoder = object()
    runtime.tokenizer = object()
    runtime.feature_extractor = object()

    def fake_generate_sentence(**kwargs):
        sf.write(kwargs["save_path"], np.array([0.0, 0.2, -0.2], dtype=np.float32), 24000, format="WAV", subtype="FLOAT")
        return {"wav_seconds": 3 / 24000, "rtf": 0.5}

    runtime.generate_sentence = fake_generate_sentence
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"only-needs-to-exist-for-wrapper-test")
    output = runtime.synthesize(text="测试", prompt_audio_path=str(reference), prompt_text="参考")
    assert _wav_format_tag(output) == (1, 1, 24000, 16)


def test_resource_snapshot_exposes_cache_counters_for_nas_isolation_evidence(tmp_path):
    cfg = _cfg(tmp_path)
    manager = EngineManager(cfg)
    state = ServiceState(cfg, model_manager=manager)
    try:
        state.cache_set("one", (b"wav", "audio/wav"), text="test")
        assert state.cache_get("one") == (b"wav", "audio/wav")
        assert state.cache_get("missing") is None
        snapshot = state.resource_snapshot()
        assert snapshot["cache_items"] == 1
        assert snapshot["cache_hits"] == 1
        assert snapshot["cache_misses"] == 1
        assert "cache_skips" in snapshot
    finally:
        manager.stop_idle_timer()



def test_zipvoice_reference_preview_normalizes_float_wav_to_browser_safe_pcm16():
    from io import BytesIO

    import numpy as np
    import soundfile as sf

    from kokoro_tts.audio import normalize_browser_preview_wav_to_pcm16_bytes

    source = BytesIO()
    sf.write(source, np.column_stack([np.array([0.0, 0.15, -0.15], dtype=np.float32), np.array([0.0, 0.15, -0.15], dtype=np.float32)]), 48000, format="WAV", subtype="FLOAT")
    normalized = normalize_browser_preview_wav_to_pcm16_bytes(source.getvalue())
    assert _wav_format_tag(normalized) == (1, 1, 24000, 16)


def test_zipvoice_segmented_stream_emits_pcm_audio_chunks(tmp_path, monkeypatch):
    import base64
    from io import BytesIO

    import numpy as np
    import soundfile as sf

    from kokoro_tts.zipvoice.engine import ZipVoiceEngine

    engine = ZipVoiceEngine(_cfg(tmp_path))

    def fake_synthesize(text, voice="", speed=1.0, **kwargs):
        buffer = BytesIO()
        sf.write(buffer, np.array([0.0, 0.1, -0.1], dtype=np.float32), 24000, format="WAV", subtype="PCM_16")
        return buffer.getvalue()

    monkeypatch.setattr(engine, "synthesize", fake_synthesize)
    frames = list(engine.synthesize_stream(
        "第一句测试。第二句测试。",
        voice="voice_001",
        prompt_audio_path="/tmp/reference.wav",
        prompt_text="参考文本",
    ))
    assert frames[0]["type"] == "started"
    assert frames[0]["stream_mode"] == "segmented"
    assert frames[-1]["type"] == "done"
    assert frames[-1]["total_audio_chunks"] == 2
    audio_frames = [frame for frame in frames if frame["type"] == "audio"]
    assert audio_frames
    assert all(base64.b64decode(frame["data"]) for frame in audio_frames)


def test_zipvoice_segmented_stream_requires_prompt_context(tmp_path):
    from kokoro_tts.zipvoice.engine import ZipVoiceEngine

    engine = ZipVoiceEngine(_cfg(tmp_path))
    frames = list(engine.synthesize_stream("测试内容。", voice=""))
    assert frames[0]["type"] == "error"
    assert "参考音频" in frames[0]["message"]



def _float_wav_bytes(sample_rate: int = 24000) -> bytes:
    from io import BytesIO

    import numpy as np
    import soundfile as sf

    buffer = BytesIO()
    sf.write(buffer, np.array([0.0, 0.25, -0.25] * 4000, dtype=np.float32), sample_rate, format="WAV", subtype="FLOAT")
    return buffer.getvalue()


def test_zipvoice_reference_preview_route_returns_pcm16_wav(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from kokoro_tts.routes.zipvoice import create_zipvoice_router

    cfg = _cfg(tmp_path)
    manager = EngineManager(cfg)
    state = ServiceState(cfg, model_manager=manager)

    async def verify():
        return True

    app = FastAPI()
    app.include_router(create_zipvoice_router(state, verify))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/zipvoice/reference-preview",
                files={"reference_audio": ("reference.wav", _float_wav_bytes(), "audio/wav")},
            )
        assert response.status_code == 200
        assert response.headers["x-angevoice-audio-contract"] == "PCM16_MONO_24000"
        assert _wav_format_tag(response.content) == (1, 1, 24000, 16)
    finally:
        manager.stop_idle_timer()


def test_zipvoice_saved_profile_route_persists_and_serves_pcm16_reference(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from kokoro_tts.routes.zipvoice import create_zipvoice_router

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
                "/v1/zipvoice/profiles",
                data={"voice_id": "voice_preview", "name": "预览", "prompt_text": "这是参考文本。"},
                files={"reference_audio": ("reference.wav", _float_wav_bytes(), "audio/wav")},
            )
            preview = client.get("/v1/zipvoice/profiles/voice_preview/reference.wav")
        assert saved.status_code == 200
        assert preview.status_code == 200
        stored = (cfg.zipvoice_profiles_dir / "voice_preview" / "reference.wav").read_bytes()
        assert _wav_format_tag(stored) == (1, 1, 24000, 16)
        assert _wav_format_tag(preview.content) == (1, 1, 24000, 16)
    finally:
        manager.stop_idle_timer()



def test_zipvoice_websocket_segmented_stream_uses_saved_profile_context(tmp_path):
    import base64

    from fastapi.testclient import TestClient

    from kokoro_tts.server import create_app

    cfg = _cfg(tmp_path)
    cfg.stream_enabled = True
    initial = MagicMock()
    initial.is_loaded = True
    initial.is_healthy = True
    initial.get_voices.return_value = ["zm_010"]
    initial.default_voice = "zm_010"
    initial.metadata.return_value = {"id": "kokoro", "loaded": True, "voice_clone_supported": False}

    app = create_app(config=cfg, engine=initial)
    state = app.state.angevoice
    state.zipvoice_profiles.save(
        voice_id="voice_ws",
        prompt_text="这是对应的参考文本。",
        audio_bytes=b"RIFF-profile-reference",
    )
    class FakeZipVoiceStreamEngine:
        is_loaded = True
        is_healthy = True
        default_voice = "voice_ws"

        def __init__(self):
            self.kwargs = {}

        def metadata(self):
            return {"id": "zipvoice", "loaded": True, "voice_clone_supported": True}

        def synthesize_stream(self, text, voice="", speed=1.0, fmt="pcm_s16le", *, prompt_audio_path=None, prompt_text="", cancel_check=None):
            self.kwargs = {"prompt_audio_path": prompt_audio_path, "prompt_text": prompt_text}
            yield {"type": "started", "segments": 1, "sample_rate": 24000, "channels": 1, "format": "pcm_s16le", "stream_mode": "segmented"}
            yield {"type": "audio", "index": 0, "data": base64.b64encode(b"\\x00\\x00").decode("ascii"), "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}
            yield {"type": "done", "total_segments": 1, "total_audio_chunks": 1}

    stream_engine = FakeZipVoiceStreamEngine()
    state.model_manager._engines["zipvoice"] = stream_engine

    with TestClient(app) as client:
        with client.websocket_connect("/ws/v1/tts") as ws:
            ws.send_json({"text": "流式测试。", "model": "zipvoice", "voice": "voice_ws", "format": "pcm_s16le"})
            frames = [ws.receive_json(), ws.receive_json(), ws.receive_json()]
    assert [frame["type"] for frame in frames] == ["started", "audio", "done"]
    assert stream_engine.kwargs["prompt_text"] == "这是对应的参考文本。"
    assert Path(stream_engine.kwargs["prompt_audio_path"]).as_posix().endswith("/voice_ws/reference.wav")



def test_zipvoice_reference_preview_disables_stale_cache_and_sniffing(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from kokoro_tts.routes.zipvoice import create_zipvoice_router

    cfg = _cfg(tmp_path)
    manager = EngineManager(cfg)
    state = ServiceState(cfg, model_manager=manager)

    async def verify():
        return True

    app = FastAPI()
    app.include_router(create_zipvoice_router(state, verify))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/zipvoice/reference-preview",
                files={"reference_audio": ("reference.wav", _float_wav_bytes(), "audio/wav")},
            )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
    finally:
        manager.stop_idle_timer()


def test_zipvoice_frontend_uses_profile_display_names_and_normalized_preview_only():
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "src" / "kokoro_tts" / "static"
    js = (static / "app.js").read_text(encoding="utf-8")
    preview = (static / "studio" / "reference-audio-preview.js").read_text(encoding="utf-8")
    assert "name.textContent = displayVoiceName(voice);" in js
    assert "option.textContent = displayVoiceName(voice);" in js
    assert "profile?.name || voiceId" in js
    assert "replaceZipVoicePreviewBlob(state.promptAudioFile);" not in js
    assert "descriptor('studio.reference_audio.preparing')" in preview
    assert "descriptor('studio.reference_audio.media_failed', { code })" in preview


def test_segment_text_can_preserve_hard_sentence_boundaries_for_zipvoice_streaming():
    from kokoro_tts.text_segmenter import segment_text_natural

    text = "这是第一句。这里是第二句。最后是第三句。"
    default_segments = segment_text_natural(text, max_text_length=5000, segment_length=120)
    stream_segments = segment_text_natural(text, max_text_length=5000, segment_length=120, flush_sentence_boundaries=True)
    assert len(default_segments) == 1
    assert stream_segments == ["这是第一句。", "这里是第二句。", "最后是第三句。"]


def test_zipvoice_frontend_skips_protected_polling_without_token_and_resets_audio_source():
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "src" / "kokoro_tts" / "static"
    js = (static / "app.js").read_text(encoding="utf-8")
    preview = (static / "studio" / "reference-audio-preview.js").read_text(encoding="utf-8")
    assert "bootstrap.authRequired && ((!state.token && !state.hasCookieSession) || state.authRejected)" in js
    assert "const blob = await response.blob();" in preview
    assert "element.removeAttribute?.('src');" in preview
    assert "descriptor('studio.error.api_key_rotated')" in js


def test_zipvoice_preview_route_downmixes_and_resamples_48khz_stereo_for_browser(tmp_path):
    from io import BytesIO

    import numpy as np
    import soundfile as sf
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from kokoro_tts.routes.zipvoice import create_zipvoice_router

    cfg = _cfg(tmp_path)
    manager = EngineManager(cfg)
    state = ServiceState(cfg, model_manager=manager)

    async def verify():
        return True

    stereo = BytesIO()
    tone = np.sin(np.linspace(0, 20, 4800, dtype=np.float32)) * 0.1
    sf.write(stereo, np.column_stack([tone, tone]), 48000, format="WAV", subtype="PCM_16")
    app = FastAPI()
    app.include_router(create_zipvoice_router(state, verify))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/zipvoice/reference-preview",
                files={"reference_audio": ("stereo48.wav", stereo.getvalue(), "audio/wav")},
            )
        assert response.status_code == 200
        assert response.headers["x-angevoice-audio-contract"] == "PCM16_MONO_24000"
        assert _wav_format_tag(response.content) == (1, 1, 24000, 16)
    finally:
        manager.stop_idle_timer()



def test_zipvoice_saved_profile_wins_over_stale_uploaded_reference_and_prompt_text(tmp_path):
    """选择保存音色后，残留的临时参考输入不得污染生成条件。"""
    cfg = _cfg(tmp_path)
    manager = EngineManager(cfg)
    state = ServiceState(cfg, model_manager=manager)
    state.zipvoice_profiles.save(
        voice_id="voice_saved",
        name="已保存音色",
        prompt_text="保存音色自己的参考文本",
        audio_bytes=b"RIFF-saved",
    )
    try:
        resolved = state._zipvoice_prompt_context(
            "zipvoice",
            "voice_saved",
            "/tmp/stale-upload.wav",
            "stale-audio-id",
            "页面残留的临时参考文本",
        )
        assert Path(resolved[0]).as_posix().endswith("/voice_saved/reference.wav")
        assert resolved[1].startswith("profile:voice_saved:")
        assert resolved[2] == "保存音色自己的参考文本"
        assert resolved[3]
    finally:
        manager.stop_idle_timer()


def test_zipvoice_frontend_preview_is_not_reloaded_by_status_poll_and_saved_voice_does_not_send_page_prompt():
    """播放器不得被状态轮询反复重载，保存音色不得携带页面临时参考文本。"""
    static = Path(__file__).resolve().parents[1] / "src" / "kokoro_tts" / "static"
    js = (static / "app.js").read_text(encoding="utf-8")
    stream_synthesis = (static / "studio" / "stream-synthesis.js").read_text(encoding="utf-8")
    preview = (static / "studio" / "reference-audio-preview.js").read_text(encoding="utf-8")
    assert "state.lastAppliedModelId !== model.id" in js
    assert "loadZipVoiceProfiles({ forcePreview: modelChanged })" in js
    assert "nextSourceKey === sourceKey" in preview
    assert "activeRequest?.sourceKey === nextSourceKey" in preview
    assert "streamSynthesisSnapshot" in js
    assert "createStreamSynthesisController" in js
    assert "promptText: els.promptText.value.trim()" in js
    assert "snapshot.requiresPromptText" in stream_synthesis
    assert "!snapshot.voice" in stream_synthesis
    assert "promptAudio" in stream_synthesis
    assert "payload.prompt_text = snapshot.promptText" in stream_synthesis
    assert "modelRequiresPromptText(currentModel()) && !voice && promptAudio" not in js
    assert "payload.prompt_text = els.promptText.value.trim()" not in js
    assert "isZipVoice" not in js
    assert "t('studio.preview.generate')" in js
    assert _catalog("zh-cn")["studio.preview.generate"] == "生成示例音频"
    assert _catalog("en")["studio.preview.generate"] == "Generate sample audio"


def test_zipvoice_ui_explains_reference_text_is_not_target_text():
    """界面必须明确区分参考文本和合成正文，降低误操作风险。"""
    html = (Path(__file__).resolve().parents[1] / "src" / "kokoro_tts" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "参考文本仅用于描述参考录音和克隆音色" in html
    assert "正文请填写在上方“合成文本”区域" in html
