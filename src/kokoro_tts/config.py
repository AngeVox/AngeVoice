"""AngeVoice 配置。

配置优先级：
1. 显式函数参数
2. Admin runtime-config.json
3. KOKORO_* / ANGEVOICE_* / MOSS_* 环境变量
4. 代码默认值
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .admin_config_schema import load_runtime_config
from .config_env import apply_env
from .kokoro_assets import (
    default_kokoro_model_dir,
    is_valid_kokoro_model_file,
    is_valid_kokoro_voice_file,
    kokoro_model_dir_candidates,
    kokoro_voice_dir_candidates,
)
from .config_ids import (
    MODEL_FILENAME,
    MOSS_GENERIC_MODEL_IDS,
    PLACEHOLDER_API_KEYS,
    PLACEHOLDER_ADMIN_PASSWORDS,
    normalize_config_model_id,
)

def _find_models_dir() -> Path:
    """查找可用的 Kokoro 模型目录。

    新布局统一把模型放在 ``models/`` 下：
    ``models/models--hexgrad--Kokoro-82M-v1.1-zh`` 用于 Kokoro，
    ``models/MOSS-TTS-Nano-100M-ONNX`` 用于 MOSS。

    这里会跳过 Git LFS 指针文件或不完整权重，避免后续 ``torch.load``
    把文本指针当成模型加载。若没有本地真实权重，返回推荐持久化目录，
    运行时交给 Hugging Face / ModelScope 下载到同一个 ``models`` 根目录。
    """

    for path in kokoro_model_dir_candidates():
        if not path or not path.exists():
            continue
        model_file = path / MODEL_FILENAME
        if is_valid_kokoro_model_file(model_file, log=logger):
            try:
                size_mb = model_file.stat().st_size / (1024 * 1024)
            except OSError:
                size_mb = 0.0
            logger.info("找到模型目录: %s (Kokoro 模型 %.1f MB)", path, size_mb)
            return path
    fallback = default_kokoro_model_dir()
    logger.warning("未找到有效的 Kokoro 本地模型目录，使用推荐持久化路径: %s；运行时将尝试远程下载。", fallback)
    return fallback


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
    segment_length: int = 160
    text_single_newline_policy: str = "auto"
    moss_segment_length: int = 120
    default_speed: float = 1.0
    default_voice: str = "zm_010"
    _voices_cache: list[str] = field(default_factory=list, init=False, repr=False)
    _voices_cache_signature: tuple[tuple[str, int, int], ...] = field(default_factory=tuple, init=False, repr=False)

    cors_origins: list = field(default_factory=lambda: ["http://localhost:8000"])
    api_key: Optional[str] = None
    api_key_file: Path = field(default_factory=lambda: Path("/app/outputs/.angevoice-api-key"))
    api_key_auto_generated: bool = False

    stream_enabled: bool = True
    stream_format: str = "pcm_s16le"
    stream_binary_enabled: bool = True
    stream_chunk_seconds: float = 0.55
    stream_prebuffer_seconds: float = 0.25

    cache_enabled: bool = True
    cache_max_items: int = 64
    cache_max_bytes: int = 512 * 1024 * 1024
    cache_skip_text_over_chars: int = 1200
    cache_skip_audio_over_bytes: int = 20 * 1024 * 1024
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
    runtime_config_file: Path = field(default_factory=lambda: Path("/app/outputs/runtime-config.json"))

    # 模型源站：auto 先短超时探测 HF/ModelScope 可达性，再做国家/地区判断。
    model_source: str = "auto"
    model_source_detect_url: str = "https://ipapi.co/country/"
    model_source_detect_timeout_seconds: float = 1.5
    model_source_probe_timeout_seconds: float = 1.5
    model_source_probe_hf_url: str = "https://huggingface.co"
    model_source_probe_modelscope_url: str = "https://www.modelscope.cn"
    model_source_effective: str = "auto"
    model_source_country: str = ""
    model_source_hf_reachable: bool | None = None
    model_source_modelscope_reachable: bool | None = None
    kokoro_hf_repo: str = "hexgrad/Kokoro-82M-v1.1-zh"
    kokoro_modelscope_repo: str = "AI-ModelScope/Kokoro-82M-v1.1-zh"
    moss_modelscope_repo: str = "openmoss/MOSS-TTS-Nano-100M-ONNX"
    moss_hf_repo: str = ""

    moss_model_dir: Optional[Path] = None
    moss_repo_path: Optional[Path] = None
    moss_execution_provider: str = "cpu"
    moss_cpu_threads: int = 4
    moss_default_voice: str = "Junhao"
    moss_prompt_audio_path: Optional[Path] = None
    moss_prompt_upload_max_bytes: int = 20 * 1024 * 1024
    tts_request_max_bytes: int = 2 * 1024 * 1024
    moss_prompt_audio_max_seconds: float = 8.0
    moss_prompt_cache_max_items: int = 8
    moss_max_new_frames: int = 320
    moss_voice_clone_max_text_tokens: int = 56
    moss_sample_mode: str = "fixed"
    moss_seed: int = 1234
    moss_cuda_enabled: bool = True
    moss_cuda_memory_limit_mb: int = 0
    moss_enable_wetext_processing: bool = False
    moss_enable_normalize_tts_text: bool = True
    moss_apply_angevoice_rules: str | bool = "auto"
    moss_mixed_english_policy: str = "translate"
    moss_realtime_streaming_decode: bool = True
    moss_stream_chunk_seconds: float = 0.40
    moss_stream_queue_max_items: int = 8
    moss_stream_prebuffer_seconds: float = 0.75
    moss_cuda_self_test_enabled: bool = True
    moss_auto_fallback_cpu: bool = True
    moss_quality_gate_enabled: bool = True
    moss_max_clip_ratio: float = 0.02
    moss_output_peak_normalize_enabled: bool = True
    moss_output_target_peak: float = 0.86
    moss_output_gain: float = 0.94
    moss_process_isolation_enabled: bool = False
    moss_output_declick_enabled: bool = True
    moss_output_edge_fade_ms: float = 1.5
    moss_audio_polish_enabled: bool = True
    moss_trim_silence_enabled: bool = True
    moss_trim_silence_db: float = -45.0
    moss_max_silence_ms: float = 480.0
    moss_crossfade_ms: float = 12.0
    moss_segment_pause_ms: float = 80.0
    moss_runtime_pause_max_ms: float = 350.0
    moss_vram_guard_enabled: bool = True
    moss_vram_safe_free_mb: int = 1200
    moss_vram_critical_free_mb: int = 600
    moss_low_vram_segment_length: int = 96
    moss_low_vram_max_new_frames: int = 280
    moss_low_vram_text_tokens: int = 48
    moss_disable_full_codec_after_oom: bool = True
    moss_full_codec_oom_cooldown_seconds: float = 600.0
    moss_vram_snapshot_ttl_seconds: float = 10.0
    moss_process_isolation_providers: str = "cuda"
    moss_process_kill_grace_seconds: float = 2.0

    # 限流：按客户端令牌桶 + 全局并发闸门；0 表示关闭。
    rate_limit_qps: float = 0.0
    rate_limit_burst: int = 5
    max_queue_length: int = 0
    trust_proxy_headers: bool = False
    public_status_endpoints: bool = True

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
        """列出 Kokoro 音色名称，兼容本地目录和 Hugging Face 缓存快照。

        上游 ``kokoro`` 包下载音色时会放到 Hugging Face 缓存快照目录，
        例如 ``models--hexgrad--Kokoro-82M-v1.1-zh/snapshots/<sha>/voices``。
        统一模型目录后如果只扫描 ``KOKORO_MODEL_DIR/voices``，前端音色库
        会显示为 0。这里统一扫描新目录、旧目录和缓存快照目录，并过滤
        Git LFS 指针、HTML 错误页等无效 ``.pt`` 文件。
        """

        voice_dirs = kokoro_voice_dir_candidates(self.model_dir)
        signature: list[tuple[str, int, int]] = []
        for voice_dir in voice_dirs:
            if not voice_dir.is_dir():
                continue
            try:
                for f in sorted(voice_dir.glob("*.pt")):
                    try:
                        st = f.stat()
                        signature.append((str(f), int(st.st_mtime_ns), int(st.st_size)))
                    except OSError:
                        signature.append((str(f), -1, -1))
            except OSError:
                continue

        current_signature = tuple(signature)
        if current_signature == self._voices_cache_signature:
            return list(self._voices_cache)

        voices: set[str] = set()
        for voice_dir in voice_dirs:
            if not voice_dir.is_dir():
                continue
            for item in sorted(voice_dir.glob("*.pt")):
                if is_valid_kokoro_voice_file(item, log=logger):
                    voices.add(item.stem)
        self._voices_cache = sorted(voices)
        self._voices_cache_signature = current_signature
        return list(self._voices_cache)

    def validate_security(self) -> None:
        """启动前拒绝不安全的后台/鉴权组合。"""
        api_key = (self.api_key or "").strip()
        normalized_key = api_key.lower()
        if api_key and normalized_key in PLACEHOLDER_API_KEYS:
            raise ValueError("KOKORO_API_KEY is still a placeholder; set a real secret or leave it empty")
        admin_password = (os.environ.get("ANGEVOICE_ADMIN_PASSWORD") or "").strip()
        if self.admin_enabled and not admin_password:
            raise ValueError("KOKORO_ADMIN_ENABLED=true requires ANGEVOICE_ADMIN_PASSWORD")
        if self.admin_enabled and admin_password.lower() in PLACEHOLDER_ADMIN_PASSWORDS:
            raise ValueError("ANGEVOICE_ADMIN_PASSWORD is still a placeholder; set a real strong password")
        if self.voice_upload_enabled and not self.admin_enabled:
            raise ValueError("KOKORO_VOICE_UPLOAD_ENABLED=true requires KOKORO_ADMIN_ENABLED=true")
        if not self.enabled_models:
            raise ValueError("ANGEVOICE_ENABLED_MODELS cannot be empty")
        self.enabled_models = [str(item).strip().lower() for item in self.enabled_models if str(item).strip()]
        self.model_source = str(self.model_source or "auto").strip().lower()
        if self.model_source not in {"auto", "huggingface", "modelscope"}:
            raise ValueError("ANGEVOICE_MODEL_SOURCE must be auto, huggingface, or modelscope")
        self.moss_execution_provider = str(self.moss_execution_provider or "cpu").strip().lower()
        if self.moss_execution_provider not in {"cpu", "cuda"}:
            raise ValueError("MOSS_EXECUTION_PROVIDER must be cpu or cuda")
        filtered_models: list[str] = []
        for item in self.enabled_models:
            provider = "cpu" if not self.moss_cuda_enabled and item in MOSS_GENERIC_MODEL_IDS else self.moss_execution_provider
            normalized_item = normalize_config_model_id(item, provider)
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
        self.default_model = normalize_config_model_id(self.default_model or self.enabled_models[0], default_provider)
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
        rules_mode = str(self.moss_apply_angevoice_rules).strip().lower()
        if rules_mode in {"1", "true", "yes", "on", "y"}:
            self.moss_apply_angevoice_rules = "true"
        elif rules_mode in {"0", "false", "no", "off", "n"}:
            self.moss_apply_angevoice_rules = "false"
        elif rules_mode in {"auto", "smart", "mixed"}:
            self.moss_apply_angevoice_rules = "auto"
        else:
            raise ValueError("MOSS_APPLY_ANGEVOICE_RULES must be auto, true, or false")
        mixed_policy = str(self.moss_mixed_english_policy or "translate").strip().lower()
        if mixed_policy in {"0", "false", "no", "off", "n", "preserve", "keep", "none"}:
            self.moss_mixed_english_policy = "preserve"
        elif mixed_policy in {"spell", "letters"}:
            self.moss_mixed_english_policy = "spell"
        elif mixed_policy in {"auto", "translate", "cn", "zh", "meaning"}:
            self.moss_mixed_english_policy = "translate"
        else:
            raise ValueError("MOSS_MIXED_ENGLISH_POLICY must be translate, preserve, or spell")
        self.text_single_newline_policy = str(self.text_single_newline_policy or "auto").strip().lower()
        if self.text_single_newline_policy not in {"auto", "preserve", "space"}:
            raise ValueError("ANGEVOICE_SINGLE_NEWLINE_POLICY must be auto, preserve, or space")

    def resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                mem = getattr(props, "total_memory", getattr(props, "total_mem", 0)) / 1e9
                logger.info("检测到 GPU: %s (%.1fGB)", name, mem)
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
    """加载运行时配置，并应用环境变量和函数参数覆盖。"""
    config = TTSConfig()
    apply_env(config)
    load_runtime_config(config)
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
    if isinstance(config.api_key_file, str):
        config.api_key_file = Path(config.api_key_file).expanduser()
    if isinstance(config.runtime_config_file, str):
        config.runtime_config_file = Path(config.runtime_config_file).expanduser()
    config.validate_security()
    return config
