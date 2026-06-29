"""Admin runtime configuration schema aggregation and persistence."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .fields import AdminConfigField
from .groups import cache, core, moss, resources, security, streaming, text, zipvoice

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:  # pragma: no cover - Docker/fnOS deployments provide fcntl.
    fcntl = None

_RUNTIME_CONFIG_LOCK = threading.RLock()


@contextmanager
def _runtime_config_file_lock(path: Path):
    """Serialize runtime-config read/modify/write across threads and workers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _RUNTIME_CONFIG_LOCK:
        with lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist admin runtime configuration without exposing a torn JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temp = Path(handle.name)
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        temp = None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


ADMIN_CONFIG_GROUPS = OrderedDict(
    [
        ("kokoro", "Kokoro"),
        ("moss", "MOSS-TTS-Nano"),
        ("zipvoice", "ZipVoice"),
        ("text", "文本与词典"),
        ("service", "服务与存储"),
        ("audio", "格式转码"),
        ("security", "安全访问"),
    ]
)

_FIELD_ORDER = (
        "angevoice_tn_engine",
        "default_speed",
        "segment_length",
        "moss_segment_length",
        "moss_voice_clone_max_text_tokens",
        "moss_max_new_frames",
        "moss_max_silence_ms",
        "moss_crossfade_ms",
        "moss_segment_pause_ms",
        "moss_runtime_pause_max_ms",
        "moss_output_target_peak",
        "moss_output_gain",
        "moss_audio_polish_enabled",
        "moss_trim_silence_enabled",
        "moss_mixed_english_policy",
        "moss_realtime_streaming_decode",
        "stream_chunk_seconds",
        "stream_prebuffer_seconds",
        "kokoro_process_isolation_enabled",
        "moss_stream_chunk_seconds",
        "moss_stream_prebuffer_seconds",
        "moss_stream_queue_max_items",
        "max_concurrent_requests",
        "request_timeout_seconds",
        "model_idle_timeout_seconds",
        "model_idle_check_interval",
        "model_idle_unload_current",
        "restart_after_idle_unload_enabled",
        "restart_after_idle_unload_delay_seconds",
        "restart_after_idle_unload_cooldown_seconds",
        "restart_after_idle_unload_exit_code",
        "startup_preload_enabled",
        "startup_preload_model",
        "engine_process_kill_grace_seconds",
        "cache_max_items",
        "cache_max_bytes",
        "cache_skip_text_over_chars",
        "cache_skip_audio_over_bytes",
        "save_outputs",
        "ffmpeg_enabled",
        "ffmpeg_binary",
        "mp3_bitrate",
        "audio_opus_bitrate",
        "audio_aac_bitrate",
        "ffmpeg_timeout_seconds",
        "output_max_files",
        "moss_vram_guard_enabled",
        "moss_vram_safe_free_mb",
        "moss_vram_critical_free_mb",
        "moss_low_vram_segment_length",
        "moss_low_vram_max_new_frames",
        "moss_low_vram_text_tokens",
        "moss_disable_full_codec_after_oom",
        "moss_full_codec_oom_cooldown_seconds",
        "moss_vram_snapshot_ttl_seconds",
        "rate_limit_qps",
        "rate_limit_burst",
        "max_queue_length",
        "websocket_max_connections",
        "websocket_max_message_bytes",
        "trust_proxy_headers",
        "public_status_endpoints",
        "model_source",
        "moss_hf_repo",
        "text_single_newline_policy",
        "moss_apply_angevoice_rules",
        "moss_prompt_audio_max_seconds",
        "moss_output_peak_normalize_enabled",
        "moss_output_declick_enabled",
        "moss_output_edge_fade_ms",
        "moss_trim_silence_db",
        "moss_quality_gate_enabled",
        "moss_process_isolation_enabled",
        "zipvoice_process_isolation_enabled",
        "zipvoice_num_steps",
        "zipvoice_prompt_audio_max_seconds",
        "zipvoice_remove_long_sil",
        "zipvoice_guidance_scale",
        "zipvoice_t_shift",
        "zipvoice_target_rms",
        "zipvoice_feat_scale",
)

_FIELDS_BY_KEY = {
    field.key: field
    for field in (
        *text.FIELDS,
        *core.FIELDS,
        *moss.FIELDS,
        *cache.FIELDS,
        *streaming.FIELDS,
        *security.FIELDS,
        *zipvoice.FIELDS,
    )
}

ADMIN_CONFIG_FIELDS: "OrderedDict[str, AdminConfigField]" = OrderedDict(
    (key, _FIELDS_BY_KEY[key]) for key in _FIELD_ORDER
)
ADMIN_CONFIG_PROFILES = resources.ADMIN_CONFIG_PROFILES


def schema_payload() -> dict[str, Any]:
    return {
        "groups": [{"key": key, "label": label} for key, label in ADMIN_CONFIG_GROUPS.items()],
        "fields": [field.as_schema() for field in ADMIN_CONFIG_FIELDS.values()],
        "profiles": [
            {
                "key": key,
                "label": profile["label"],
                "description": profile["description"],
                "values": profile["values"],
            }
            for key, profile in ADMIN_CONFIG_PROFILES.items()
        ],
    }


def config_values(cfg) -> dict[str, Any]:
    return {key: getattr(cfg, key, field.default) for key, field in ADMIN_CONFIG_FIELDS.items()}


def runtime_config_path(cfg) -> Path:
    path = getattr(cfg, "runtime_config_file", None) or Path("/app/config/runtime-config.json")
    return Path(path).expanduser()


def legacy_runtime_config_path(cfg) -> Path:
    return Path(getattr(cfg, "output_dir", "/app/outputs")).expanduser() / "runtime-config.json"


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "y"}:
            return True
        if normalized in {"0", "false", "no", "off", "n"}:
            return False
    raise ValueError("expected boolean")


def _coerce_field(field: AdminConfigField, value: Any) -> Any:
    if field.type == "bool":
        coerced = _coerce_bool(value)
    elif field.type == "int":
        coerced = int(value)
    elif field.type == "float":
        coerced = float(value)
    elif field.type == "choice":
        coerced = str(value).strip().lower()
        allowed = {choice_value for choice_value, _ in field.choices}
        if coerced not in allowed:
            raise ValueError(f"expected one of {sorted(allowed)}")
    else:
        coerced = str(value)

    if isinstance(coerced, (int, float)) and field.type in {"int", "float"}:
        if field.min_value is not None and coerced < field.min_value:
            raise ValueError(f"must be >= {field.min_value}")
        if field.max_value is not None and coerced > field.max_value:
            raise ValueError(f"must be <= {field.max_value}")
    return coerced


def validate_admin_config_values(values: dict[str, Any], *, allow_unknown: bool = False) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if key not in ADMIN_CONFIG_FIELDS:
            if allow_unknown:
                continue
            raise KeyError(f"Unknown admin config field: {key}")
        cleaned[key] = _coerce_field(ADMIN_CONFIG_FIELDS[key], value)
    return cleaned


def apply_admin_config_values(cfg, values: dict[str, Any]) -> tuple[list[str], list[str], bool]:
    cleaned = validate_admin_config_values(values)
    changed: list[str] = []
    restart_required: list[str] = []
    rebuild_moss = False
    for key, value in cleaned.items():
        old = getattr(cfg, key, None)
        if old == value:
            continue
        setattr(cfg, key, value)
        changed.append(key)
        field = ADMIN_CONFIG_FIELDS[key]
        if field.restart:
            restart_required.append(key)
        if field.rebuild_moss:
            rebuild_moss = True
        if key == "model_source":
            cfg.model_source_effective = "auto"
            cfg.model_source_country = ""
            cfg.model_source_hf_reachable = None
            cfg.model_source_modelscope_reachable = None
    return changed, restart_required, rebuild_moss


def profile_values(profile: str) -> dict[str, Any]:
    profile_key = str(profile or "").strip()
    if profile_key not in ADMIN_CONFIG_PROFILES:
        raise KeyError(f"Unknown admin profile: {profile_key}")
    return dict(ADMIN_CONFIG_PROFILES[profile_key]["values"])


def read_runtime_config_values(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("忽略无法读取的 runtime config: %s", path, exc_info=True)
        return {}
    if not isinstance(data, dict):
        return {}
    values = data.get("values", data)
    if not isinstance(values, dict):
        return {}
    return {str(key): value for key, value in values.items()}


def load_runtime_config(cfg) -> list[str]:
    path = runtime_config_path(cfg)
    raw_values = read_runtime_config_values(path)
    legacy_path = legacy_runtime_config_path(cfg)
    if not raw_values and path != legacy_path and legacy_path.exists():
        raw_values = read_runtime_config_values(legacy_path)
        if raw_values:
            payload = {"version": 1, "updated_at": int(time.time()), "values": raw_values, "migrated_from": str(legacy_path)}
            _atomic_write_json(path, payload)
            logger.info("已迁移 Admin runtime config: %s -> %s", legacy_path, path)
    if not raw_values:
        return []
    cleaned: dict[str, Any] = {}
    removed_keys: list[str] = []
    invalid_keys: list[str] = []
    for key, value in raw_values.items():
        if key not in ADMIN_CONFIG_FIELDS:
            removed_keys.append(key)
            continue
        try:
            cleaned[key] = _coerce_field(ADMIN_CONFIG_FIELDS[key], value)
        except (TypeError, ValueError, KeyError):
            invalid_keys.append(key)
            logger.warning("runtime config 字段校验失败，已忽略字段 %s: %r", key, value, exc_info=True)
    if removed_keys:
        logger.info("runtime config 忽略已移除字段: %s", ", ".join(sorted(removed_keys)))
    if invalid_keys:
        logger.warning("runtime config 已跳过无效字段: %s", ", ".join(sorted(invalid_keys)))
    if not cleaned and raw_values:
        logger.warning("runtime config 未包含可加载的有效字段: %s", path)
    if removed_keys or invalid_keys:
        _atomic_write_json(path, {"version": 1, "updated_at": int(time.time()), "values": cleaned})
        logger.info("已清理 runtime config 中不可用字段并保留有效设置: %s", path)
    for key, value in cleaned.items():
        setattr(cfg, key, value)
    logger.info("已加载 Admin runtime config: %s (%d fields)", path, len(cleaned))
    return list(cleaned)


def save_runtime_config_values(cfg, changed_values: dict[str, Any]) -> Path:
    path = runtime_config_path(cfg)
    cleaned_changes = validate_admin_config_values(changed_values)
    with _runtime_config_file_lock(path):
        existing = read_runtime_config_values(path)
        merged = dict(existing)
        merged.update(cleaned_changes)
        payload = {
            "version": 1,
            "updated_at": int(time.time()),
            "values": merged,
        }
        _atomic_write_json(path, payload)
    return path


def runtime_config_info(cfg) -> dict[str, Any]:
    path = runtime_config_path(cfg)
    values = read_runtime_config_values(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "field_count": len(values),
        "values": values,
    }


def delete_runtime_config(cfg) -> bool:
    path = runtime_config_path(cfg)
    with _runtime_config_file_lock(path):
        if not path.exists():
            return False
        path.unlink()
        return True


def export_env_patch(values: dict[str, Any], *, only: list[str] | None = None) -> str:
    selected = only or list(ADMIN_CONFIG_FIELDS)
    lines: list[str] = []
    for key in selected:
        if key not in ADMIN_CONFIG_FIELDS or key not in values:
            continue
        field = ADMIN_CONFIG_FIELDS[key]
        value = values[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{field.env}={rendered}")
    return "\n".join(lines) + ("\n" if lines else "")
