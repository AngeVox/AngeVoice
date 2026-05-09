"""AngeVoice lightweight unit tests.

These tests intentionally avoid loading the real Kokoro/MOSS model files so CI
can run on GitHub-hosted CPU runners. GPU/model-runtime behavior is covered by
manual E2E scripts.
"""

import base64
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


EXPECTED_VERSION = "2.6.4.3"


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
        assert "/admin/voices/upload" in schema["paths"]


class TestConfig:
    def test_default_config(self):
        from kokoro_tts.config import TTSConfig

        config = TTSConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.sample_rate == 24000
        assert config.device == "auto"
        assert config.stream_chunk_seconds == 0.50
        assert config.rate_limit_qps == 0.0
        assert config.max_queue_length == 0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("KOKORO_PORT", "9000")
        monkeypatch.setenv("KOKORO_HOST", "127.0.0.1")
        monkeypatch.setenv("KOKORO_DEVICE", "cpu")
        monkeypatch.setenv("KOKORO_STREAM_CHUNK_SECONDS", "0.2")
        monkeypatch.setenv("KOKORO_RATE_LIMIT_QPS", "2.5")
        monkeypatch.setenv("KOKORO_RATE_LIMIT_BURST", "7")
        monkeypatch.setenv("KOKORO_MAX_QUEUE_LENGTH", "3")

        from kokoro_tts.config import load_config

        config = load_config()
        assert config.port == 9000
        assert config.host == "127.0.0.1"
        assert config.device == "cpu"
        assert config.stream_chunk_seconds == 0.2
        assert config.rate_limit_qps == 2.5
        assert config.rate_limit_burst == 7
        assert config.max_queue_length == 3

    def test_function_params_override(self):
        from kokoro_tts.config import load_config

        config = load_config(port=3000, device="cuda")
        assert config.port == 3000
        assert config.device == "cuda"

    def test_voices_discovery(self, tmp_path):
        from kokoro_tts.config import TTSConfig

        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        (voices_dir / "zm_001.pt").touch()
        (voices_dir / "zm_002.pt").touch()

        config = TTSConfig(model_dir=tmp_path)
        assert config.get_voices() == ["zm_001", "zm_002"]
        assert config.model_file == tmp_path / "kokoro-v1_1-zh.pth"
        assert config.voices_dir == voices_dir

    def test_moss_cuda_can_be_disabled(self):
        from kokoro_tts.config import TTSConfig

        config = TTSConfig(
            enabled_models=["kokoro", "moss-nano-cpu", "moss-nano-cuda"],
            default_model="moss-nano-cuda",
            moss_execution_provider="cuda",
            moss_cuda_enabled=False,
        )
        config.validate_security()

        assert config.enabled_models == ["kokoro", "moss-nano-cpu"]
        assert config.default_model == "moss-nano-cpu"
        assert config.moss_execution_provider == "cpu"


class TestPromptAudioAndMossHelpers:
    def test_prompt_audio_base64_accepts_data_url(self):
        from kokoro_tts.prompt_audio import decode_prompt_audio_base64

        payload = base64.b64encode(b"fake-wav").decode("ascii")
        assert decode_prompt_audio_base64(payload) == b"fake-wav"
        assert decode_prompt_audio_base64(f"data:audio/wav;base64,{payload}") == b"fake-wav"

    def test_moss_output_postprocess_limits_peak(self):
        import numpy as np

        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine

        engine = MossNanoEngine(TTSConfig(moss_output_target_peak=0.5))
        output = engine._postprocess_waveform(np.asarray([[1.2, -1.2], [0.1, -0.1]], dtype=np.float32))

        assert output.shape == (2, 2)
        assert float(np.max(np.abs(output))) <= 0.5001
        assert engine.metadata()["last_output_quality"]["scale"] < 1.0

    def test_moss_stream_split_limits_chunk_duration(self):
        import numpy as np

        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine

        engine = MossNanoEngine(TTSConfig(moss_stream_chunk_seconds=0.01))
        chunks = list(engine._split_waveform_for_stream(np.zeros((5000, 2), dtype=np.float32)))

        assert len(chunks) == 3
        assert all(chunk.shape[0] <= 2400 for chunk in chunks)

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


class TestEngineAndText:
    def test_engine_not_loaded_and_clean_text(self):
        from kokoro_tts.engine import TTSEngine

        engine = TTSEngine()
        assert not engine.is_loaded
        assert engine._clean_text("hello\x00world") == "hello world"
        assert engine._clean_text("hello   world") == "hello world"
        assert engine._detect_language("你好世界") == "zh"

    def test_text_normalization_common_cases(self):
        from kokoro_tts.engine import normalize_text_for_tts

        assert normalize_text_for_tts("今天是2026-05-05。") == "今天是二零二六年五月五日。"
        assert normalize_text_for_tts("价格100元") == "价格一百元"
        assert normalize_text_for_tts("会议12:43开始") == "会议十二点四十三分开始"


class TestServiceStateAndEngineManager:
    def test_cache_key_includes_model_and_prompt_audio(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.service_state import ServiceState

        state = ServiceState(TTSConfig(), MagicMock())
        base_key = state.cache_key("moss-nano-cpu", "你好", "Junhao", 1.0, "wav")
        clone_key = state.cache_key("moss-nano-cpu", "你好", "Junhao", 1.0, "wav", "sha256:abc")
        kokoro_key = state.cache_key("kokoro", "你好", "Junhao", 1.0, "wav")

        assert base_key != clone_key
        assert kokoro_key != base_key

    def test_engine_manager_lists_enabled_models(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine_manager import EngineManager

        cfg = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu", "moss-nano-cuda"])
        cfg.validate_security()
        manager = EngineManager(cfg)

        models = manager.list_models()
        assert [item["id"] for item in models] == ["kokoro", "moss-nano-cpu", "moss-nano-cuda"]
        assert models[0]["current"] is True
        assert models[1]["voice_clone_supported"] is True

    def test_unload_model_rejects_busy_model_without_force(self):
        from fastapi import HTTPException
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine_manager import EngineManager

        engine = MagicMock()
        engine.is_loaded = True
        cfg = TTSConfig(enabled_models=["kokoro"], default_model="kokoro")
        manager = EngineManager(cfg, initial_engine=engine)
        manager._active_counts["kokoro"] = 1

        with pytest.raises(HTTPException) as exc_info:
            manager.unload_model("kokoro")
        assert exc_info.value.status_code == 409
        engine.unload.assert_not_called()

        assert manager.unload_model("kokoro", force=True) is True
        engine.unload.assert_called_once()

    def test_switch_model_skips_unloading_busy_previous_model(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine_manager import EngineManager

        kokoro = MagicMock()
        kokoro.is_loaded = True
        cfg = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu"], default_model="kokoro")
        manager = EngineManager(cfg, initial_engine=kokoro)
        manager._active_counts["kokoro"] = 1
        moss = MagicMock()
        moss.is_loaded = True
        moss.metadata.return_value = {"id": "moss-nano-cpu"}
        manager._engines["moss-nano-cpu"] = moss

        result = manager.switch_model("moss-nano-cpu", unload_previous=True, load=False)

        assert result["ok"] is True
        assert result["previous_busy"] is True
        assert result["unloaded_previous"] is False
        kokoro.unload.assert_not_called()


class TestSecurityAndMiddleware:
    def test_admin_requires_api_key(self):
        from kokoro_tts.config import TTSConfig

        with pytest.raises(ValueError, match="requires KOKORO_API_KEY"):
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

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, qps=0.01, burst=1)

        @app.get("/ping")
        def ping():
            return {"ok": True}

        client = TestClient(app)
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 429


class TestServerAndCLI:
    @pytest.mark.skipif(not _has_module("fastapi"), reason="fastapi not installed")
    def test_create_app_with_rate_and_queue_config(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.server import create_app

        app = create_app(
            config=TTSConfig(
                model_dir=Path("/nonexistent"),
                rate_limit_qps=1.0,
                rate_limit_burst=2,
                max_queue_length=2,
            )
        )
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

    def test_cli_help(self):
        from kokoro_tts.cli import main

        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["kokoro-tts", "--help"]):
                main()
        assert exc_info.value.code == 0
