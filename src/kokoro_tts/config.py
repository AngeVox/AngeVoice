"""AngeVoice configuration.

Configuration priority:
1. Explicit function parameters
2. KOKORO_* environment variables
3. Defaults
"""

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_FILENAME = "kokoro-v1_1-zh.pth"


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


def _get_env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class TTSConfig:
    """Runtime configuration."""
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

    def resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                mem = torch.cuda.get_device_properties(0).total_mem / 1e9
                logger.info(f"检测到 GPU: {name} ({mem:.1f}GB)")
                return "cuda"
        except ImportError:
            pass
        logger.info("使用 CPU 推理")
        return "cpu"


def _apply_env(config: TTSConfig) -> None:
    simple_str = {
        "KOKORO_HOST": "host",
        "KOKORO_DEVICE": "device",
        "KOKORO_DEFAULT_VOICE": "default_voice",
        "KOKORO_STREAM_FORMAT": "stream_format",
        "KOKORO_MP3_BITRATE": "mp3_bitrate",
    }
    simple_int = {
        "KOKORO_PORT": ("port", 1, None),
        "KOKORO_WORKERS": ("workers", 1, None),
        "KOKORO_MAX_CONCURRENT_REQUESTS": ("max_concurrent_requests", 1, None),
        "KOKORO_MAX_TEXT_LENGTH": ("max_text_length", 1, None),
        "KOKORO_SEGMENT_LENGTH": ("segment_length", 20, None),
        "KOKORO_CACHE_MAX_ITEMS": ("cache_max_items", 0, None),
        "KOKORO_BATCH_MAX_ITEMS": ("batch_max_items", 1, None),
        "KOKORO_BATCH_CONCURRENCY": ("batch_concurrency", 1, None),
        "KOKORO_VOICE_UPLOAD_MAX_BYTES": ("voice_upload_max_bytes", 1, None),
    }
    simple_float = {
        "KOKORO_DEFAULT_SPEED": ("default_speed", None),
        "KOKORO_REQUEST_TIMEOUT_SECONDS": ("request_timeout_seconds", 1.0),
    }
    simple_bool = {
        "KOKORO_STREAM_BINARY_ENABLED": "stream_binary_enabled",
        "KOKORO_CACHE_ENABLED": "cache_enabled",
        "KOKORO_QUEUE_STATUS_ENABLED": "queue_status_enabled",
        "KOKORO_METRICS_ENABLED": "metrics_enabled",
        "KOKORO_BATCH_ENABLED": "batch_enabled",
        "KOKORO_ADMIN_ENABLED": "admin_enabled",
        "KOKORO_VOICE_UPLOAD_ENABLED": "voice_upload_enabled",
        "KOKORO_MP3_ENABLED": "mp3_enabled",
    }

    for env_name, attr in simple_str.items():
        if os.environ.get(env_name) is not None:
            setattr(config, attr, os.environ[env_name])

    for env_name, (attr, min_value, _max_value) in simple_int.items():
        if os.environ.get(env_name) is not None:
            value = _get_env_int(env_name, getattr(config, attr))
            if min_value is not None:
                value = max(min_value, value)
            setattr(config, attr, value)

    for env_name, (attr, min_value) in simple_float.items():
        if os.environ.get(env_name) is not None:
            value = _get_env_float(env_name, getattr(config, attr))
            if min_value is not None:
                value = max(min_value, value)
            setattr(config, attr, value)

    for env_name, attr in simple_bool.items():
        if os.environ.get(env_name) is not None:
            setattr(config, attr, _get_env_bool(env_name, getattr(config, attr)))

    if os.environ.get("KOKORO_API_KEY"):
        config.api_key = os.environ["KOKORO_API_KEY"]
    if os.environ.get("KOKORO_CORS_ORIGINS"):
        config.cors_origins = [o.strip() for o in os.environ["KOKORO_CORS_ORIGINS"].split(",") if o.strip()]


def load_config(
    model_dir: Optional[str] = None,
    device: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    **kwargs,
) -> TTSConfig:
    """Load runtime config with environment and argument overrides."""
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

    return config
