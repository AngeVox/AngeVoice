"""AngeVoice 轻量单元测试。"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
EXPECTED_VERSION = "2.6.4.4"


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


class TestVersioning:
    def test_package_version_is_single_source(self):
        import kokoro_tts
        assert kokoro_tts.__version__ == EXPECTED_VERSION

    @pytest.mark.skipif(not _has_module("fastapi"), reason="fastapi not installed")
    def test_openapi_schema_uses_package_version(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.server import create_app
        app = create_app(config=TTSConfig(model_dir=tmp_path, enabled_models=["kokoro"], default_model="kokoro"))
        schema = app.openapi()
        assert schema["info"]["version"] == EXPECTED_VERSION
        assert "/v1/audio/batch" in schema["paths"]
        assert "/admin" in schema["paths"]


class TestConfig:
    def test_default_config(self):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.device == "auto"
        assert config.rate_limit_qps == 0.0
        assert config.max_queue_length == 0
        assert config.model_idle_timeout_seconds == 600
        assert config.model_idle_unload_current is True
        assert config.moss_process_isolation_enabled is True
        assert config.moss_process_isolation_providers == "cuda"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("KOKORO_PORT", "9000")
        monkeypatch.setenv("KOKORO_DEVICE", "cpu")
        monkeypatch.setenv("KOKORO_RATE_LIMIT_QPS", "2.5")
        monkeypatch.setenv("KOKORO_MAX_QUEUE_LENGTH", "3")
        monkeypatch.setenv("ANGEVOICE_IDLE_TIMEOUT_SECONDS", "30")
        monkeypatch.setenv("MOSS_PROCESS_ISOLATION_ENABLED", "false")
        from kokoro_tts.config import load_config
        config = load_config()
        assert config.port == 9000
        assert config.device == "cpu"
        assert config.rate_limit_qps == 2.5
        assert config.max_queue_length == 3
        assert config.model_idle_timeout_seconds == 30
        assert config.moss_process_isolation_enabled is False

    def test_moss_cuda_can_be_disabled(self):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu", "moss-nano-cuda"], default_model="moss-nano-cuda", moss_execution_provider="cuda", moss_cuda_enabled=False)
        config.validate_security()
        assert config.enabled_models == ["kokoro", "moss-nano-cpu"]
        assert config.default_model == "moss-nano-cpu"
        assert config.moss_execution_provider == "cpu"


class TestMossHelpers:
    def test_moss_output_postprocess_limits_peak(self):
        import numpy as np
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine
        engine = MossNanoEngine(TTSConfig(moss_output_target_peak=0.5))
        output = engine._postprocess_waveform(np.asarray([[1.2, -1.2], [0.1, -0.1]], dtype=np.float32))
        assert output.shape == (2, 2)
        assert float(np.max(np.abs(output))) <= 0.5001
        assert engine.metadata()["last_output_quality"]["scale"] < 1.0

    def test_moss_health_flags_and_executor_rebuild(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine
        engine = MossNanoEngine(TTSConfig())
        old_executor = engine._executor
        engine._loaded = True
        engine._unhealthy = True
        assert engine.is_healthy is False
        engine.unload()
        assert engine._unhealthy is False
        assert engine._consecutive_timeouts == 0
        assert engine._executor is not old_executor


class TestEngineManager:
    def test_switch_model_skips_unloading_busy_previous_model(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine_manager import EngineManager
        kokoro = MagicMock(); kokoro.is_loaded = True
        cfg = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu"], default_model="kokoro")
        manager = EngineManager(cfg, initial_engine=kokoro)
        manager._active_counts["kokoro"] = 1
        moss = MagicMock(); moss.is_loaded = True; moss.metadata.return_value = {"id": "moss-nano-cpu"}
        manager._engines["moss-nano-cpu"] = moss
        result = manager.switch_model("moss-nano-cpu", unload_previous=True, load=False)
        assert result["previous_busy"] is True
        assert result["unloaded_previous"] is False
        kokoro.unload.assert_not_called()

    def test_unload_inactive_can_include_current_model(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine_manager import EngineManager
        engine = MagicMock(); engine.is_loaded = True
        manager = EngineManager(TTSConfig(enabled_models=["kokoro"], default_model="kokoro"), initial_engine=engine)
        assert manager.unload_inactive(include_current=True) == ["kokoro"]
        engine.unload.assert_called_once()


class TestSecurityAndMiddleware:
    def test_admin_requires_password(self, monkeypatch):
        from kokoro_tts.config import TTSConfig
        monkeypatch.delenv("ANGEVOICE_ADMIN_PASSWORD", raising=False)
        with pytest.raises(ValueError, match="ANGEVOICE_ADMIN_PASSWORD"):
            TTSConfig(admin_enabled=True).validate_security()

    def test_placeholder_api_key_is_rejected(self):
        from kokoro_tts.config import TTSConfig
        with pytest.raises(ValueError, match="placeholder"):
            TTSConfig(api_key="CHANGE-ME-TO-A-REAL-SECRET-KEY").validate_security()

    @pytest.mark.skipif(not _has_module("fastapi"), reason="fastapi not installed")
    def test_rate_limit_middleware_initializes_and_limits(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from kokoro_tts.rate_limit import RateLimitMiddleware
        app = FastAPI(); app.add_middleware(RateLimitMiddleware, qps=0.01, burst=1)
        @app.get("/ping")
        def ping(): return {"ok": True}
        client = TestClient(app)
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 429


class TestServerAndCLI:
    @pytest.mark.skipif(not _has_module("fastapi"), reason="fastapi not installed")
    def test_create_app_with_rate_and_queue_config(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.server import create_app
        app = create_app(config=TTSConfig(model_dir=Path("/nonexistent"), rate_limit_qps=1.0, max_queue_length=2))
        assert app.title == "AngeVoice"

    def test_run_server_uses_import_string_for_workers(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.server import run_server
        config = TTSConfig(model_dir=Path("/nonexistent"), workers=2)
        with patch("uvicorn.run") as run:
            run_server(config)
        args, kwargs = run.call_args
        assert args[0] == "kokoro_tts.server:create_app"
        assert kwargs["factory"] is True
        assert kwargs["workers"] == 2


class TestMossSplitModules:
    def test_stream_budget_thresholds(self):
        from kokoro_tts.moss import StreamBudgetThresholds, resolve_stream_decode_frame_budget

        thresholds = StreamBudgetThresholds(low=0.25, mid=0.65, high=1.20)
        assert resolve_stream_decode_frame_budget(0, 48000, None, thresholds) == 1
        assert resolve_stream_decode_frame_budget(48000, 48000, 0.0, thresholds) in {1, 2, 4, 8}

    def test_text_segmentation_helper(self):
        from kokoro_tts.moss import segment_text

        segments = segment_text("第一句。第二句很长很长很长。", max_text_length=200, segment_length=8)
        assert segments
        assert all(len(item) <= 20 for item in segments)

    def test_prompt_cache_key_changes_with_file(self, tmp_path):
        from kokoro_tts.moss import prompt_audio_cache_key

        a = tmp_path / "a.wav"
        b = tmp_path / "b.wav"
        a.write_bytes(b"aaa")
        b.write_bytes(b"bbb")
        key_a = prompt_audio_cache_key(voice="Junhao", default_voice="Junhao", prompt_audio_path=str(a), max_seconds=8, sample_rate=48000, channels=2)
        key_b = prompt_audio_cache_key(voice="Junhao", default_voice="Junhao", prompt_audio_path=str(b), max_seconds=8, sample_rate=48000, channels=2)
        assert key_a != key_b


class TestP2Regressions:
    def test_health_status_uses_idle_for_idle_unloaded_current_model(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine_manager import EngineManager

        engine = MagicMock()
        engine.is_loaded = False
        engine.is_healthy = True
        manager = EngineManager(TTSConfig(enabled_models=["kokoro"], default_model="kokoro"), initial_engine=engine)
        manager._last_used["kokoro"] = 1.0
        snapshot = manager.current_snapshot()
        assert snapshot["idle_unloaded"] is True
        assert snapshot["loaded"] is False

    def test_moss_process_isolation_defaults_to_cuda_only(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine

        cfg = TTSConfig()
        cuda_engine = MossNanoEngine(cfg, execution_provider="cuda")
        cpu_engine = MossNanoEngine(cfg, execution_provider="cpu")
        assert cuda_engine._process_isolated is True
        assert cpu_engine._process_isolated is False
        cuda_engine._loaded = True
        cuda_engine._validate_request("你好", "Junhao", 1.0)

    def test_moss_process_isolation_can_be_disabled(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine

        cfg = TTSConfig(moss_process_isolation_enabled=False)
        assert MossNanoEngine(cfg, execution_provider="cuda")._process_isolated is False


class TestReviewFixRegressions:
    def test_bearer_token_prefix_is_case_insensitive(self):
        from kokoro_tts.security import _extract_bearer_token

        assert _extract_bearer_token("Bearer abc123") == "abc123"
        assert _extract_bearer_token("bearer abc123") == "abc123"
        assert _extract_bearer_token("BEARER abc123") == "abc123"
        assert _extract_bearer_token("Token abc123") == ""

    def test_batch_pcm_zip_filename_uses_pcm_extension(self):
        from kokoro_tts.service_extras import _safe_zip_filename

        assert _safe_zip_filename(None, 0, "pcm") == "speech_001.pcm"
        assert _safe_zip_filename("chapter-1", 0, "pcm") == "chapter-1.pcm"
        assert _safe_zip_filename("already.pcm", 0, "pcm") == "already.pcm"

    def test_request_cancel_state_remains_consistent(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.service_state import ServiceState

        state = ServiceState(TTSConfig(queue_status_enabled=True), MagicMock())
        state.mark_request("req1", "running")
        assert state.request_cancel("req1") is True
        assert state.is_cancelled("req1") is True
        state.finish_request("req1", "cancelled")
        assert state.is_cancelled("req1") is False
