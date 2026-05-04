"""Docker 内集成测试 — 验证 HTTP + WebSocket 端点（mock 模型）"""

import json
import struct
import base64
import zipfile
from io import BytesIO
from unittest.mock import MagicMock

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def mock_engine():
    """创建完全 mock 的 TTSEngine"""
    engine = MagicMock()
    engine._loaded = True
    engine._device = "cpu"
    engine.is_loaded = True
    engine.config = MagicMock()
    engine.config.sample_rate = 24000
    engine.config.max_text_length = 10000
    engine.config.get_voices.return_value = ["zm_010", "zf_001"]
    engine.synthesize.side_effect = ValueError("文本不能为空")
    engine.synthesize_array.return_value = np.zeros(2400, dtype=np.float32)
    engine._encode_segment.return_value = b"\x00" * 4800
    return engine


@pytest.fixture
def app_with_mock(mock_engine):
    """创建带 mock engine 的 FastAPI app"""
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.server import create_app

    config = TTSConfig(model_dir="/nonexistent")
    return create_app(config=config, engine=mock_engine)


class TestHTTPEndpoints:
    """HTTP 端点测试"""

    @pytest.mark.asyncio
    async def test_health(self, app_with_mock):
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "device" in data

    @pytest.mark.asyncio
    async def test_voices(self, app_with_mock):
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/audio/voices")
            assert resp.status_code == 200
            assert "voices" in resp.json()

    @pytest.mark.asyncio
    async def test_openai_tts_success(self, app_with_mock, mock_engine):
        mock_engine.synthesize.side_effect = None
        mock_engine.synthesize.return_value = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 100

        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/audio/speech", json={
                "text": "你好世界",
                "voice": "zm_010",
                "speed": 1.0,
            })
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "audio/wav"
            assert "x-request-id" in resp.headers

    @pytest.mark.asyncio
    async def test_openai_tts_empty_text(self, app_with_mock):
        """空文本应返回 400"""
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/audio/speech", json={
                "text": "",
                "voice": "zm_010",
            })
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_openai_tts_mp3_disabled(self, app_with_mock):
        """MP3 默认关闭时应返回 400，而不是继续合成。"""
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/audio/speech", json={
                "text": "测试 MP3",
                "voice": "zm_010",
                "response_format": "mp3",
            })
            assert resp.status_code == 400
            assert "MP3" in resp.text

    @pytest.mark.asyncio
    async def test_api_tts_post(self, app_with_mock, mock_engine):
        mock_engine.synthesize.side_effect = None
        mock_engine.synthesize.return_value = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 100

        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/tts", json={
                "text": "测试接口",
                "voice": "zm_010",
                "speed": 1.0,
            })
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_formats_endpoint(self, app_with_mock):
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/audio/formats")
            assert resp.status_code == 200
            data = resp.json()
            assert "wav" in data["formats"]
            assert "pcm" in data["formats"]
            assert data["mp3_enabled"] is False

    @pytest.mark.asyncio
    async def test_cancel_endpoint_unknown_request(self, app_with_mock):
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/audio/requests/fake-request/cancel")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["known"] is False
            assert data["status"] == "cancelling"

    @pytest.mark.asyncio
    async def test_batch_tts_zip(self, app_with_mock, mock_engine):
        mock_engine.synthesize.side_effect = None
        mock_engine.synthesize.return_value = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 100

        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/audio/batch", json={
                "voice": "zm_010",
                "response_format": "wav",
                "items": [
                    {"text": "第一段", "filename": "001"},
                    {"text": "第二段", "filename": "002"},
                ],
            })
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/zip"
            with zipfile.ZipFile(BytesIO(resp.content)) as zf:
                names = set(zf.namelist())
                assert "001.wav" in names
                assert "002.wav" in names
                assert "manifest.json" in names
                manifest = json.loads(zf.read("manifest.json"))
                assert len(manifest) == 2
                assert all(item["status"] == "ok" for item in manifest)

    @pytest.mark.asyncio
    async def test_admin_cache_disabled_by_default(self, app_with_mock):
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/admin/cache")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_api_key_required_when_configured(self, mock_engine):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.server import create_app

        app = create_app(config=TTSConfig(model_dir="/nonexistent", api_key="secret"), engine=mock_engine)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/stats")
            assert resp.status_code == 401
            resp = await client.get("/stats", headers={"Authorization": "Bearer secret"})
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_cache_enabled_with_api_key(self, mock_engine):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.server import create_app

        app = create_app(config=TTSConfig(model_dir="/nonexistent", admin_enabled=True, api_key="secret"), engine=mock_engine)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/admin/cache", headers={"Authorization": "Bearer secret"})
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_routes_intact(self, app_with_mock):
        """验证所有原有路由未被破坏"""
        routes = [route.path for route in app_with_mock.routes]
        assert "/v1/audio/speech" in routes
        assert "/api/tts" in routes
        assert "/health" in routes
        assert "/v1/audio/voices" in routes
        assert "/v1/audio/formats" in routes
        assert "/v1/audio/batch" in routes
        assert "/v1/audio/requests/{request_id}/cancel" in routes
        assert "/admin/cache" in routes
        assert "/" in routes
        assert "/ws/v1/tts" in routes


class TestWebSocketStructure:
    """WebSocket 端点结构验证"""

    def test_ws_route_exists(self, app_with_mock):
        routes = [route.path for route in app_with_mock.routes]
        assert "/ws/v1/tts" in routes

    def test_ws_handler_is_websocket(self, app_with_mock):
        """验证 WebSocket handler 注册正确"""
        ws_routes = [r for r in app_with_mock.routes if hasattr(r, 'path') and r.path == '/ws/v1/tts']
        assert len(ws_routes) == 1
        route = ws_routes[0]
        assert hasattr(route, 'endpoint')


class TestStreamEncoding:
    """流式编码测试"""

    def test_pcm_s16le_encoding(self):
        """PCM s16le: float32 -> int16 -> bytes"""
        audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
        audio_int16 = (audio * 32767).astype(np.int16)
        result = audio_int16.tobytes()

        assert isinstance(result, bytes)
        assert len(result) == 10
        samples = struct.unpack("<5h", result)
        assert samples[0] == 0
        assert samples[1] == 16383
        assert samples[2] == -16383
        assert samples[3] == 32767
        assert samples[4] == -32767

    def test_wav_encoding(self):
        """WAV 编码返回有效 RIFF 头"""
        import soundfile as sf

        audio = np.random.randn(24000).astype(np.float32)
        audio = np.clip(audio, -1.0, 1.0)
        buffer = BytesIO()
        sf.write(buffer, audio, 24000, format="WAV")
        result = buffer.getvalue()

        assert result[:4] == b"RIFF"
        assert result[8:12] == b"WAVE"
        assert len(result) > 48000

    def test_pcm_roundtrip(self):
        """PCM 编码后解码应还原"""
        original = np.array([0.0, 0.3, -0.7, 1.0, -1.0], dtype=np.float32)
        audio_int16 = (original * 32767).astype(np.int16)
        encoded = audio_int16.tobytes()
        decoded = np.frombuffer(encoded, dtype=np.int16).astype(np.float32) / 32767

        np.testing.assert_array_almost_equal(original, decoded, decimal=4)

    def test_large_audio_encoding(self):
        """大块音频编码不崩溃"""
        audio = np.random.randn(24000 * 10).astype(np.float32)
        audio = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio * 32767).astype(np.int16)
        result = audio_int16.tobytes()

        assert len(result) == 24000 * 10 * 2


class TestConfigStreamFields:
    """配置流式字段测试"""

    def test_stream_defaults(self):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig()
        assert config.stream_enabled is True
        assert config.stream_format == "pcm_s16le"

    def test_stream_custom(self):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig(stream_enabled=False, stream_format="wav")
        assert config.stream_enabled is False
        assert config.stream_format == "wav"


class TestSynthesizeStreamLogic:
    """synthesize_stream 逻辑测试（不需要模型）"""

    def test_engine_not_loaded_yields_error(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        results = list(engine.synthesize_stream("你好"))
        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "未加载" in results[0]["message"]

    def test_empty_text_yields_error(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        engine = TTSEngine(TTSConfig())
        results = list(engine.synthesize_stream(""))
        assert len(results) == 1
        assert results[0]["type"] == "error"

    def test_text_too_long_yields_error(self):
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.config import TTSConfig

        config = TTSConfig(max_text_length=10)
        engine = TTSEngine(config)
        engine._loaded = True
        results = list(engine.synthesize_stream("这是一段超过十个字符的文本"))
        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "过长" in results[0]["message"]
