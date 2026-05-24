"""Admin-editable runtime configuration schema.

The admin console uses this module as the single source for editable fields,
profile presets, validation, runtime persistence, and ENV patch export.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class AdminConfigField:
    key: str
    env: str
    label: str
    group: str
    type: str
    default: Any
    min_value: float | int | None = None
    max_value: float | int | None = None
    step: float | int | None = None
    choices: tuple[tuple[str, str], ...] = ()
    restart: bool = False
    rebuild_moss: bool = False
    advanced: bool = False
    help: str = ""

    def as_schema(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "env": self.env,
            "label": self.label,
            "group": self.group,
            "type": self.type,
            "default": self.default,
            "min": self.min_value,
            "max": self.max_value,
            "step": self.step,
            "choices": [{"value": value, "label": label} for value, label in self.choices],
            "restart": self.restart,
            "rebuild_moss": self.rebuild_moss,
            "advanced": self.advanced,
            "help": self.help,
        }


ADMIN_CONFIG_GROUPS = OrderedDict(
    [
        ("kokoro", "Kokoro"),
        ("moss", "MOSS-TTS-Nano"),
        ("zipvoice", "ZipVoice"),
        ("service", "服务与存储"),
        ("security", "安全访问"),
    ]
)


ADMIN_CONFIG_FIELDS: "OrderedDict[str, AdminConfigField]" = OrderedDict()


def _field(*args, **kwargs) -> None:
    field = AdminConfigField(*args, **kwargs)
    ADMIN_CONFIG_FIELDS[field.key] = field


_field(
    "default_speed",
    "KOKORO_DEFAULT_SPEED",
    "Kokoro 默认语速",
    "kokoro",
    "float",
    1.0,
    0.5,
    2.0,
    0.05,
    help="MOSS 暂不支持语速调节，此项只影响 Kokoro。",
)
_field(
    "segment_length",
    "KOKORO_SEGMENT_LENGTH",
    "Kokoro 分句长度",
    "kokoro",
    "int",
    160,
    60,
    400,
    10,
    help="Kokoro 长文本切片长度，常用 120-200。",
)
_field(
    "moss_segment_length",
    "MOSS_SEGMENT_LENGTH",
    "MOSS 分句长度",
    "moss",
    "int",
    120,
    80,
    600,
    10,
    rebuild_moss=True,
    help="NAS/P4 默认 120，牺牲少量吞吐换取中英文混合和长文本稳定；12GB+ 可在后台切换长文本旁白预设。",
)
_field(
    "moss_voice_clone_max_text_tokens",
    "MOSS_VOICE_CLONE_MAX_TEXT_TOKENS",
    "MOSS token 上限",
    "moss",
    "int",
    56,
    20,
    200,
    1,
    rebuild_moss=True,
)
_field(
    "moss_max_new_frames",
    "MOSS_MAX_NEW_FRAMES",
    "MOSS 生成帧预算",
    "moss",
    "int",
    320,
    64,
    1200,
    1,
    rebuild_moss=True,
)
_field(
    "moss_max_silence_ms",
    "MOSS_MAX_SILENCE_MS",
    "最大静音",
    "moss",
    "float",
    480.0,
    0,
    5000,
    10,
    help="最终音频中超过该长度的静音会被压缩。",
)
_field(
    "moss_crossfade_ms",
    "MOSS_CROSSFADE_MS",
    "Crossfade",
    "moss",
    "float",
    12.0,
    0,
    120,
    1,
)
_field(
    "moss_segment_pause_ms",
    "MOSS_SEGMENT_PAUSE_MS",
    "段间停顿",
    "moss",
    "float",
    80.0,
    0,
    2000,
    10,
)
_field(
    "moss_runtime_pause_max_ms",
    "MOSS_RUNTIME_PAUSE_MAX_MS",
    "Runtime 停顿上限",
    "moss",
    "float",
    350.0,
    0,
    3000,
    10,
)
_field(
    "moss_output_target_peak",
    "MOSS_OUTPUT_TARGET_PEAK",
    "目标峰值",
    "moss",
    "float",
    0.86,
    0.1,
    1.0,
    0.01,
)
_field(
    "moss_output_gain",
    "MOSS_OUTPUT_GAIN",
    "输出增益",
    "moss",
    "float",
    0.94,
    0.1,
    2.0,
    0.01,
)
_field(
    "moss_audio_polish_enabled",
    "MOSS_AUDIO_POLISH_ENABLED",
    "音频自然化",
    "moss",
    "bool",
    True,
)
_field(
    "moss_trim_silence_enabled",
    "MOSS_TRIM_SILENCE_ENABLED",
    "裁剪首尾静音",
    "moss",
    "bool",
    True,
)

_field(
    "moss_mixed_english_policy",
    "MOSS_MIXED_ENGLISH_POLICY",
    "中英文混排",
    "moss",
    "choice",
    "translate",
    choices=(
        ("translate", "常见英文转自然中文"),
        ("preserve", "保留英文原文"),
        ("spell", "仅替换已知词组"),
    ),
    rebuild_moss=False,
    help="MOSS 对中文句子夹英文较敏感。默认 translate 会把 deadline、work-life balance 等常见词组转成中文，减少停顿、怪声和尾部漂移。",
)

_field(
    "moss_realtime_streaming_decode",
    "MOSS_REALTIME_STREAMING_DECODE",
    "逐帧流式",
    "moss",
    "bool",
    True,
)
_field(
    "stream_chunk_seconds",
    "KOKORO_STREAM_CHUNK_SECONDS",
    "Kokoro 分包秒",
    "kokoro",
    "float",
    0.55,
    0.05,
    2.0,
    0.01,
)
_field(
    "stream_prebuffer_seconds",
    "KOKORO_STREAM_PREBUFFER_SECONDS",
    "Kokoro 预缓冲",
    "kokoro",
    "float",
    0.25,
    0,
    3.0,
    0.05,
)
_field(
    "moss_stream_chunk_seconds",
    "MOSS_STREAM_CHUNK_SECONDS",
    "MOSS 分包秒",
    "moss",
    "float",
    0.40,
    0.05,
    2.0,
    0.01,
)
_field(
    "moss_stream_prebuffer_seconds",
    "MOSS_STREAM_PREBUFFER_SECONDS",
    "MOSS 预缓冲",
    "moss",
    "float",
    0.75,
    0,
    3.0,
    0.05,
)
_field(
    "moss_stream_queue_max_items",
    "MOSS_STREAM_QUEUE_MAX_ITEMS",
    "MOSS 流式队列",
    "moss",
    "int",
    8,
    1,
    64,
    1,
)
_field(
    "max_concurrent_requests",
    "KOKORO_MAX_CONCURRENT_REQUESTS",
    "最大并发",
    "service",
    "int",
    1,
    1,
    64,
    1,
    restart=True,
)
_field(
    "request_timeout_seconds",
    "KOKORO_REQUEST_TIMEOUT_SECONDS",
    "请求超时",
    "service",
    "float",
    300.0,
    1,
    3600,
    1,
)
_field(
    "model_idle_timeout_seconds",
    "ANGEVOICE_IDLE_TIMEOUT_SECONDS",
    "空闲释放",
    "service",
    "float",
    600.0,
    0,
    86400,
    1,
)
_field(
    "model_idle_check_interval",
    "ANGEVOICE_IDLE_CHECK_INTERVAL",
    "空闲检查间隔",
    "service",
    "float",
    30.0,
    5,
    3600,
    1,
    advanced=True,
)
_field(
    "model_idle_unload_current",
    "ANGEVOICE_IDLE_UNLOAD_CURRENT",
    "释放当前模型",
    "service",
    "bool",
    True,
)
_field(
    "cache_max_items",
    "KOKORO_CACHE_MAX_ITEMS",
    "音频缓存数量",
    "service",
    "int",
    64,
    0,
    2000,
    1,
)
_field(
    "cache_max_bytes",
    "KOKORO_CACHE_MAX_BYTES",
    "缓存上限 Bytes",
    "service",
    "int",
    536870912,
    0,
    8589934592,
    1048576,
    help="0 表示不限制；NAS 默认约 512MB。",
)
_field(
    "cache_skip_text_over_chars",
    "KOKORO_CACHE_SKIP_TEXT_OVER_CHARS",
    "长文本跳过缓存",
    "service",
    "int",
    1200,
    0,
    100000,
    100,
    help="超过该字符数的 HTTP 合成结果不写入缓存，0 表示关闭。",
)
_field(
    "cache_skip_audio_over_bytes",
    "KOKORO_CACHE_SKIP_AUDIO_OVER_BYTES",
    "大音频跳过缓存",
    "service",
    "int",
    20971520,
    0,
    2147483647,
    1048576,
    help="超过该大小的音频不写入缓存，0 表示关闭。",
)
_field(
    "save_outputs",
    "ANGEVOICE_SAVE_OUTPUTS",
    "保存合成结果",
    "service",
    "bool",
    False,
)
_field(
    "output_max_files",
    "ANGEVOICE_OUTPUT_MAX_FILES",
    "保留文件数",
    "service",
    "int",
    1000,
    0,
    100000,
    1,
)
_field(
    "moss_vram_guard_enabled",
    "MOSS_VRAM_GUARD_ENABLED",
    "启用显存保护",
    "moss",
    "bool",
    True,
    rebuild_moss=False,
    help="8GB/P4/NAS 推荐开启。",
)
_field(
    "moss_vram_safe_free_mb",
    "MOSS_VRAM_SAFE_FREE_MB",
    "安全剩余显存 MB",
    "moss",
    "int",
    1200,
    0,
    65536,
    100,
)
_field(
    "moss_vram_critical_free_mb",
    "MOSS_VRAM_CRITICAL_FREE_MB",
    "临界剩余显存 MB",
    "moss",
    "int",
    600,
    0,
    65536,
    100,
)
_field(
    "moss_low_vram_segment_length",
    "MOSS_LOW_VRAM_SEGMENT_LENGTH",
    "低显存分句长度",
    "moss",
    "int",
    96,
    60,
    400,
    10,
)
_field(
    "moss_low_vram_max_new_frames",
    "MOSS_LOW_VRAM_MAX_NEW_FRAMES",
    "低显存帧预算",
    "moss",
    "int",
    280,
    64,
    800,
    1,
)
_field(
    "moss_low_vram_text_tokens",
    "MOSS_LOW_VRAM_TEXT_TOKENS",
    "低显存 token 上限",
    "moss",
    "int",
    48,
    20,
    160,
    1,
)
_field(
    "moss_disable_full_codec_after_oom",
    "MOSS_DISABLE_FULL_CODEC_AFTER_OOM",
    "OOM 后禁用整段解码",
    "moss",
    "bool",
    True,
)
_field(
    "moss_full_codec_oom_cooldown_seconds",
    "MOSS_FULL_CODEC_OOM_COOLDOWN_SECONDS",
    "OOM 冷却秒",
    "moss",
    "float",
    600.0,
    0,
    86400,
    10,
)
_field(
    "moss_vram_snapshot_ttl_seconds",
    "MOSS_VRAM_SNAPSHOT_TTL_SECONDS",
    "显存快照 TTL",
    "moss",
    "float",
    10.0,
    0,
    3600,
    1,
    help="缓存 torch/nvidia-smi 显存查询结果，减少长文本流式过程中的同步卡顿。0 表示每次都查。",
)
_field(
    "rate_limit_qps",
    "KOKORO_RATE_LIMIT_QPS",
    "限流 QPS",
    "security",
    "float",
    0.0,
    0,
    1000,
    0.1,
    restart=True,
)
_field(
    "rate_limit_burst",
    "KOKORO_RATE_LIMIT_BURST",
    "限流突发",
    "security",
    "int",
    5,
    0,
    10000,
    1,
    restart=True,
)
_field(
    "max_queue_length",
    "KOKORO_MAX_QUEUE_LENGTH",
    "队列上限",
    "security",
    "int",
    0,
    0,
    10000,
    1,
    restart=True,
)
_field(
    "trust_proxy_headers",
    "KOKORO_TRUST_PROXY_HEADERS",
    "信任反代 IP",
    "security",
    "bool",
    False,
    restart=True,
)
_field(
    "public_status_endpoints",
    "KOKORO_PUBLIC_STATUS_ENDPOINTS",
    "公开模型列表",
    "security",
    "bool",
    True,
)
_field(
    "model_source",
    "ANGEVOICE_MODEL_SOURCE",
    "模型下载源",
    "security",
    "choice",
    "auto",
    choices=(("auto", "auto 自动"), ("modelscope", "ModelScope"), ("huggingface", "Hugging Face"), ("offline", "offline 离线")),
)
_field(
    "moss_hf_repo",
    "MOSS_HF_REPO",
    "MOSS HF 仓库",
    "moss",
    "str",
    "",
    restart=True,
    help="可选。默认留空并使用 ModelScope 仓库备用下载 MOSS ONNX 资产；如上游提供 Hugging Face 仓库，可在这里填写。",    advanced=True,
)
_field(
    "text_single_newline_policy",
    "ANGEVOICE_SINGLE_NEWLINE_POLICY",
    "单换行策略",
    "service",
    "choice",
    "auto",
    choices=(("auto", "auto 智能合并"), ("preserve", "preserve 保留停顿"), ("space", "space 当作空格")),
    help="中文网页/小说复制常有硬换行；auto 会尽量合并段内换行，只保留空行段落。",    advanced=True,
)
_field(
    "moss_apply_angevoice_rules",
    "MOSS_APPLY_ANGEVOICE_RULES",
    "MOSS 文本规则",
    "moss",
    "choice",
    "auto",
    choices=(("auto", "auto 中英文混排智能处理"), ("true", "true 完整中文规则"), ("false", "false 仅温和清理")),
    rebuild_moss=False,
    help="auto 会对中文为主文本应用完整中文规则，对 URL、版本号、API、英文缩写等中英文混排文本保守处理。",    advanced=True,
)
_field(
    "moss_prompt_audio_max_seconds",
    "MOSS_PROMPT_AUDIO_MAX_SECONDS",
    "参考音频秒数",
    "moss",
    "float",
    8.0,
    0,
    60,
    0.5,
    rebuild_moss=True,    advanced=True,
)
_field(
    "moss_output_peak_normalize_enabled",
    "MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED",
    "峰值保护",
    "moss",
    "bool",
    True,    advanced=True,
)
_field(
    "moss_output_declick_enabled",
    "MOSS_OUTPUT_DECLICK_ENABLED",
    "去爆音",
    "moss",
    "bool",
    True,    advanced=True,
)
_field(
    "moss_output_edge_fade_ms",
    "MOSS_OUTPUT_EDGE_FADE_MS",
    "边缘淡入淡出",
    "moss",
    "float",
    1.5,
    0,
    20,
    0.5,    advanced=True,
)
_field(
    "moss_trim_silence_db",
    "MOSS_TRIM_SILENCE_DB",
    "静音阈值 dB",
    "moss",
    "float",
    -45.0,
    -90,
    -10,
    1,    advanced=True,
)
_field(
    "moss_quality_gate_enabled",
    "MOSS_QUALITY_GATE_ENABLED",
    "MOSS 质量自检",
    "moss",
    "bool",
    True,
    rebuild_moss=True,    advanced=True,
)
_field(
    "moss_process_isolation_enabled",
    "MOSS_PROCESS_ISOLATION_ENABLED",
    "MOSS 进程隔离",
    "moss",
    "bool",
    False,
    rebuild_moss=True,
    help="建议保持开启：超时或底层卡死时可终止隔离 worker 并自动恢复，避免引擎永久阻塞。",    advanced=True,
)


# ZipVoice 参数单独成组；均按后续请求读取，不改变产品级模型名称。
_field(
    "zipvoice_num_steps",
    "ZIPVOICE_NUM_STEPS",
    "采样步数",
    "zipvoice",
    "int",
    8,
    1,
    32,
    1,
    help="步数提高可能改善质量但会增加延迟；CPU/NAS 建议先用 8，GPU 可测试 16。",
)
_field(
    "zipvoice_prompt_audio_max_seconds",
    "ZIPVOICE_PROMPT_AUDIO_MAX_SECONDS",
    "参考音频最长秒数",
    "zipvoice",
    "float",
    15.0,
    3.0,
    30.0,
    0.5,
    help="官方建议单人参考音频短于 3 秒；此项是产品保护上限，超过 3 秒只提示风险。",
)
_field(
    "zipvoice_remove_long_sil",
    "ZIPVOICE_REMOVE_LONG_SIL",
    "移除生成长静音",
    "zipvoice",
    "bool",
    False,
    help="仅在生成音频存在异常长停顿时尝试开启，可能改变自然停顿。",
)
_field(
    "zipvoice_guidance_scale",
    "ZIPVOICE_GUIDANCE_SCALE",
    "Guidance Scale",
    "zipvoice",
    "float",
    3.0,
    0.0,
    20.0,
    0.1,
    advanced=True,
)
_field(
    "zipvoice_t_shift",
    "ZIPVOICE_T_SHIFT",
    "T-Shift",
    "zipvoice",
    "float",
    0.5,
    0.01,
    1.0,
    0.01,
    advanced=True,
)
_field(
    "zipvoice_target_rms",
    "ZIPVOICE_TARGET_RMS",
    "目标 RMS",
    "zipvoice",
    "float",
    0.1,
    0.0,
    1.0,
    0.01,
    advanced=True,
)
_field(
    "zipvoice_feat_scale",
    "ZIPVOICE_FEAT_SCALE",
    "特征缩放",
    "zipvoice",
    "float",
    0.1,
    0.001,
    10.0,
    0.01,
    advanced=True,
)


ADMIN_CONFIG_PROFILES: dict[str, dict[str, Any]] = {
    "deploy_lan_default": {
        "label": "部署预设：局域网易用",
        "description": "适合家庭/NAS/内网，保留易访问体验并启用基础保护。",
        "values": {
            "public_status_endpoints": True,
            "trust_proxy_headers": False,
            "rate_limit_qps": 0.0,
            "rate_limit_burst": 5,
            "max_queue_length": 0,
        },
    },
    "deploy_public_hardened": {
        "label": "部署预设：公网加固",
        "description": "公网暴露建议：收紧枚举接口并启用限流/队列保护。",
        "values": {
            "public_status_endpoints": False,
            "trust_proxy_headers": False,
            "rate_limit_qps": 3.0,
            "rate_limit_burst": 6,
            "max_queue_length": 64,
        },
    },
    "nas_stable": {
        "label": "NAS 稳定",
        "description": "默认推荐：8GB/P4/家用 NAS，优先中英文混合稳定、减少卡顿和低音量。",
        "values": {
            "moss_segment_length": 120,
            "moss_voice_clone_max_text_tokens": 56,
            "moss_max_new_frames": 320,
            "moss_stream_chunk_seconds": 0.40,
            "moss_stream_queue_max_items": 8,
            "moss_stream_prebuffer_seconds": 0.75,
            "moss_max_silence_ms": 480,
            "moss_crossfade_ms": 12,
            "moss_segment_pause_ms": 80,
            "moss_runtime_pause_max_ms": 350,
            "moss_output_target_peak": 0.86,
            "moss_output_gain": 0.94,
            "moss_realtime_streaming_decode": True,
            "moss_vram_guard_enabled": True,
            "moss_apply_angevoice_rules": "auto",
            "moss_mixed_english_policy": "translate",
            "moss_vram_snapshot_ttl_seconds": 10.0,
        },
    },
    "nas_deep_sleep_cpu": {
        "label": "CPU 低配 NAS / Deep Sleep",
        "description": "低内存模式：降低缓存并在 180 秒空闲后释放当前模型；适用于内存受限设备，可结合唤醒延迟调整。",
        "values": {
            "model_idle_timeout_seconds": 180.0,
            "model_idle_check_interval": 30.0,
            "model_idle_unload_current": True,
            "cache_max_items": 16,
            "cache_max_bytes": 134217728,
            "cache_skip_text_over_chars": 400,
            "cache_skip_audio_over_bytes": 8388608,
            "max_concurrent_requests": 1,
        },
    },
    "balanced": {
        "label": "均衡推荐",
        "description": "10-12GB 显存或较强 CPU，兼顾自然度和稳定。",
        "values": {
            "moss_segment_length": 220,
            "moss_voice_clone_max_text_tokens": 80,
            "moss_max_new_frames": 400,
            "moss_stream_chunk_seconds": 0.50,
            "moss_stream_queue_max_items": 8,
            "moss_stream_prebuffer_seconds": 0.55,
            "moss_max_silence_ms": 650,
            "moss_crossfade_ms": 30,
            "moss_runtime_pause_max_ms": 600,
            "moss_realtime_streaming_decode": True,
        },
    },
    "long_narration": {
        "label": "长文本旁白",
        "description": "12GB+ 推荐：更自然，但 8GB/P4 不建议默认。",
        "values": {
            "moss_segment_length": 260,
            "moss_voice_clone_max_text_tokens": 90,
            "moss_max_new_frames": 450,
            "moss_stream_chunk_seconds": 0.55,
            "moss_stream_queue_max_items": 12,
            "moss_stream_prebuffer_seconds": 0.65,
            "moss_max_silence_ms": 760,
            "moss_crossfade_ms": 35,
            "moss_runtime_pause_max_ms": 650,
            "moss_realtime_streaming_decode": True,
        },
    },
    "low_latency": {
        "label": "低延迟流式",
        "description": "短句交互，首包更快。",
        "values": {
            "moss_segment_length": 120,
            "moss_voice_clone_max_text_tokens": 56,
            "moss_max_new_frames": 300,
            "moss_stream_chunk_seconds": 0.32,
            "moss_stream_queue_max_items": 8,
            "moss_stream_prebuffer_seconds": 0.55,
            "moss_crossfade_ms": 10,
            "moss_realtime_streaming_decode": True,
        },
    },
    "clone_quality": {
        "label": "克隆质量优先",
        "description": "16GB+ 推荐：首包更慢，克隆更稳。",
        "values": {
            "moss_segment_length": 240,
            "moss_voice_clone_max_text_tokens": 84,
            "moss_max_new_frames": 440,
            "moss_prompt_audio_max_seconds": 8.0,
            "moss_stream_chunk_seconds": 0.55,
            "moss_stream_prebuffer_seconds": 0.70,
            "moss_stream_queue_max_items": 8,
            "moss_max_silence_ms": 760,
            "moss_crossfade_ms": 35,
            "moss_realtime_streaming_decode": False,
        },
    },
}


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
    try:
        cleaned = validate_admin_config_values(raw_values, allow_unknown=True)
    except Exception:
        logger.warning("忽略包含无效字段的 runtime config: %s", path, exc_info=True)
        return []
    ignored_keys = sorted(set(raw_values) - set(cleaned))
    if ignored_keys:
        logger.info("runtime config 忽略已移除字段: %s", ", ".join(ignored_keys))
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
