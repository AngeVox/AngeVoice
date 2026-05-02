"""Kokoro TTS 配置管理

支持三种配置方式（优先级从高到低）：
1. 环境变量 KOKORO_*
2. 配置文件 config.yaml
3. 默认值
"""

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 模型文件名
MODEL_FILENAME = "kokoro-v1_1-zh.pth"


def _find_models_dir() -> Path:
    """按优先级查找 models 目录"""
    candidates = [
        # 1. 环境变量
        Path(os.environ.get("KOKORO_MODEL_DIR", "")),
        # 2. 项目根目录下的 models/
        Path.cwd() / "models",
        # 3. 包所在目录向上查找
        Path(__file__).resolve().parent.parent.parent / "models",
        # 4. Docker 容器路径
        Path("/app/models"),
    ]
    for p in candidates:
        if p and p.exists() and (p / MODEL_FILENAME).exists():
            logger.info(f"找到模型目录: {p}")
            return p

    # 兜底：当前目录
    fallback = Path.cwd() / "models"
    logger.warning(f"未找到模型目录，使用兜底路径: {fallback}")
    return fallback


@dataclass
class TTSConfig:
    """TTS 配置"""
    # 模型
    model_dir: Path = field(default_factory=_find_models_dir)
    device: str = "auto"  # auto, cpu, cuda

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

    # 合成参数
    sample_rate: int = 24000
    max_text_length: int = 10000
    segment_length: int = 100
    default_speed: float = 1.0
    default_voice: str = "zm_010"

    # 安全
    cors_origins: list = field(default_factory=lambda: ["*"])
    api_key: Optional[str] = None

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
        """获取可用音色列表"""
        if self.voices_dir.exists():
            return sorted([f.stem for f in self.voices_dir.glob("*.pt")])
        return []

    def resolve_device(self) -> str:
        """解析实际设备"""
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


def load_config(
    model_dir: Optional[str] = None,
    device: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    **kwargs,
) -> TTSConfig:
    """加载配置，参数覆盖环境变量和默认值"""
    config = TTSConfig()

    # 环境变量覆盖默认值
    if os.environ.get("KOKORO_HOST"):
        config.host = os.environ["KOKORO_HOST"]
    if os.environ.get("KOKORO_PORT"):
        config.port = int(os.environ["KOKORO_PORT"])
    if os.environ.get("KOKORO_DEVICE"):
        config.device = os.environ["KOKORO_DEVICE"]
    if os.environ.get("KOKORO_API_KEY"):
        config.api_key = os.environ["KOKORO_API_KEY"]

    # 函数参数覆盖一切
    if model_dir:
        config.model_dir = Path(model_dir)
    if device:
        config.device = device
    if host:
        config.host = host
    if port:
        config.port = port
    for k, v in kwargs.items():
        if hasattr(config, k):
            setattr(config, k, v)

    return config
