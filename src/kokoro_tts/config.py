"""AngeVoice 配置。

配置优先级：
1. 显式函数参数
2. KOKORO_* / ANGEVOICE_* / MOSS_* 环境变量
3. 代码默认值
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Optional

logger = logging.getLogger(__name__)

MODEL_FILENAME = "kokoro-v1_1-zh.pth"
PLACEHOLDER_API_KEYS = {
    "change-me",
    "change-me-to-a-real-secret-key",
    "change-me-to-a-real-secret",
    "replace-with-a-long-random-token",
    "<paste-generated-token-here>",
    "paste-generated-token-here",
    "<your-generated-secret>",
    "your-generated-secret",
    "staging-change-me-to-real-key",
}
MOSS_GENERIC_MODEL_IDS = {"moss", "moss-nano", "moss-tts-nano"}
MOSS_CPU_MODEL_IDS = {"moss-cpu", "moss-nano-cpu", "moss-tts-nano-cpu"}
MOSS_CUDA_MODEL_IDS = {"moss-cuda", "moss-gpu", "moss-nano-cuda", "moss-tts-nano-cuda"}


def _normalize_config_model_id(model_id: str, moss_provider: str) -> str:
    raw = str(model_id or "").strip().lower()
    if raw in MOSS_GENERIC_MODEL_IDS:
        return "moss-nano-cuda" if moss_provider == "cuda" else "moss-nano-cpu"
    if raw in MOSS_CPU_MODEL_IDS:
        return "moss-nano-cpu"
    if raw in MOSS_CUDA_MODEL_IDS:
        return "moss-nano-cuda"
    return raw


class IntEnvSpec(NamedTuple):
    attr: str
    min_value: int | None = None
    max_value: int | None = None


class FloatEnvSpec(NamedTuple):
    attr: str
    min_value: float | None = None
    max_value: float | None = None


def _find_models_dir() -> Path:
    candidates = [
        Path(os.environ.get("KOKORO_MODEL_DIR", "")),
        Path.cwd() / "models",
        Path(__file__).resolve().parent.parent.parent / "models",
        Path("/app/models"),
    ]
    for p in candidates:
        if p and p.exists() and (p / MODEL_FILENAME).exists():
            logger.info(f"找到模型目录: {p}")
            return p

    fallback = Path.cwd() / "models"
    logger.warning(f"未找到模型目录，使用兜底路径: {fallback}")
    return fallback


def _get_env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"忽略无效整数环境变量 {name}={value!r}")
        return default


def _get_env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(f"忽略无效浮点环境变量 {name}={value!r}")
        return default


def _get_env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _clamp(value, min_value=None, max_value=None):
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


@dataclass
class TTSConfig:
    """运行时配置。"""
    model_dir: Path = field(default_factory=_find_models_dir)
    device: str = "auto"

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    max_concurrent_requests: int = 1

    sample_rate: int = 24000
    max_text_length: int = 10000
    segment_length: int = 100
    default_speed: float = 1.0
    default_voice: str = "zm_010"

    cors_origins: list = field(default_factory=lambda: ["http://localhost:8000"])
    api_key: Optional[str] = None

    stream_enabled: bool = True
    stream_format: str = "pcm_s16le"
    stream_binary_enabled: bool = True
    stream_chunk_seconds: float = 0.50

    cache_enabled: bool = True
    cache_max_items: int = 128
    queue_status_enabled: bool = True
    metrics_enabled: bool = True
    request_timeout_seconds: float = 300.0

    batch_enabled: bool = True
    batch_max_items: int = 20
    batch_concurrency: int = 1
    admin_enabled: bool = False
    voice_upload_enabled: bool = False
    voice_upload_max_bytes: int = 10 * 1024 * 1024
    mp3_enabled: bool = False
    mp3_bitrate: str = "192k"

    enabled_models: list[str] = field(default_factory=lambda: ["kokoro"])
    default_model: str = "kokoro"
    model_switch_enabled: bool = True
    model_unload_on_switch: bool = True
    model_switch_timeout_seconds: float = 300.0
    save_outputs: bool = False
    output_dir: Path = field(default_factory=lambda: Path("/app/outputs"))
    output_max_files: int = 1000

    moss_model_dir: Optional[Path] = None
    moss_repo_path: Optional[Path] = None
    moss_execution_provider: str = "cpu"
    moss_cpu_threads: int = 4
    moss_default_voice: str = "Junhao"
    moss_prompt_audio_path: Optional[Path] = None
    moss_prompt_upload_max_bytes: int = 20 * 1024 * 1024
    moss_prompt_audio_max_seconds: float = 10.0
    moss_prompt_cache_max_items: int = 8
    moss_max_new_frames: int = 375
    moss_voice_clone_max_text_tokens: int = 75
    moss_sample_mode: str = "fixed"
    moss_seed: int = 1234
    moss_cuda_enabled: bool = True
    moss_cuda_memory_limit_mb: int = 0
    moss_enable_wetext_processing: bool = False
    moss_enable_normalize_tts_text: bool = True
    moss_apply_angevoice_rules: bool = True
    moss_realtime_streaming_decode: bool = True
    moss_stream_chunk_seconds: float = 0.42
    moss_stream_queue_max_items: int = 8
    moss_cuda_self_test_enabled: bool = True
    moss_auto_fallback_cpu: bool = True
    moss_quality_gate_enabled: bool = True
    moss_max_clip_ratio: float = 0.02
    moss_output_peak_normalize_enabled: bool = True
    moss_output_target_peak: float = 0.78
    moss_output_gain: float = 0.90
    moss_process_isolation_enabled: bool = False
    moss_output_declick_enabled: bool = True
    moss_output_edge_fade_ms: float = 2.0
    moss_process_isolation_providers: str = "cuda"
    moss_process_kill_grace_seconds: float = 2.0

    # 限流：按客户端令牌桶 + 全局并发闸门；0 表示关闭。
    rate_limit_qps: float = 0.0
    rate_limit_burst: int = 5
    max_queue_length: int = 0

    # MOSS 流式解码预算阈值：按已输出音频领先实时播放的秒数决定解码帧数。
    moss_stream_budget_threshold_low: float = 0.25
    moss_stream_budget_threshold_mid: float = 0.65
    moss_stream_budget_threshold_high: float = 1.20
    moss_stream_chunk_min_floor: float = 0.10

    # 空闲释放：默认 10 分钟无人使用后释放所有已加载模型。
    model_idle_timeout_seconds: float = 600
    model_idle_check_interval: float = 30
    model_idle_unload_current: bool = True

    @property
    def model_path(self) -> str:
        return str(self.model_dir)

    @property
    def model_file(self) -> Path:
        return self.model_dir / MODEL_FILENAME

    @property
    def voices_dir(self) -> Path:
        return self.model_dir / "voices"

    def get_voices(self) -> list[str]:
        if self.voices_dir.exists():
            return sorted([f.stem for f in self.voices_dir.glob("*.pt")])
        return []

    def validate_security(self) -> None:
        """启动前拒绝不安全的后台/鉴权组合。"""
        api_key = (self.api_key or "").strip()
        normalized_key = api_key.lower()
        if api_key and normalized_key in PLACEHOLDER_API_KEYS:
            raise ValueError("KOKORO_API_KEY is still a placeholder; set a real secret or leave it empty")
        admin_password = (os.environ.get("ANGEVOICE_ADMIN_PASSWORD") or "").strip()
        if self.admin_enabled and not admin_password:
            raise ValueError("KOKORO_ADMIN_ENABLED=true requires ANGEVOICE_ADMIN_PASSWORD")
        if self.voice_upload_enabled and not self.admin_enabled:
            raise ValueError("KOKORO_VOICE_UPLOAD_ENABLED=true requires KOKORO_ADMIN_ENABLED=true")
        if not self.enabled_models:
            raise ValueError("ANGEVOICE_ENABLED_MODELS cannot be empty")
        self.enabled_models = [str(item).strip().lower() for item in self.enabled_models if str(item).strip()]
        self.moss_execution_provider = str(self.moss_execution_provider or "cpu").strip().lower()
        if self.moss_execution_provider not in {"cpu", "cuda"}:
            raise ValueError("MOSS_EXECUTION_PROVIDER must be cpu or cuda")
        filtered_models: list[str] = []
        for item in self.enabled_models:
            provider = "cpu" if not self.moss_cuda_enabled and item in MOSS_GENERIC_MODEL_IDS else self.moss_execution_provider
            normalized_item = _normalize_config_model_id(item, provider)
            if not self.moss_cuda_enabled and normalized_item == "moss-nano-cuda":
                logger.warning("Ignoring %s because MOSS_CUDA_ENABLED=false", item)
                continue
            if normalized_item not in filtered_models:
                filtered_models.append(normalized_item)
        self.enabled_models = filtered_models or ["kokoro"]
        if not self.moss_cuda_enabled:
            if self.moss_execution_provider == "cuda":
                logger.warning("MOSS_EXECUTION_PROVIDER=cuda ignored because MOSS_CUDA_ENABLED=false")
                self.moss_execution_provider = "cpu"
        default_provider = (
            "cpu"
            if not self.moss_cuda_enabled and str(self.default_model or "").strip().lower() in MOSS_GENERIC_MODEL_IDS
            else self.moss_execution_provider
        )
        self.default_model = _normalize_config_model_id(self.default_model or self.enabled_models[0], default_provider)
        if not self.moss_cuda_enabled and self.default_model == "moss-nano-cuda":
            replacement = "moss-nano-cpu" if "moss-nano-cpu" in self.enabled_models else self.enabled_models[0]
            logger.warning("Default model %s is disabled; using %s", self.default_model, replacement)
            self.default_model = replacement
        if self.default_model not in self.enabled_models:
            logger.warning("Default model %s is not enabled; using %s", self.default_model, self.enabled_models[0])
            self.default_model = self.enabled_models[0]
        self.moss_sample_mode = str(self.moss_sample_mode or "fixed").strip().lower()
        if self.moss_sample_mode not in {"greedy", "fixed", "full"}:
            raise ValueError("MOSS_SAMPLE_MODE must be greedy, fixed, or full")

    def resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                mem = getattr(props, "total_memory", getattr(props, "total_mem", 0)) / 1e9
                logger.info(f"检测到 GPU: {name} ({mem:.1f}GB)")
                return "cuda"
        except ImportError:
            pass
        logger.info("使用 CPU 推理")
        return "cpu"


def _apply_env(config: TTSConfig) -> None:
    str_env: dict[str, str] = {
        "KOKORO_HOST": "host",
        "KOKORO_DEVICE": "device",
        "KOKORO_DEFAULT_VOICE": "default_voice",
        "KOKORO_STREAM_FORMAT": "stream_format",
        "KOKORO_MP3_BITRATE": "mp3_bitrate",
        "ANGEVOICE_DEFAULT_MODEL": "default_model",
        "ANGEVOICE_OUTPUT_DIR": "output_dir",
        "MOSS_EXECUTION_PROVIDER": "moss_execution_provider",
        "MOSS_DEFAULT_VOICE": "moss_default_voice",
        "MOSS_SAMPLE_MODE": "moss_sample_mode",
        "MOSS_PROCESS_ISOLATION_PROVIDERS": "moss_process_isolation_providers",
    }
    int_env: dict[str, IntEnvSpec] = {
        "KOKORO_PORT": IntEnvSpec("port", 1),
        "KOKORO_WORKERS": IntEnvSpec("workers", 1),
        "KOKORO_MAX_CONCURRENT_REQUESTS": IntEnvSpec("max_concurrent_requests", 1),
        "KOKORO_MAX_TEXT_LENGTH": IntEnvSpec("max_text_length", 1),
        "KOKORO_SEGMENT_LENGTH": IntEnvSpec("segment_length", 20),
        "KOKORO_CACHE_MAX_ITEMS": IntEnvSpec("cache_max_items", 0),
        "KOKORO_BATCH_MAX_ITEMS": IntEnvSpec("batch_max_items", 1),
        "KOKORO_BATCH_CONCURRENCY": IntEnvSpec("batch_concurrency", 1),
        "KOKORO_VOICE_UPLOAD_MAX_BYTES": IntEnvSpec("voice_upload_max_bytes", 1),
        "ANGEVOICE_OUTPUT_MAX_FILES": IntEnvSpec("output_max_files", 0),
        "MOSS_CPU_THREADS": IntEnvSpec("moss_cpu_threads", 1),
        "MOSS_PROMPT_UPLOAD_MAX_BYTES": IntEnvSpec("moss_prompt_upload_max_bytes", 1),
        "MOSS_PROMPT_CACHE_MAX_ITEMS": IntEnvSpec("moss_prompt_cache_max_items", 0),
        "MOSS_MAX_NEW_FRAMES": IntEnvSpec("moss_max_new_frames", 1),
        "MOSS_VOICE_CLONE_MAX_TEXT_TOKENS": IntEnvSpec("moss_voice_clone_max_text_tokens", 1),
        "MOSS_SEED": IntEnvSpec("moss_seed", -1),
        "MOSS_CUDA_MEMORY_LIMIT_MB": IntEnvSpec("moss_cuda_memory_limit_mb", 0),
        "MOSS_STREAM_QUEUE_MAX_ITEMS": IntEnvSpec("moss_stream_queue_max_items", 1, 64),
        "KOKORO_RATE_LIMIT_BURST": IntEnvSpec("rate_limit_burst", 0),
        "KOKORO_MAX_QUEUE_LENGTH": IntEnvSpec("max_queue_length", 0),
    }
    float_env: dict[str, FloatEnvSpec] = {
        "KOKORO_DEFAULT_SPEED": FloatEnvSpec("default_speed"),
        "KOKORO_REQUEST_TIMEOUT_SECONDS": FloatEnvSpec("request_timeout_seconds", 1.0),
        "KOKORO_STREAM_CHUNK_SECONDS": FloatEnvSpec("stream_chunk_seconds", 0.05, 2.0),
        "ANGEVOICE_MODEL_SWITCH_TIMEOUT_SECONDS": FloatEnvSpec("model_switch_timeout_seconds", 1.0),
        "MOSS_PROMPT_AUDIO_MAX_SECONDS": FloatEnvSpec("moss_prompt_audio_max_seconds", 0.0),
        "MOSS_STREAM_CHUNK_SECONDS": FloatEnvSpec("moss_stream_chunk_seconds", 0.05, 2.0),
        "MOSS_MAX_CLIP_RATIO": FloatEnvSpec("moss_max_clip_ratio", 0.0, 1.0),
        "MOSS_OUTPUT_TARGET_PEAK": FloatEnvSpec("moss_output_target_peak", 0.1, 1.0),
        "MOSS_OUTPUT_GAIN": FloatEnvSpec("moss_output_gain", 0.1, 2.0),
        "KOKORO_RATE_LIMIT_QPS": FloatEnvSpec("rate_limit_qps", 0.0),
        "MOSS_STREAM_BUDGET_THRESHOLD_LOW": FloatEnvSpec("moss_stream_budget_threshold_low", 0.0),
        "MOSS_STREAM_BUDGET_THRESHOLD_MID": FloatEnvSpec("moss_stream_budget_threshold_mid", 0.0),
        "MOSS_STREAM_BUDGET_THRESHOLD_HIGH": FloatEnvSpec("moss_stream_budget_threshold_high", 0.0),
        "MOSS_STREAM_CHUNK_MIN_FLOOR": FloatEnvSpec("moss_stream_chunk_min_floor", 0.01),
        "MOSS_PROCESS_KILL_GRACE_SECONDS": FloatEnvSpec("moss_process_kill_grace_seconds", 0.1, 30.0),
        "MOSS_OUTPUT_EDGE_FADE_MS": FloatEnvSpec("moss_output_edge_fade_ms", 0.0, 20.0),
        "ANGEVOICE_IDLE_TIMEOUT_SECONDS": FloatEnvSpec("model_idle_timeout_seconds", 0.0),
        "ANGEVOICE_IDLE_CHECK_INTERVAL": FloatEnvSpec("model_idle_check_interval", 5.0),
    }
    bool_env: dict[str, str] = {
        "KOKORO_STREAM_BINARY_ENABLED": "stream_binary_enabled",
        "KOKORO_CACHE_ENABLED": "cache_enabled",
        "KOKORO_QUEUE_STATUS_ENABLED": "queue_status_enabled",
        "KOKORO_METRICS_ENABLED": "metrics_enabled",
        "KOKORO_BATCH_ENABLED": "batch_enabled",
        "KOKORO_ADMIN_ENABLED": "admin_enabled",
        "KOKORO_VOICE_UPLOAD_ENABLED": "voice_upload_enabled",
        "KOKORO_MP3_ENABLED": "mp3_enabled",
        "ANGEVOICE_MODEL_SWITCH_ENABLED": "model_switch_enabled",
        "ANGEVOICE_MODEL_UNLOAD_ON_SWITCH": "model_unload_on_switch",
        "ANGEVOICE_SAVE_OUTPUTS": "save_outputs",
        "ANGEVOICE_IDLE_UNLOAD_CURRENT": "model_idle_unload_current",
        "MOSS_CUDA_ENABLED": "moss_cuda_enabled",
        "MOSS_ENABLE_WETEXT_PROCESSING": "moss_enable_wetext_processing",
        "MOSS_ENABLE_NORMALIZE_TTS_TEXT": "moss_enable_normalize_tts_text",
        "MOSS_APPLY_ANGEVOICE_RULES": "moss_apply_angevoice_rules",
        "MOSS_REALTIME_STREAMING_DECODE": "moss_realtime_streaming_decode",
        "MOSS_CUDA_SELF_TEST_ENABLED": "moss_cuda_self_test_enabled",
        "MOSS_AUTO_FALLBACK_CPU": "moss_auto_fallback_cpu",
        "MOSS_QUALITY_GATE_ENABLED": "moss_quality_gate_enabled",
        "MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED": "moss_output_peak_normalize_enabled",
        "MOSS_PROCESS_ISOLATION_ENABLED": "moss_process_isolation_enabled",
        "MOSS_OUTPUT_DECLICK_ENABLED": "moss_output_declick_enabled",
    }

    for env_name, attr in str_env.items():
        if os.environ.get(env_name) is not None:
            setattr(config, attr, os.environ[env_name])
    if isinstance(config.output_dir, str):
        config.output_dir = Path(config.output_dir).expanduser()

    for env_name, spec in int_env.items():
        if os.environ.get(env_name) is not None:
            value = _get_env_int(env_name, getattr(config, spec.attr))
            setattr(config, spec.attr, _clamp(value, spec.min_value, spec.max_value))

    for env_name, spec in float_env.items():
        if os.environ.get(env_name) is not None:
            value = _get_env_float(env_name, getattr(config, spec.attr))
            setattr(config, spec.attr, _clamp(value, spec.min_value, spec.max_value))

    for env_name, attr in bool_env.items():
        if os.environ.get(env_name) is not None:
            setattr(config, attr, _get_env_bool(env_name, getattr(config, attr)))

    if os.environ.get("KOKORO_API_KEY"):
        config.api_key = os.environ["KOKORO_API_KEY"]
    if os.environ.get("KOKORO_CORS_ORIGINS"):
        config.cors_origins = [o.strip() for o in os.environ["KOKORO_CORS_ORIGINS"].split(",") if o.strip()]
    if os.environ.get("ANGEVOICE_ENABLED_MODELS"):
        config.enabled_models = [item.strip().lower() for item in os.environ["ANGEVOICE_ENABLED_MODELS"].split(",") if item.strip()]
    if os.environ.get("MOSS_MODEL_DIR"):
        config.moss_model_dir = Path(os.environ["MOSS_MODEL_DIR"]).expanduser()
    if os.environ.get("MOSS_TTS_NANO_PATH"):
        config.moss_repo_path = Path(os.environ["MOSS_TTS_NANO_PATH"]).expanduser()
    if os.environ.get("MOSS_PROMPT_AUDIO_PATH"):
        config.moss_prompt_audio_path = Path(os.environ["MOSS_PROMPT_AUDIO_PATH"]).expanduser()


def load_config(model_dir: Optional[str] = None, device: Optional[str] = None, host: Optional[str] = None, port: Optional[int] = None, **kwargs) -> TTSConfig:
    """加载运行时配置，并应用环境变量和函数参数覆盖。"""
    config = TTSConfig()
    _apply_env(config)
    if model_dir:
        config.model_dir = Path(model_dir)
    if device:
        config.device = device
    if host:
        config.host = host
    if port:
        config.port = port
    for k, v in kwargs.items():
        if v is not None and hasattr(config, k):
            setattr(config, k, v)
    if isinstance(config.output_dir, str):
        config.output_dir = Path(config.output_dir).expanduser()
    config.validate_security()
    return config
