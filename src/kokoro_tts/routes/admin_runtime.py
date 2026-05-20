"""AngeVoice 管理后台运行时辅助函数。"""

from __future__ import annotations

import os
from pathlib import Path

from ..admin_config_schema import (
    ADMIN_CONFIG_FIELDS,
    apply_admin_config_values,
    config_values,
    delete_runtime_config,
    export_env_patch,
    profile_values,
    runtime_config_info,
    runtime_config_path,
    save_runtime_config_values,
    schema_payload,
)
from .admin_models import AdminConfigPatch


def _apply_quality_runtime_guards(cfg) -> list[str]:
    """对实时性/质量/显存参数做联动防呆，避免高风险组合。"""
    adjusted: list[str] = []

    # 防止临界阈值 >= 安全阈值，导致保护逻辑不稳定。
    safe_free = int(getattr(cfg, "moss_vram_safe_free_mb", 1200) or 0)
    critical_free = int(getattr(cfg, "moss_vram_critical_free_mb", 600) or 0)
    if safe_free > 0 and critical_free >= safe_free:
        cfg.moss_vram_critical_free_mb = max(0, safe_free - 100)
        adjusted.append("moss_vram_critical_free_mb")

    # 低延迟实时解码时，强制保持预缓冲不小于一个分包，减少首播抖动和断续。
    if bool(getattr(cfg, "moss_realtime_streaming_decode", True)):
        chunk = float(getattr(cfg, "moss_stream_chunk_seconds", 0.4) or 0.4)
        prebuffer = float(getattr(cfg, "moss_stream_prebuffer_seconds", 0.75) or 0.0)
        min_prebuffer = max(0.35, chunk)
        if prebuffer < min_prebuffer:
            cfg.moss_stream_prebuffer_seconds = min_prebuffer
            adjusted.append("moss_stream_prebuffer_seconds")

    # 声音克隆文本 token 上限不应超过 MOSS 分句长度的一半附近，避免单段过重导致显存突增。
    segment_length = int(getattr(cfg, "moss_segment_length", 120) or 120)
    token_limit = int(getattr(cfg, "moss_voice_clone_max_text_tokens", 56) or 56)
    soft_cap = max(40, int(segment_length * 0.5))
    if token_limit > soft_cap:
        cfg.moss_voice_clone_max_text_tokens = soft_cap
        adjusted.append("moss_voice_clone_max_text_tokens")

    # 输出增益高于目标峰值的 1.2 倍时，容易触发削波；这里做软约束。
    target_peak = float(getattr(cfg, "moss_output_target_peak", 0.86) or 0.86)
    gain = float(getattr(cfg, "moss_output_gain", 0.94) or 0.94)
    max_gain = min(2.0, max(0.1, target_peak * 1.2))
    if gain > max_gain:
        cfg.moss_output_gain = max_gain
        adjusted.append("moss_output_gain")

    return adjusted


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return value[:2] + "***"
    return value[:6] + "..." + value[-4:]


def security_snapshot(cfg, *, reveal: bool = False) -> dict:
    key = cfg.api_key or ""
    key_file = Path(getattr(cfg, "api_key_file", "") or "")
    return {
        "api_key_enabled": bool(key),
        "api_key_preview": mask_secret(key),
        "api_key": key if reveal else "",
        "api_key_auto_generated": bool(getattr(cfg, "api_key_auto_generated", False)),
        "api_key_file": str(key_file) if str(key_file) else "",
        "api_key_file_exists": bool(key_file.exists()) if str(key_file) else False,
    }


def config_snapshot(cfg) -> dict:
    data = {
        "enabled_models": cfg.enabled_models,
        "default_model": cfg.default_model,
        "max_concurrent_requests": cfg.max_concurrent_requests,
        "request_timeout_seconds": cfg.request_timeout_seconds,
        "idle_timeout_seconds": cfg.model_idle_timeout_seconds,
        "idle_check_interval": cfg.model_idle_check_interval,
        "idle_unload_current": getattr(cfg, "model_idle_unload_current", True),
        "moss_execution_provider": cfg.moss_execution_provider,
        "moss_stream_chunk_seconds": cfg.moss_stream_chunk_seconds,
        "moss_segment_length": cfg.moss_segment_length,
        "moss_voice_clone_max_text_tokens": cfg.moss_voice_clone_max_text_tokens,
        "moss_max_new_frames": cfg.moss_max_new_frames,
        "moss_stream_prebuffer_seconds": getattr(cfg, "moss_stream_prebuffer_seconds", 0.75),
        "moss_max_silence_ms": getattr(cfg, "moss_max_silence_ms", 480),
        "moss_crossfade_ms": getattr(cfg, "moss_crossfade_ms", 12),
        "moss_segment_pause_ms": getattr(cfg, "moss_segment_pause_ms", 80),
        "moss_runtime_pause_max_ms": getattr(cfg, "moss_runtime_pause_max_ms", 350),
        "moss_output_target_peak": getattr(cfg, "moss_output_target_peak", 0.86),
        "moss_output_gain": getattr(cfg, "moss_output_gain", 0.94),
        "moss_audio_polish_enabled": getattr(cfg, "moss_audio_polish_enabled", True),
        "moss_trim_silence_enabled": getattr(cfg, "moss_trim_silence_enabled", True),
        "moss_realtime_streaming_decode": cfg.moss_realtime_streaming_decode,
        "moss_process_isolation_enabled": cfg.moss_process_isolation_enabled,
        "moss_quality_gate_enabled": cfg.moss_quality_gate_enabled,
        "moss_vram_guard_enabled": getattr(cfg, "moss_vram_guard_enabled", True),
        "moss_vram_safe_free_mb": getattr(cfg, "moss_vram_safe_free_mb", 1200),
        "moss_vram_critical_free_mb": getattr(cfg, "moss_vram_critical_free_mb", 600),
        "moss_vram_snapshot_ttl_seconds": getattr(cfg, "moss_vram_snapshot_ttl_seconds", 10.0),
        "moss_low_vram_segment_length": getattr(cfg, "moss_low_vram_segment_length", 96),
        "cache_max_bytes": getattr(cfg, "cache_max_bytes", 0),
        "cache_skip_text_over_chars": getattr(cfg, "cache_skip_text_over_chars", 0),
        "cache_skip_audio_over_bytes": getattr(cfg, "cache_skip_audio_over_bytes", 0),
        "text_single_newline_policy": getattr(cfg, "text_single_newline_policy", "auto"),
        "moss_apply_angevoice_rules": getattr(cfg, "moss_apply_angevoice_rules", "auto"),
        "rate_limit_qps": cfg.rate_limit_qps,
        "rate_limit_burst": cfg.rate_limit_burst,
        "max_queue_length": cfg.max_queue_length,
        "trust_proxy_headers": getattr(cfg, "trust_proxy_headers", False),
        "public_status_endpoints": getattr(cfg, "public_status_endpoints", True),
        "model_source": getattr(cfg, "model_source", "auto"),
        "model_source_effective": getattr(cfg, "model_source_effective", "auto"),
        "model_source_hf_reachable": getattr(cfg, "model_source_hf_reachable", None),
        "model_source_modelscope_reachable": getattr(cfg, "model_source_modelscope_reachable", None),
    }
    data.update(config_values(cfg))
    data["runtime_config_file"] = str(runtime_config_path(cfg))
    data["runtime_config"] = runtime_config_info(cfg)
    return data


def apply_config_patch(cfg, patch: AdminConfigPatch) -> tuple[list[str], list[str], bool]:
    values = patch.model_dump(exclude_none=True)
    changed, restart_required, rebuild_moss = apply_admin_config_values(cfg, values)
    adjusted = _apply_quality_runtime_guards(cfg)
    for key in adjusted:
        if key not in changed:
            changed.append(key)
        # guards 调整了 rebuild_moss 字段时，需要重新标记
        field_def = ADMIN_CONFIG_FIELDS.get(key)
        if field_def and getattr(field_def, "rebuild_moss", False):
            rebuild_moss = True
    if changed:
        save_runtime_config_values(cfg, {name: getattr(cfg, name) for name in changed})
    return changed, restart_required, rebuild_moss


def apply_config_profile(cfg, profile: str) -> tuple[list[str], list[str], bool]:
    values = profile_values(profile)
    changed, restart_required, rebuild_moss = apply_admin_config_values(cfg, values)
    adjusted = _apply_quality_runtime_guards(cfg)
    for key in adjusted:
        if key not in changed:
            changed.append(key)
        field_def = ADMIN_CONFIG_FIELDS.get(key)
        if field_def and getattr(field_def, "rebuild_moss", False):
            rebuild_moss = True
    if changed:
        save_runtime_config_values(cfg, {name: getattr(cfg, name) for name in changed})
    return changed, restart_required, rebuild_moss


def admin_config_payload(cfg) -> dict:
    values = config_values(cfg)
    info = runtime_config_info(cfg)
    return {
        "config": config_snapshot(cfg),
        "values": values,
        "schema": schema_payload(),
        "runtime_config_file": str(runtime_config_path(cfg)),
        "runtime_config": info,
        "env_patch": export_env_patch(values),
    }


def rotate_api_key(cfg) -> str:
    from ..config_api_key import generate_api_key

    key = generate_api_key()
    cfg.api_key = key
    cfg.api_key_auto_generated = True
    key_file = Path(getattr(cfg, "api_key_file", "") or cfg.output_dir / ".angevoice-api-key").expanduser()
    cfg.api_key_file = key_file
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key + "\n", encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    os.environ["KOKORO_API_KEY"] = key
    return key


def clear_runtime_config_file(cfg) -> bool:
    return delete_runtime_config(cfg)
