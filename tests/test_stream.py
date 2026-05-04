"""流式语音合成测试

验证 synthesize_stream 逐段 yield、PCM 编码正确性、WebSocket 端点可连接等。
"""

import base64
import struct
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestEncodeSegment:
    """测试 _encode_segment 方法"""

    def test_pcm_s16le_encoding(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
        result = engine._encode_segment(audio, format="pcm_s16le")

        assert isinstance(result, bytes)
        assert len(result) == 10
        samples = struct.unpack("<5h", result)
        assert samples[0] == 0
        assert samples[1] == 16383
        assert samples[2] == -16383
        assert samples[3] == 32767
        assert samples[4] == -32767

    def test_pcm_s16le_clips_out_of_range_values(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        audio = np.array([2.0, -2.0, np.nan, np.inf, -np.inf], dtype=np.float32)
        result = engine._encode_segment(audio, format="pcm_s16le")
        samples = struct.unpack("<5h", result)
        assert samples == (32767, -32767, 0, 0, 0)

    def test_wav_encoding(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        audio = np.random.randn(1000).astype(np.float32)
        audio = np.clip(audio, -1.0, 1.0)
        result = engine._encode_segment(audio, format="wav")

        assert isinstance(result, bytes)
        assert result[:4] == b"RIFF"
        assert result[8:12] == b"WAVE"

    def test_unsupported_format(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        audio = np.array([0.0, 0.5], dtype=np.float32)
        with pytest.raises(ValueError, match="Unsupported format"):
            engine._encode_segment(audio, format="mp3")


class TestTextSegmentation:
    """测试文本分段。"""

    def test_long_text_without_punctuation_is_split(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig(segment_length=30))
        text = "这是一段没有任何标点的长文本" * 12
        segments = engine._segment_text(text)

        assert len(segments) > 1
        assert all(len(s) <= 45 for s in segments)

    def test_punctuation_is_preferred_for_split(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig(segment_length=20))
        text = (
            "第一句话内容较长，用于触发按标点切分。"
            "第二句话继续补充足够多的文字，避免测试文本太短。"
            "第三句话结束，用于验证所有分段都非空。"
        )
        segments = engine._segment_text(text)

        assert len(segments) >= 2
        assert all(s for s in segments)


class TestSynthesizeStream:
    """测试 synthesize_stream 方法"""

    def test_engine_not_loaded(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        results = list(engine.synthesize_stream("你好"))
        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "未加载" in results[0]["message"]

    def test_empty_text(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        results = list(engine.synthesize_stream(""))
        assert len(results) == 1
        assert results[0]["type"] == "error"

    def test_text_too_long(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig(max_text_length=10))
        engine._loaded = True
        results = list(engine.synthesize_stream("这是一段超过十个字符的文本"))
        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "过长" in results[0]["message"]

    def test_invalid_speed(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        engine._loaded = True
        results = list(engine.synthesize_stream("你好", speed=3.0))
        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "speed" in results[0]["message"]

    def test_unsupported_stream_format(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        engine._loaded = True
        results = list(engine.synthesize_stream("你好", fmt="mp3"))
        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "Unsupported format" in results[0]["message"]

    def test_stream_yields_segments(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        config = TTSConfig(segment_length=30)
        engine = TTSEngine(config)
        engine._loaded = True
        fake_audio = np.random.randn(1000).astype(np.float32)
        engine._synthesize_segment = MagicMock(return_value=fake_audio)

        text = (
            "第一段文本用于流式合成测试，需要足够长。"
            "第二段文本继续增加长度，确保分段逻辑被覆盖。"
            "第三段文本结束。"
        )
        results = list(engine.synthesize_stream(text, voice="zm_010"))

        types = [r["type"] for r in results]
        assert "started" in types
        assert "done" in types

        started = results[0]
        assert started["sample_rate"] == config.sample_rate
        assert started["channels"] == 1

        audio_msgs = [r for r in results if r["type"] == "audio"]
        assert len(audio_msgs) >= 1
        for msg in audio_msgs:
            assert "index" in msg
            assert "data" in msg
            assert "format" in msg
            assert msg["format"] == "pcm_s16le"
            assert msg["sample_rate"] == config.sample_rate
            assert msg["channels"] == 1
            decoded = base64.b64decode(msg["data"])
            assert len(decoded) > 0

    def test_format_param(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        with patch.object(engine, "_loaded", True), patch.object(engine, "_zh_pipeline") as mock_pipe:
            mock_result = MagicMock()
            mock_result.audio = np.array([0.5], dtype=np.float32)
            mock_pipe.return_value = iter([mock_result])

            results = list(engine.synthesize_stream("你好", fmt="wav"))
            audio_msgs = [r for r in results if r["type"] == "audio"]
            if audio_msgs:
                decoded = base64.b64decode(audio_msgs[0]["data"])
                assert decoded[:4] == b"RIFF"
