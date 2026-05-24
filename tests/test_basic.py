"""AngeVoice 轻量单元测试。"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
EXPECTED_VERSION = "2.6.6"


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
        assert config.moss_process_isolation_enabled is False
        assert config.moss_process_isolation_providers == "cuda"
        assert config.moss_realtime_streaming_decode is True
        assert config.moss_segment_length == 120
        assert config.moss_max_new_frames == 320
        assert config.moss_voice_clone_max_text_tokens == 56
        assert config.moss_max_silence_ms == 480
        assert config.moss_vram_guard_enabled is True
        assert config.moss_stream_queue_max_items == 8
        assert config.moss_stream_prebuffer_seconds == 0.75
        assert config.moss_output_target_peak == 0.86
        assert config.moss_output_gain == 0.94
        assert config.moss_apply_angevoice_rules == "auto"
        assert config.moss_mixed_english_policy == "translate"
        assert config.moss_vram_snapshot_ttl_seconds == 10.0
        assert config.cache_max_items == 64
        assert config.cache_max_bytes == 512 * 1024 * 1024
        assert config.text_single_newline_policy == "auto"
        assert config.model_source == "auto"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("KOKORO_PORT", "9000")
        monkeypatch.setenv("KOKORO_DEVICE", "cpu")
        monkeypatch.setenv("KOKORO_RATE_LIMIT_QPS", "2.5")
        monkeypatch.setenv("KOKORO_MAX_QUEUE_LENGTH", "3")
        monkeypatch.setenv("ANGEVOICE_IDLE_TIMEOUT_SECONDS", "30")
        monkeypatch.setenv("MOSS_PROCESS_ISOLATION_ENABLED", "false")
        monkeypatch.setenv("MOSS_SEGMENT_LENGTH", "160")
        monkeypatch.setenv("ANGEVOICE_MODEL_SOURCE", "modelscope")
        monkeypatch.setenv("MOSS_MIXED_ENGLISH_POLICY", "preserve")
        from kokoro_tts.config import load_config
        config = load_config()
        assert config.port == 9000
        assert config.device == "cpu"
        assert config.rate_limit_qps == 2.5
        assert config.max_queue_length == 3
        assert config.model_idle_timeout_seconds == 30
        assert config.moss_process_isolation_enabled is False
        assert config.moss_segment_length == 160
        assert config.model_source == "modelscope"
        assert config.moss_mixed_english_policy == "preserve"


    def test_auto_api_key_generates_persistent_secret(self, monkeypatch, tmp_path):
        from kokoro_tts.config import load_config

        key_file = tmp_path / "api_key.txt"
        monkeypatch.setenv("KOKORO_API_KEY", "auto")
        monkeypatch.setenv("ANGEVOICE_API_KEY_FILE", str(key_file))
        cfg = load_config(model_dir=str(tmp_path / "models"))
        assert cfg.api_key and cfg.api_key.startswith("av_")
        assert cfg.api_key_auto_generated is True
        assert key_file.read_text(encoding="utf-8").strip() == cfg.api_key

        cfg2 = load_config(model_dir=str(tmp_path / "models"))
        assert cfg2.api_key == cfg.api_key

    def test_model_source_auto_uses_reachability_before_country(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts import model_sources

        cfg = TTSConfig(model_source="auto")
        with patch.object(model_sources, "_probe_reachability", return_value=(False, True)), \
             patch.object(model_sources, "_detect_country", return_value=""):
            assert model_sources.resolve_model_source(cfg) == "modelscope"

        cfg = TTSConfig(model_source="auto")
        with patch.object(model_sources, "_probe_reachability", return_value=(True, True)), \
             patch.object(model_sources, "_detect_country", return_value="CN"):
            assert model_sources.resolve_model_source(cfg) == "modelscope"

        cfg = TTSConfig(model_source="auto")
        with patch.object(model_sources, "_probe_reachability", return_value=(True, False)), \
             patch.object(model_sources, "_detect_country", return_value="CN"):
            assert model_sources.resolve_model_source(cfg) == "huggingface"

    def test_model_source_auto_uses_cached_effective_source(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts import model_sources

        cfg = TTSConfig(model_source="auto")
        cfg.model_source_effective = "modelscope"
        with patch.object(model_sources, "_probe_reachability", side_effect=AssertionError("cache miss")):
            assert model_sources.resolve_model_source(cfg) == "modelscope"

    def test_moss_cuda_can_be_disabled(self):
        from kokoro_tts.config import TTSConfig
        config = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu", "moss-nano-cuda"], default_model="moss-nano-cuda", moss_execution_provider="cuda", moss_cuda_enabled=False)
        config.validate_security()
        assert config.enabled_models == ["kokoro", "moss-nano-cpu"]
        assert config.default_model == "moss-nano-cpu"
        assert config.moss_execution_provider == "cpu"


class TestValidationHelpers:
    @pytest.mark.skipif(not _has_module("fastapi"), reason="fastapi not installed")
    def test_text_length_validation_is_shared(self):
        from fastapi import HTTPException
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.validation import validate_tts_text

        cfg = TTSConfig(max_text_length=3)
        assert validate_tts_text(" 你好 ", cfg) == "你好"
        with pytest.raises(HTTPException):
            validate_tts_text("四个字符", cfg)

    @pytest.mark.skipif(not _has_module("fastapi"), reason="fastapi not installed")
    def test_moss_rejects_speed_adjustment(self):
        from fastapi import HTTPException
        from kokoro_tts.validation import validate_model_speed

        assert validate_model_speed("moss-nano-cpu", 1.0) == 1.0
        with pytest.raises(HTTPException):
            validate_model_speed("moss-nano-cpu", 1.2)
        assert validate_model_speed("kokoro", 1.2) == 1.2


class TestMossHelpers:
    def test_moss_output_postprocess_limits_peak(self):
        import numpy as np
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine
        engine = MossNanoEngine(TTSConfig(moss_output_target_peak=0.5, moss_output_gain=1.0))
        output = engine._postprocess_waveform(np.asarray([[1.2, -1.2], [0.1, -0.1]], dtype=np.float32))
        assert output.shape == (2, 2)
        assert float(np.max(np.abs(output))) <= 0.5001
        assert engine.metadata()["last_output_quality"]["scale"] < 1.0


    def test_moss_postprocess_repairs_impulses_and_fades_edges(self):
        import numpy as np
        from kokoro_tts.moss.postprocess import normalize_waveform

        audio = np.zeros((64, 1), dtype=np.float32)
        audio[32, 0] = 0.95
        processed, quality = normalize_waveform(
            audio,
            channels=1,
            target_peak=0.78,
            declick_enabled=True,
            edge_fade_samples=4,
        )
        assert processed.shape == (64, 1)
        assert quality.repaired_impulses >= 1
        assert abs(float(processed[0, 0])) < 1e-6
        assert float(np.max(np.abs(processed))) <= 0.7801

    def test_fragile_liao_hint_is_not_rewritten_by_default(self):
        from kokoro_tts.zh_rules import normalize_chinese_rules

        assert "春花秋月何时了" in normalize_chinese_rules("春花秋月何时了", model="moss-nano-cuda")
        assert "春花秋月何时了" in normalize_chinese_rules("春花秋月何时了", model="kokoro")


    def test_moss_text_rules_use_moss_route_not_kokoro_polyphone_dictionary(self):
        from kokoro_tts.moss.text import clean_text

        cleaned = clean_text("春花秋月何时了，重庆4.20更新。", apply_angevoice_rules=True, model="moss-nano-cuda")
        assert "何时蓼" not in cleaned
        assert "何时瞭" not in cleaned
        assert "虫庆" not in cleaned
        assert "重庆" in cleaned
        assert "四月二十日更新" in cleaned

    def test_short_dot_date_uses_context_and_preserves_decimal_or_version(self):
        from kokoro_tts.engine import normalize_text_for_tts

        assert "四月二十日" in normalize_text_for_tts("活动在4.20开始")
        assert "四月二十日" in normalize_text_for_tts("4.20号更新")
        assert "4.20" in normalize_text_for_tts("版本4.20已经发布")
        assert "4.20" in normalize_text_for_tts("比例是4.20")
        assert "四元二角" in normalize_text_for_tts("价格是4.20元")

    def test_moss_rejects_speed_control_directly(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine

        engine = MossNanoEngine(TTSConfig(), execution_provider="cpu")
        engine._loaded = True
        engine._runtime = object()
        with pytest.raises(ValueError, match="暂不支持语速调节"):
            engine._validate_request("你好", "Junhao", 1.2)

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

    def test_drop_model_removes_engine_for_config_rebuild(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine_manager import EngineManager

        engine = MagicMock(); engine.is_loaded = True
        manager = EngineManager(TTSConfig(enabled_models=["kokoro"], default_model="kokoro"), initial_engine=engine)
        assert manager.drop_model("kokoro") is True
        engine.unload.assert_called_once()
        assert "kokoro" not in manager._engines


class TestSecurityAndMiddleware:

    def test_admin_safe_compare_supports_chinese(self):
        from kokoro_tts.routes.admin import _safe_compare

        assert _safe_compare("安歌", "安歌") is True
        assert _safe_compare("安歌", "admin") is False

    def test_admin_default_first_entry_credentials_are_allowed_with_warning(self, monkeypatch, caplog):
        from kokoro_tts.config import TTSConfig
        monkeypatch.delenv("ANGEVOICE_ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("ANGEVOICE_ADMIN_PASSWORD", raising=False)
        TTSConfig(admin_enabled=True).validate_security()
        assert "admin/admin123" in caplog.text

    def test_placeholder_api_key_is_rejected(self):
        from kokoro_tts.config import TTSConfig
        with pytest.raises(ValueError, match="placeholder"):
            TTSConfig(api_key="CHANGE-ME-TO-A-REAL-SECRET-KEY").validate_security()


    def test_rate_limit_ignores_forwarded_headers_by_default(self):
        from types import SimpleNamespace
        from kokoro_tts.rate_limit import _extract_client_key

        class Request:
            headers = {"x-forwarded-for": "1.2.3.4", "x-real-ip": "5.6.7.8"}
            client = SimpleNamespace(host="10.0.0.9")

        assert _extract_client_key(Request()) == "ip:10.0.0.9"
        assert _extract_client_key(Request(), trust_proxy_headers=True) == "ip:1.2.3.4"

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

    def test_run_server_uses_import_string_for_workers(self, monkeypatch):
        from types import SimpleNamespace
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.server import run_server

        calls = []

        def fake_run(*args, **kwargs):
            calls.append((args, kwargs))

        monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
        config = TTSConfig(model_dir=Path("/nonexistent"), workers=2)
        run_server(config)
        args, kwargs = calls[-1]
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

    def test_moss_process_isolation_defaults_to_off_and_can_enable_cuda(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine

        cfg = TTSConfig()
        cuda_engine = MossNanoEngine(cfg, execution_provider="cuda")
        assert cuda_engine._process_isolated is False

        isolated_cfg = TTSConfig(moss_process_isolation_enabled=True, moss_process_isolation_providers="cuda")
        isolated_cuda = MossNanoEngine(isolated_cfg, execution_provider="cuda")
        isolated_cpu = MossNanoEngine(isolated_cfg, execution_provider="cpu")
        assert isolated_cuda._process_isolated is True
        assert isolated_cpu._process_isolated is False
        isolated_cuda._loaded = True
        isolated_cuda._validate_request("你好", "Junhao", 1.0)


    def test_moss_isolated_stream_reloads_after_cancelled_worker(self):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss_engine import MossNanoEngine

        class ClosedClient:
            alive = False

        engine = MossNanoEngine(TTSConfig(), execution_provider="cuda", process_isolation=True)
        engine._loaded = True
        engine._process_client = ClosedClient()
        called = {"load": 0}

        def fake_load():
            called["load"] += 1
            engine._loaded = True
            engine._process_client = None
            return engine

        engine.load = fake_load
        list(engine._synthesize_stream_process_isolated(text="你好", voice="Junhao", speed=1.0, fmt="pcm_s16le", prompt_audio_path=None, cancel_check=lambda: True))
        assert called["load"] == 1

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


class TestXiaozhiAdapterKit:
    def test_xiaozhi_adapter_files_exist(self):
        from pathlib import Path

        root = Path(__file__).parent.parent / "xiaozhi"
        required = [
            "adapters/angevoice.py",
            "adapters/angevoice_stream.py",
            "adapters/angevoice_clone.py",
            "scripts/install-xiaozhi-adapter.sh",
            "manager/presets.yaml",
            "examples/config-moss-clone.yaml",
        ]
        for rel in required:
            assert (root / rel).exists(), rel

    def test_xiaozhi_moss_clone_docs_show_prompt_mount_path(self):
        from pathlib import Path

        text = (Path(__file__).parent.parent / "xiaozhi" / "README.md").read_text(encoding="utf-8")
        assert "data/angevoice_prompts/reference.wav" in text
        assert "/opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav" in text
        assert "智控台" in text

    def test_admin_basic_auth_parser_accepts_utf8_and_latin1_bytes(self):
        import base64
        from kokoro_tts.routes.admin import _candidate_encodings, _parse_basic_header

        raw = "管理员:密钥".encode("utf-8")
        parsed = _parse_basic_header("Basic " + base64.b64encode(raw).decode("ascii"))
        assert parsed is not None
        username, password = parsed
        assert username in _candidate_encodings("管理员")
        assert password in _candidate_encodings("密钥")


def test_cache_skips_long_text_and_large_audio(tmp_path):
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.service_state import ServiceState

    cfg = TTSConfig(model_dir=tmp_path, cache_max_items=10, cache_skip_text_over_chars=5, cache_skip_audio_over_bytes=10)
    state = ServiceState(cfg, eng=None)
    state.cache_set("long", (b"abc", "audio/wav"), text="123456")
    assert state.cache_size() == 0
    state.cache_set("big", (b"a" * 11, "audio/wav"), text="ok")
    assert state.cache_size() == 0
    state.cache_set("ok", (b"a" * 5, "audio/wav"), text="ok")
    assert state.cache_size() == 1
    assert state.cache_bytes() == 5

class TestKokoroLocalPathRegression:
    def test_local_model_dir_is_not_used_as_repo_id(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine import TTSEngine

        model_dir = tmp_path / "models"
        model_dir.mkdir()
        (model_dir / "kokoro-v1_1-zh.pth").write_bytes(b"PK" + b"x" * (11 * 1024 * 1024))
        (model_dir / "config.json").write_text("{}", encoding="utf-8")
        engine = TTSEngine(TTSConfig(model_dir=model_dir))
        assert engine._safe_kokoro_repo_id() == "hexgrad/Kokoro-82M-v1.1-zh"
        assert not engine._safe_kokoro_repo_id().startswith("/")

    def test_local_voice_name_resolves_to_models_voices_file(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine import TTSEngine

        model_dir = tmp_path / "models"
        voices = model_dir / "voices"
        voices.mkdir(parents=True)
        voice_file = voices / "zm_010.pt"
        voice_file.write_bytes(b"PK" + b"v" * (16 * 1024))
        engine = TTSEngine(TTSConfig(model_dir=model_dir))
        assert engine._resolve_voice_for_pipeline("zm_010") == str(voice_file)
        assert engine._resolve_voice_for_pipeline("../zm_010.pt") == str(voice_file)
        assert engine._resolve_voice_for_pipeline("missing_voice") == "missing_voice"


    def test_default_model_dir_uses_unified_layout(self, monkeypatch):
        from kokoro_tts.config import TTSConfig

        monkeypatch.delenv("KOKORO_MODEL_DIR", raising=False)
        monkeypatch.setenv("ANGEVOICE_MODELS_ROOT", "/tmp/angevoice-models")
        cfg = TTSConfig()
        assert str(cfg.model_dir).endswith("/tmp/angevoice-models/models--hexgrad--Kokoro-82M-v1.1-zh")

    def test_tiny_but_valid_torch_voice_is_allowed(self, tmp_path):
        from kokoro_tts.kokoro_assets import is_valid_kokoro_voice_file

        voice = tmp_path / "small_voice.pt"
        voice.write_bytes(b"PK\x03\x04" + b"x" * 700)
        assert is_valid_kokoro_voice_file(voice) is True

    def test_lfs_voice_warning_is_deduplicated(self, tmp_path, caplog):
        import logging
        from kokoro_tts.kokoro_assets import is_valid_kokoro_voice_file

        voice = tmp_path / "zf_087.pt"
        voice.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:deadbeef\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            assert is_valid_kokoro_voice_file(voice) is False
            assert is_valid_kokoro_voice_file(voice) is False
        messages = [record.message for record in caplog.records if "zf_087.pt" in record.message]
        assert len(messages) == 1

    def test_lfs_pointer_model_and_voice_are_not_used_locally(self, tmp_path):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.engine import TTSEngine
        from kokoro_tts.kokoro_assets import has_valid_kokoro_local_assets, is_valid_kokoro_voice_file

        model_dir = tmp_path / "models"
        voices = model_dir / "voices"
        voices.mkdir(parents=True)
        (model_dir / "kokoro-v1_1-zh.pth").write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:deadbeef\n"
            "size 327247856\n",
            encoding="utf-8",
        )
        (model_dir / "config.json").write_text("{}", encoding="utf-8")
        voice_file = voices / "zm_010.pt"
        voice_file.write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:deadbeef\n"
            "size 523331\n",
            encoding="utf-8",
        )

        engine = TTSEngine(TTSConfig(model_dir=model_dir))
        assert has_valid_kokoro_local_assets(model_dir) is False
        assert is_valid_kokoro_voice_file(voice_file) is False
        assert engine._resolve_voice_for_pipeline("zm_010") == "zm_010"


class TestMossProductionDefaults:
    def test_moss_auto_text_rules_keep_technical_mixed_text(self):
        from kokoro_tts.moss.text import clean_text

        text = "AngeVoice v2.6.5.3.2 调用 OpenAI API，地址是 192.168.1.2:8101。"
        cleaned = clean_text(text, apply_angevoice_rules="auto", model="moss")
        assert "v2.6.5.3.2" in cleaned
        assert "OpenAI API" in cleaned
        assert "192.168.1.2:8101" in cleaned

    def test_moss_auto_text_rules_still_normalize_chinese_date(self):
        from kokoro_tts.moss.text import clean_text

        cleaned = clean_text("今天是2026-05-20。", apply_angevoice_rules="auto", model="moss")
        assert "二零二六年五月二十日" in cleaned


    def test_moss_mixed_english_policy_translates_common_workplace_text(self):
        from kokoro_tts.moss.text import clean_text

        text = (
            "被各种deadline追着跑，很容易产生anxiety。"
            "做一个self-reflection，明确core competitiveness。"
            "保持work-life balance，提升creativity和productivity，"
            "实现personal growth，成为best version of yourself。"
        )
        cleaned = clean_text(text, apply_angevoice_rules="auto", model="moss")
        assert "deadline" not in cleaned
        assert "anxiety" not in cleaned
        assert "self-reflection" not in cleaned
        assert "core competitiveness" not in cleaned
        assert "work-life balance" not in cleaned
        assert "personal growth" not in cleaned
        assert "best version of yourself" not in cleaned
        assert "截止日期" in cleaned
        assert "焦虑" in cleaned
        assert "自我反思" in cleaned
        assert "核心竞争力" in cleaned
        assert "工作生活平衡" in cleaned
        assert "个人成长" in cleaned
        assert "最好的自己" in cleaned

    def test_moss_mixed_english_policy_can_preserve_original_words(self):
        from kokoro_tts.moss.text import clean_text

        cleaned = clean_text("deadline 和 anxiety", apply_angevoice_rules="auto", model="moss", mixed_english_policy="preserve")
        assert "deadline" in cleaned
        assert "anxiety" in cleaned

    def test_moss_vram_snapshot_ttl_reuses_recent_probe(self, monkeypatch):
        from kokoro_tts.config import TTSConfig
        from kokoro_tts.moss.vram import VramSnapshot
        import kokoro_tts.moss_engine as moss_engine_module
        from kokoro_tts.moss_engine import MossNanoEngine

        calls = {"count": 0}

        def fake_snapshot():
            calls["count"] += 1
            return VramSnapshot(True, free_mb=7000, total_mb=7680, source="test")

        monkeypatch.setattr(moss_engine_module, "get_cuda_vram_snapshot", fake_snapshot)
        engine = MossNanoEngine(
            TTSConfig(moss_vram_guard_enabled=True, moss_vram_snapshot_ttl_seconds=60),
            execution_provider="cuda",
            engine_id="moss-nano-cuda",
        )
        assert engine._effective_segment_length() == 120
        assert engine._effective_text_tokens() == 56
        assert calls["count"] == 1
