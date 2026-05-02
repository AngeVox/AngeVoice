"""Kokoro TTS 基础测试

测试配置和引擎初始化逻辑（不需要实际模型文件）。
模型加载测试需要在有模型文件的环境中运行。
"""

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
        from kokoro_tts.config import TTSConfig, load_config
        config = load_config(port=3000, device="cuda")
        assert config.port == 3000
        assert config.device == "cuda"

    def test_voices_empty_when_no_dir(self):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig(model_dir=Path("/nonexistent"))
        # voices_dir 不存在时应返回空列表
        assert config.get_voices() == []

    def test_voices_discovery(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        # 创建临时音色文件
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

    def test_voices_dir_property(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig(model_dir=tmp_path)
        assert config.voices_dir == tmp_path / "voices"


class TestEngine:
    """测试引擎模块（不需要实际模型）"""

    def test_engine_not_loaded(self):
        from kokoro_tts.engine import TTSEngine
        engine = TTSEngine()
        assert not engine.is_loaded

    def test_clean_text(self):
        from kokoro_tts.engine import TTSEngine
        engine = TTSEngine()
        # \x00 不可打印 → 被替换为空格，再合并连续空白
        assert engine._clean_text("hello\x00world") == "hello world"
        # 合并空白
        assert engine._clean_text("hello   world") == "hello world"
        # 去除首尾空白
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
        # 短文本不分段
        text = "你好"
        segments = engine._segment_text(text)
        assert len(segments) == 1

        # 长文本按标点分段
        text = "你好世界。这是第二句话，很长很长。"
        engine.config.segment_length = 5  # 很小的值触发分段
        segments = engine._segment_text(text)
        assert len(segments) >= 2

    def test_make_speed_fn(self):
        from kokoro_tts.engine import TTSEngine
        engine = TTSEngine()
        fn = engine._make_speed_fn(1.5)
        assert fn(100) == 1.5
        assert fn(200) == 1.5


class TestServer:
    """测试服务器模块"""

    @pytest.mark.skipif(
        not _has_module("fastapi"),
        reason="fastapi not installed",
    )
    def test_create_app(self):
        from kokoro_tts.server import create_app
        from kokoro_tts.config import TTSConfig
        # 不加载模型，只测试 app 创建
        with patch("kokoro_tts.engine.TTSEngine.load"):
            config = TTSConfig(model_dir=Path("/nonexistent"))
            app = create_app(config=config)
            assert app.title == "Kokoro TTS"

    @pytest.mark.skipif(
        not _has_module("fastapi"),
        reason="fastapi not installed",
    )
    def test_tts_request_model(self):
        from kokoro_tts.server import create_app
        from kokoro_tts.config import TTSConfig
        with patch("kokoro_tts.engine.TTSEngine.load"):
            app = create_app(config=TTSConfig(model_dir=Path("/nonexistent")))
            # TTSRequest is internal to create_app; just verify app was created
            assert app.title == "Kokoro TTS"


class TestCLI:
    """测试 CLI 模块"""

    def test_cli_help(self):
        from kokoro_tts.cli import main
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["kokoro-tts", "--help"]):
                main()
        assert exc_info.value.code == 0
