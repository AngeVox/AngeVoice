"""代码质量审查反馈的回归测试。"""

from unittest.mock import MagicMock

from kokoro_tts.config import TTSConfig
from kokoro_tts.engine import normalize_text_for_tts
from kokoro_tts.engine_manager import EngineManager, EngineSpec
from kokoro_tts.service_state import ServiceState


def test_large_money_amount_is_read_naturally():
    """十亿以上金额不能被静默跳过，也不能触发高位组异常。"""

    text = normalize_text_for_tts("合同金额为¥1234567890.50。")
    assert "十二亿" in text
    assert "三千四百五十六万" in text
    assert "七千八百九十元五角" in text


def test_model_snapshot_protects_core_identity_fields():
    """运行时 metadata 不应静默覆盖模型基础身份字段。"""

    manager = EngineManager(TTSConfig(enabled_models=["kokoro"], default_model="kokoro"))
    engine = MagicMock()
    engine.is_loaded = True
    engine.is_healthy = True
    engine.metadata.return_value = {
        "id": "evil-id",
        "name": "bad-name",
        "backend": "bad-backend",
        "loaded": True,
        "voices": ["zf_001"],
    }
    manager._engines["kokoro"] = engine

    snapshot = manager._model_snapshot(EngineSpec("kokoro", "Kokoro v1.1 Chinese", "kokoro", "cpu"))
    assert snapshot["id"] == "kokoro"
    assert snapshot["name"] == "Kokoro v1.1 Chinese"
    assert snapshot["backend"] == "kokoro"
    assert snapshot["voices"] == ["zf_001"]


def test_config_get_voices_uses_directory_signature_cache(tmp_path):
    """音色列表应缓存，并在目录变更后自动失效。"""

    model_dir = tmp_path / "models--hexgrad--Kokoro-82M-v1.1-zh"
    voices_dir = model_dir / "voices"
    voices_dir.mkdir(parents=True)
    (voices_dir / "zf_001.pt").write_bytes(b"PK\x03\x04valid")

    config = TTSConfig(model_dir=model_dir)
    assert config.get_voices() == ["zf_001"]
    (voices_dir / "zf_002.pt").write_bytes(b"PK\x03\x04valid")
    # 有些文件系统 mtime 粒度较粗，显式 touch 确保缓存签名变化。
    voices_dir.touch()
    assert config.get_voices() == ["zf_001", "zf_002"]


def test_cache_get_updates_hit_miss_stats_once():
    """缓存命中/未命中统计与读取路径保持一致。"""

    state = ServiceState(TTSConfig(cache_enabled=True, cache_max_items=2))
    assert state.cache_get("missing") is None
    state.cache_set("hit", (b"audio", "audio/wav"), text="短文本")
    assert state.cache_get("hit") == (b"audio", "audio/wav")
    stats = state.snapshot_stats()
    assert stats["cache_misses"] == 1
    assert stats["cache_hits"] == 1


def test_percent_reads_three_digits_as_number():
    """三位以上百分比应按自然数字读法，不应逐位读成一零零。"""

    text = normalize_text_for_tts("完成率达到100%，峰值为12.5%。")
    assert "百分之一百" in text
    assert "百分之一零零" not in text
    assert "百分之十二点五" in text


def test_worker_env_exports_cover_runtime_env_specs():
    """多 worker 模式应继承运行时配置里的关键环境变量。"""

    from kokoro_tts.config_env import BOOL_ENV, FLOAT_ENV, INT_ENV, STR_ENV
    from kokoro_tts.server import _WORKER_ENV_EXPORTS

    all_runtime_envs = set(STR_ENV) | set(INT_ENV) | set(FLOAT_ENV) | set(BOOL_ENV)
    process_level_only = {
        "KOKORO_HOST",
        "KOKORO_PORT",
        "KOKORO_WORKERS",
        "KOKORO_CORS_ORIGINS",
        "KOKORO_API_KEY",
        "KOKORO_AUTO_API_KEY",
    }
    missing = sorted(all_runtime_envs - set(_WORKER_ENV_EXPORTS) - process_level_only)
    assert missing == []
    assert _WORKER_ENV_EXPORTS["ANGEVOICE_IDLE_UNLOAD_CURRENT"] == "model_idle_unload_current"
    assert _WORKER_ENV_EXPORTS["KOKORO_TTS_REQUEST_MAX_BYTES"] == "tts_request_max_bytes"
    assert _WORKER_ENV_EXPORTS["KOKORO_VOICE_UPLOAD_MAX_BYTES"] == "voice_upload_max_bytes"


def test_moss_model_assets_reject_lfs_only_dir(tmp_path):
    """MOSS 目录不能只因非空就被当作有效模型目录。"""

    from kokoro_tts.model_sources import has_valid_moss_model_assets

    model_dir = tmp_path / "MOSS-TTS-Nano-100M-ONNX"
    model_dir.mkdir()
    (model_dir / "decoder.onnx").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:dummy\n"
        "size 123456789\n",
        encoding="utf-8",
    )
    assert not has_valid_moss_model_assets(model_dir)

    real_model = model_dir / "encoder.onnx"
    with real_model.open("wb") as handle:
        handle.seek(1024 * 1024)
        handle.write(b"\0")
    assert has_valid_moss_model_assets(model_dir)


def test_drop_model_unload_failure_keeps_engine_and_marks_pending():
    """模型重建前卸载失败时不能误删引擎，应保留待重建标记。"""

    manager = EngineManager(TTSConfig(enabled_models=["kokoro"], default_model="kokoro"))
    engine = MagicMock()
    engine.unload.side_effect = RuntimeError("cuda unload failed")
    manager._engines["kokoro"] = engine

    assert manager.drop_model("kokoro", force=True, raise_if_busy=False) is False
    assert manager._engines["kokoro"] is engine
    assert "kokoro" in manager._pending_rebuild


def test_get_engine_load_failure_cleanup_catches_unload_fallback_failure():
    """加载失败后，兼容旧 unload() 签名的清理异常不能覆盖原始加载异常。"""

    from unittest.mock import MagicMock

    manager = EngineManager(TTSConfig(enabled_models=["kokoro"], default_model="kokoro"))
    engine = MagicMock()
    engine.is_loaded = False
    engine.load.side_effect = RuntimeError("load failed")
    engine.unload.side_effect = [TypeError("old signature"), RuntimeError("unload failed")]
    manager._engines["kokoro"] = engine

    import pytest

    with pytest.raises(RuntimeError, match="load failed"):
        manager.get_engine("kokoro", load=True)
    assert manager._active_counts["kokoro"] == 0
