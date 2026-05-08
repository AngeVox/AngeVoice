"""AngeVoice 基础测试

测试配置和引擎初始化逻辑（不需要实际模型文件）。
模型加载测试需要在有模型文件的环境中运行。
"""

import base64
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 确保能导入包
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


class TestConfig:
    """测试配置模块"""

    def test_default_config(self):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.sample_rate == 24000
        assert config.device == "auto"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("KOKORO_PORT", "9000")
        monkeypatch.setenv("KOKORO_HOST", "127.0.0.1")
        monkeypatch.setenv("KOKORO_DEVICE", "cpu")

        from kokoro_tts.config import load_config
        config = load_config()
        assert config.port == 9000
        assert config.host == "127.0.0.1"
        assert config.device == "cpu"

    def test_function_params_override(self):
        from kokoro_tts.config import load_config
        config = load_config(port=3000, device="cuda")
        assert config.port == 3000
        assert config.device == "cuda"

    def test_voices_empty_when_no_dir(self):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig(model_dir=Path("/nonexistent"))
        assert config.get_voices() == []

    def test_voices_discovery(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        (voices_dir / "zm_001.pt").touch()
        (voices_dir / "zm_002.pt").touch()

        config = TTSConfig(model_dir=tmp_path)
        voices = config.get_voices()
        assert "zm_001" in voices
        assert "zm_002" in voices

    def test_model_file_property(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig(model_dir=tmp_path)
        assert config.model_file == tmp_path / "kokoro-v1_1-zh.pth"

    def test_moss_prompt_upload_env(self, monkeypatch):
        monkeypatch.setenv("MOSS_PROMPT_UPLOAD_MAX_BYTES", "4096")
        monkeypatch.setenv("MOSS_PROMPT_AUDIO_MAX_SECONDS", "6.5")
        monkeypatch.setenv("MOSS_PROMPT_CACHE_MAX_ITEMS", "3")
        monkeypatch.setenv("MOSS_OUTPUT_TARGET_PEAK", "0.88")
        monkeypatch.setenv("MOSS_OUTPUT_GAIN", "0.9")

        from kokoro_tts.config import load_config

        config = load_config()
        assert config.moss_prompt_upload_max_bytes == 4096
        assert config.moss_prompt_audio_max_seconds == 6.5
        assert config.moss_prompt_cache_max_items == 3
        assert config.moss_output_target_peak == 0.88
        assert config.moss_output_gain == 0.9
        assert config.moss_apply_angevoice_rules is True

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

    def test_voices_dir_property(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig(model_dir=tmp_path)
        assert config.voices_dir == tmp_path / "voices"


class TestPromptAudio:
    """测试参考音频工具和 MOSS 后处理。"""

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


class TestOpenApi:
    """确保可选路由不会破坏 OpenAPI schema。"""

    def test_openapi_schema_builds_with_batch_and_admin_routes(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.server import create_app

        app = create_app(config=TTSConfig(model_dir=tmp_path, enabled_models=["kokoro"], default_model="kokoro"))
        schema = app.openapi()

        assert schema["info"]["version"] == "2.6.3"
        assert "/v1/audio/batch" in schema["paths"]
        assert "/admin/voices/upload" in schema["paths"]


class TestTextNormalization:
    """测试中文 TTS 文本规范化。"""

    def test_date_in_chinese_context(self):
        from kokoro_tts.engine import normalize_text_for_tts

        assert normalize_text_for_tts("今天是2026-05-05。") == "今天是二零二六年五月五日。"
        assert normalize_text_for_tts("版本于2026/5/5发布") == "版本于二零二六年五月五日发布"

    def test_money_in_chinese_context(self):
        from kokoro_tts.engine import normalize_text_for_tts

        assert normalize_text_for_tts("价格100元") == "价格一百元"
        assert normalize_text_for_tts("费用为¥1000.50") == "费用为一千元五角"
        assert normalize_text_for_tts("预算12000元") == "预算一万二千元"

    def test_percent_and_phone_number(self):
        from kokoro_tts.engine import normalize_text_for_tts

        assert normalize_text_for_tts("成功率98.5%") == "成功率百分之九八点五"
        assert normalize_text_for_tts("电话13800138000") == "电话幺三八，零零幺三，八零零零"

    def test_plain_id_is_grouped_but_short_plain_number_is_unchanged(self):
        from kokoro_tts.engine import normalize_text_for_tts

        assert normalize_text_for_tts("编号12345678") == "编号幺二三四，五六七八"
        assert normalize_text_for_tts("模型版本123") == "模型版本123"

    def test_poetry_polyphone_and_auto_punctuation(self):
        from kokoro_tts.engine import normalize_text_for_tts

        assert normalize_text_for_tts("春花秋月何时了") == "春花秋月何时瞭。"
        assert normalize_text_for_tts("银行行长正在听音乐。") == "银杭杭掌正在听音悦。"
        assert normalize_text_for_tts("重庆重新调整调查方案。") == "虫庆虫新条整掉查方案。"
        assert normalize_text_for_tts("效率很高，率先完成。") == "效律很高，帅先完成。"

    def test_clock_time_in_chinese_context(self):
        from kokoro_tts.engine import normalize_text_for_tts

        assert normalize_text_for_tts("会议12:00开始") == "会议十二点整开始"
        assert normalize_text_for_tts("会议12:01开始") == "会议十二点零一分开始"
        assert normalize_text_for_tts("会议12:43开始") == "会议十二点四十三分开始"

    def test_long_chinese_run_gets_pause_marks(self):
        from kokoro_tts.engine import normalize_text_for_tts

        text = "这是一段没有任何标点的长文本" * 4
        normalized = normalize_text_for_tts(text)
        assert "，" in normalized
        assert len(normalized) > len(text)


class TestEngine:
    """测试引擎模块（不需要实际模型）"""

    def test_engine_not_loaded(self):
        from kokoro_tts.engine import TTSEngine
        engine = TTSEngine()
        assert not engine.is_loaded

    def test_clean_text(self):
        from kokoro_tts.engine import TTSEngine
        engine = TTSEngine()
        assert engine._clean_text("hello\x00world") == "hello world"
        assert engine._clean_text("hello   world") == "hello world"
        assert engine._clean_text("  hello  ") == "hello"

    def test_detect_language(self):
        from kokoro_tts.engine import TTSEngine
        engine = TTSEngine()
        assert engine._detect_language("hello world test") == "en"
        assert engine._detect_language("你好世界") == "zh"
        assert engine._detect_language("") == "zh"

    def test_segment_text(self):
        from kokoro_tts.engine import TTSEngine
        engine = TTSEngine()
        text = "你好"
        segments = engine._segment_text(text)
        assert len(segments) == 1

        engine.config.segment_length = 20
        text = (
            "第一句话用于测试分段逻辑，内容需要足够长才能触发切分。"
            "第二句话继续补充长度，确保超过一倍半的切分阈值。"
            "第三句话用于验证标点优先切分。"
        )
        segments = engine._segment_text(text)
        assert len(segments) >= 2
        assert all(s for s in segments)

    def test_make_speed_fn(self):
        from kokoro_tts.engine import TTSEngine
        engine = TTSEngine()
        fn = engine._make_speed_fn(1.5)
        assert fn(100) == 1.5
        assert fn(200) == 1.5


class TestServiceState:
    """测试服务状态收尾逻辑。"""

    def test_cache_key_includes_model(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.service_state import ServiceState

        cfg = TTSConfig()
        engine = MagicMock()
        state = ServiceState(cfg, engine)

        kokoro_key = state.cache_key("kokoro", "你好", "zm_010", 1.0, "wav")
        moss_key = state.cache_key("moss-nano-cpu", "你好", "zm_010", 1.0, "wav")

        assert kokoro_key != moss_key

    def test_cache_key_includes_prompt_audio(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.service_state import ServiceState

        state = ServiceState(TTSConfig(), MagicMock())

        base_key = state.cache_key("moss-nano-cpu", "你好", "Junhao", 1.0, "wav")
        clone_key = state.cache_key("moss-nano-cpu", "你好", "Junhao", 1.0, "wav", "sha256:abc")

        assert base_key != clone_key

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
        assert "voice_clone" in models[1]["modes"]

    def test_engine_manager_hides_disabled_cuda_moss(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine_manager import EngineManager

        cfg = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu", "moss-nano-cuda"], moss_cuda_enabled=False)
        cfg.validate_security()
        manager = EngineManager(cfg)

        models = manager.list_models()
        assert [item["id"] for item in models] == ["kokoro", "moss-nano-cpu"]
        assert manager.normalize_model_id("moss") == "moss-nano-cpu"
        with pytest.raises(Exception) as exc_info:
            manager.switch_model("moss-nano-cuda", load=False)
        assert getattr(exc_info.value, "status_code", None) == 404

    @pytest.mark.asyncio
    async def test_http_exception_finishes_request_state(self):
        from fastapi import HTTPException
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.service_state import ServiceState

        cfg = TTSConfig(mp3_enabled=False)
        engine = MagicMock()
        state = ServiceState(cfg, engine)

        with pytest.raises(HTTPException) as exc_info:
            await state.synthesize_response_threaded("你好", "zm_010", 1.0, "mp3", "req-http-error")

        assert exc_info.value.status_code == 400
        assert state.active_requests["req-http-error"]["status"] == "error"
        assert state.active_requests["req-http-error"]["status_code"] == 400
        assert state.stats["requests_error"] == 1
        assert state.stats["requests_ok"] == 0

    @pytest.mark.asyncio
    async def test_cancelled_request_finishes_as_cancelled(self):
        from fastapi import HTTPException
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.service_state import ServiceState

        cfg = TTSConfig()
        engine = MagicMock()
        state = ServiceState(cfg, engine)
        state.request_cancel("req-cancelled")

        with pytest.raises(HTTPException) as exc_info:
            await state.synthesize_response_threaded("你好", "zm_010", 1.0, "wav", "req-cancelled")

        assert exc_info.value.status_code == 499
        assert state.active_requests["req-cancelled"]["status"] == "cancelled"
        assert state.stats["requests_error"] == 1

    def test_cache_helpers_are_thread_safe_entrypoints(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.service_state import ServiceState

        state = ServiceState(TTSConfig(), MagicMock())
        state.cache_set("one", (b"wav", "audio/wav"))

        assert state.cache_get("one") == (b"wav", "audio/wav")
        assert state.cache_size() == 1
        assert state.cache_clear() == 1
        assert state.cache_size() == 0


class TestSecurityConfig:
    """测试生产安全配置保护。"""

    def test_admin_requires_api_key(self):
        from kokoro_tts.config import TTSConfig

        with pytest.raises(ValueError, match="requires KOKORO_API_KEY"):
            TTSConfig(admin_enabled=True).validate_security()

    def test_placeholder_api_key_is_rejected(self):
        from kokoro_tts.config import TTSConfig

        with pytest.raises(ValueError, match="placeholder"):
            TTSConfig(api_key="CHANGE-ME-TO-A-REAL-SECRET-KEY").validate_security()


class TestServer:
    """测试服务器模块"""

    @pytest.mark.skipif(not _has_module("fastapi"), reason="fastapi not installed")
    def test_create_app(self):
        from kokoro_tts.server import create_app
        from kokoro_tts.config import TTSConfig
        with patch("kokoro_tts.engine.TTSEngine.load"):
            config = TTSConfig(model_dir=Path("/nonexistent"))
            app = create_app(config=config)
            assert app.title == "AngeVoice"

    @pytest.mark.skipif(not _has_module("fastapi"), reason="fastapi not installed")
    def test_tts_request_model(self):
        from kokoro_tts.server import create_app
        from kokoro_tts.config import TTSConfig
        with patch("kokoro_tts.engine.TTSEngine.load"):
            app = create_app(config=TTSConfig(model_dir=Path("/nonexistent")))
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


class TestCLI:
    """测试 CLI 模块"""

    def test_cli_help(self):
        from kokoro_tts.cli import main
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["kokoro-tts", "--help"]):
                main()
        assert exc_info.value.code == 0
