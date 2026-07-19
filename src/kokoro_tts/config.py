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
from .model_source_metadata import MODEL_SOURCE_METADATA

def _find_models_dir() -> Path:
    """查找可用的 Kokoro 模型目录。

    新布局统一把模型放在 ``models/`` 下：
    ``models/models--hexgrad--Kokoro-82M-v1.1-zh`` 用于 Kokoro，
    ``models/MOSS-TTS-Nano-100M-ONNX`` 用于 MOSS。

    这里会跳过 Git LFS 指针文件或不完整权重，避免后续 ``torch.load``
    把文本指针当成模型加载。若没有本地真实权重，返回推荐持久化目录，
    运行时交给 Hugging Face / ModelScope 下载到同一个 ``models`` 根目录。
    """

    env_model_dir = os.environ.get("KOKORO_MODEL_DIR")
    env_models_root = os.environ.get("ANGEVOICE_MODELS_ROOT")
    if env_model_dir:
        candidates = [Path(env_model_dir).expanduser()]
    elif env_models_root:
        candidates = [default_kokoro_model_dir(Path(env_models_root).expanduser())]
    else:
        candidates = kokoro_model_dir_candidates()

    for path in candidates:
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
    fallback = candidates[0] if candidates else default_kokoro_model_dir()
    logger.warning("未找到有效的 Kokoro 本地模型目录，使用推荐持久化路径: %s；运行时将尝试远程下载。", fallback)
    return fallback


@dataclass
class TTSConfig:
    """运行时配置。"""
    model_dir: Path = field(default_factory=_find_models_dir)
    device: str = "auto"
    deployment_profile: str = "source"

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    access_log_enabled: bool = False
    max_concurrent_requests: int = 1

    sample_rate: int = 24000
    max_text_length: int = 10000
    segment_length: int = 160
    text_single_newline_policy: str = "auto"
    angevoice_tn_engine: str = "wetext"
    moss_segment_length: int = 120
    default_speed: float = 1.0
    default_voice: str = "zm_010"
    kokoro_prefetch_voices: bool = True
    _voices_cache: list[str] = field(default_factory=list, init=False, repr=False)
    _voices_cache_signature: tuple[tuple[str, int, int], ...] = field(default_factory=tuple, init=False, repr=False)

    cors_origins: list = field(default_factory=lambda: ["http://localhost:8000"])
    api_key: Optional[str] = None
    credentials_dir: Path = field(default_factory=lambda: Path("/app/credentials"))
    api_key_file: Path = field(default_factory=lambda: Path("/app/credentials/.angevoice-api-key"))
    admin_credentials_file: Path = field(default_factory=lambda: Path("/app/credentials/admin-credentials.json"))
    api_key_auto_generated: bool = False

    stream_enabled: bool = True
    stream_format: str = "pcm_s16le"
    stream_binary_enabled: bool = True
    stream_chunk_seconds: float = 0.55
    stream_prebuffer_seconds: float = 0.25
    # WebSocket 资源保护。0 最大连接数显式禁用连接上限。
    websocket_max_connections: int = 16
    # 支持 base64 解码后最多 20 MiB 参考音频上传加 JSON 开销。
    websocket_max_message_bytes: int = 32 * 1024 * 1024

    cache_enabled: bool = True
    cache_max_items: int = 64
    cache_max_bytes: int = 512 * 1024 * 1024
    cache_skip_text_over_chars: int = 1200
    cache_skip_audio_over_bytes: int = 20 * 1024 * 1024
    queue_status_enabled: bool = True
    metrics_enabled: bool = True
    request_timeout_seconds: float = 300.0
    # 流式合成允许更长的无音频帧等待窗口。MOSS 长文本在首帧或分段之间
    # 可能需要数秒到数十秒，不能直接复用普通 HTTP 请求超时。
    websocket_stream_idle_timeout_seconds: float = 120.0

    batch_enabled: bool = True
    batch_max_items: int = 20
    batch_concurrency: int = 1
    admin_enabled: bool = False
    voice_upload_enabled: bool = False
    voice_upload_max_bytes: int = 10 * 1024 * 1024
    # 旧 mp3 开关保留兼容；新转码能力统一由 FFmpeg 开关控制。
    mp3_enabled: bool = False
    mp3_bitrate: str = "192k"
    ffmpeg_enabled: bool = False
    ffmpeg_binary: str = "ffmpeg"
    ffmpeg_timeout_seconds: float = 30.0
    audio_opus_bitrate: str = "32k"
    audio_aac_bitrate: str = "96k"

    enabled_models: list[str] = field(default_factory=lambda: ["kokoro"])
    default_model: str = "kokoro"
    # Studio 默认选择与可选冷启动预加载独立。
    startup_preload_enabled: bool = False
    startup_preload_model: str = "kokoro"
    model_switch_enabled: bool = True
    model_unload_on_switch: bool = True
    model_switch_timeout_seconds: float = 300.0
    save_outputs: bool = False
    output_dir: Path = field(default_factory=lambda: Path("/app/outputs"))
    output_max_files: int = 1000
    runtime_config_file: Path = field(default_factory=lambda: Path("/app/config/runtime-config.json"))
    update_check_enabled: bool = True
    update_repository: str = "angevox/AngeVoice"
    update_check_timeout_seconds: float = 3.0
    update_check_cache_seconds: float = 21600.0

    # 模型源站：auto 先短超时探测 HF/ModelScope 可达性，再做国家/地区判断。
    model_source: str = MODEL_SOURCE_METADATA.default
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
    moss_audio_tokenizer_modelscope_repo: str = "openmoss/MOSS-Audio-Tokenizer-Nano-ONNX"
    moss_audio_tokenizer_hf_repo: str = "openmoss/MOSS-Audio-Tokenizer-Nano-ONNX"

    moss_model_dir: Optional[Path] = None
    moss_audio_tokenizer_model_dir: Optional[Path] = None
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
    # 库默认值保持嵌入兼容性；正式部署模板启用隔离。
    kokoro_process_isolation_enabled: bool = False
    zipvoice_process_isolation_enabled: bool = False
    engine_process_kill_grace_seconds: float = 2.0
    engine_process_stream_drain_seconds: float = 30.0
    # 子进程流式输出的无帧等待窗口。用于区分“模型正在跑慢帧”
    # 与“worker 真正卡死”，避免 MOSS 长文本被过早判定超时。
    engine_process_stream_idle_timeout_seconds: float = 120.0
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

    # ZipVoice：CPU 为冻结基线；标准 GPU profile 请求 CUDA provider 并可自动回退 CPU。
    zipvoice_model_root: Path = field(default_factory=lambda: Path("/app/models/zipvoice"))
    zipvoice_distill_dir: Path = field(default_factory=lambda: Path("/app/models/zipvoice/zipvoice_distill"))
    zipvoice_vocos_dir: Path = field(default_factory=lambda: Path("/app/models/zipvoice/vocos-mel-24khz"))
    zipvoice_profiles_dir: Path = field(default_factory=lambda: Path("/app/prompts/zipvoice"))
    zipvoice_repo_path: Optional[Path] = None
    zipvoice_download_enabled: bool = True
    zipvoice_execution_provider: str = "cpu"
    zipvoice_cuda_enabled: bool = False
    zipvoice_auto_fallback_cpu: bool = True
    zipvoice_cuda_device_index: int = 0
    zipvoice_cuda_max_duration: float = 36.0
    zipvoice_cpu_threads: int = 4
    zipvoice_num_steps: int = 8
    zipvoice_guidance_scale: float = 3.0
    zipvoice_t_shift: float = 0.5
    zipvoice_target_rms: float = 0.1
    zipvoice_feat_scale: float = 0.1
    zipvoice_remove_long_sil: bool = False
    zipvoice_prompt_upload_max_bytes: int = 20 * 1024 * 1024
    zipvoice_prompt_audio_max_seconds: float = 15.0

    # 限流：默认提供基础入口保护；可信内网可显式配置为 0 关闭。
    rate_limit_qps: float = 10.0
    rate_limit_burst: int = 20
    max_queue_length: int = 50
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
    # 卸载后彻底清理：默认关闭。开启后只在模型因空闲卸载成功后，
    # 且服务已经完全空闲时退出当前进程，交给 Docker/服务管理器拉起。
    restart_after_idle_unload_enabled: bool = False
    restart_after_idle_unload_delay_seconds: float = 3.0
    restart_after_idle_unload_cooldown_seconds: float = 1800.0
    restart_after_idle_unload_exit_code: int = 75

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
        """启动前归一化运行时配置，并拒绝不安全的组合。"""
        self._validate_auth_and_admin_security()
        self._validate_feature_dependencies()
        self._normalize_model_source()
        self._normalize_execution_providers()
        self._normalize_enabled_models()
        self._normalize_default_model()
        self._normalize_moss_text_options()
        self._normalize_text_policy()
        self._normalize_audio_transcoding()

    def _validate_auth_and_admin_security(self) -> None:
        api_key = (self.api_key or "").strip()
        normalized_key = api_key.lower()
        if api_key and normalized_key in PLACEHOLDER_API_KEYS:
            raise ValueError("KOKORO_API_KEY is still a placeholder; set a real secret or leave it empty")
        from .config_api_key import effective_api_key

        externally_bound = str(self.host or "").strip().lower() not in {"127.0.0.1", "localhost", "::1"}
        if externally_bound and not effective_api_key(self):
            logger.warning(
                "服务绑定到 %s 但未启用 API 鉴权；"
                "在可信网络外暴露前，请设置 KOKORO_API_KEY=auto 或强密钥",
                self.host,
            )
        admin_username = (
            os.environ.get("ANGEVOICE_ADMIN_USERNAME")
            or os.environ.get("KOKORO_ADMIN_USERNAME")
            or "admin"
        ).strip()
        admin_password = (
            os.environ.get("ANGEVOICE_ADMIN_PASSWORD")
            or os.environ.get("KOKORO_ADMIN_PASSWORD")
            or "admin123"
        ).strip()
        credentials_file = Path(getattr(self, "admin_credentials_file", "/app/credentials/admin-credentials.json")).expanduser()
        persisted_admin = credentials_file.is_file()
        first_entry_default = admin_username == "admin" and admin_password == "admin123"
        if self.admin_enabled and not persisted_admin and first_entry_default:
            logger.warning("管理后台当前使用首次默认凭据 admin/admin123；公网暴露前必须在安全页修改密码")
        if (
            self.admin_enabled
            and not persisted_admin
            and admin_password.lower() in PLACEHOLDER_ADMIN_PASSWORDS
            and not first_entry_default
        ):
            raise ValueError("ANGEVOICE_ADMIN_PASSWORD is still a placeholder; use the documented first-entry default or set a strong password")

    def _validate_feature_dependencies(self) -> None:
        if self.voice_upload_enabled and not self.admin_enabled:
            raise ValueError("KOKORO_VOICE_UPLOAD_ENABLED=true requires KOKORO_ADMIN_ENABLED=true")
        if not self.enabled_models:
            raise ValueError("ANGEVOICE_ENABLED_MODELS cannot be empty")

    def _normalize_model_source(self) -> None:
        self.model_source = str(
            self.model_source or MODEL_SOURCE_METADATA.default
        ).strip().lower()
        if self.model_source not in MODEL_SOURCE_METADATA.accepted_values:
            raise ValueError("ANGEVOICE_MODEL_SOURCE must be auto, huggingface, modelscope, or offline")

    def _normalize_execution_providers(self) -> None:
        self.moss_execution_provider = str(self.moss_execution_provider or "cpu").strip().lower()
        if self.moss_execution_provider not in {"cpu", "cuda"}:
            raise ValueError("MOSS_EXECUTION_PROVIDER must be cpu or cuda")
        self.zipvoice_execution_provider = str(self.zipvoice_execution_provider or "cpu").strip().lower()
        if self.zipvoice_execution_provider not in {"cpu", "cuda"}:
            raise ValueError("ZIPVOICE_EXECUTION_PROVIDER must be cpu or cuda")
        if self.zipvoice_execution_provider == "cuda" and not self.zipvoice_cuda_enabled:
            logger.warning("ZIPVOICE_EXECUTION_PROVIDER=cuda ignored because ZIPVOICE_CUDA_ENABLED=false")
            self.zipvoice_execution_provider = "cpu"
        if not self.moss_cuda_enabled and self.moss_execution_provider == "cuda":
            logger.warning("MOSS_EXECUTION_PROVIDER=cuda ignored because MOSS_CUDA_ENABLED=false")
            self.moss_execution_provider = "cpu"

    def _normalize_enabled_models(self) -> None:
        normalized_models = [str(item).strip().lower() for item in self.enabled_models if str(item).strip()]
        filtered_models: list[str] = []
        for item in normalized_models:
            provider = "cpu" if not self.moss_cuda_enabled and item in MOSS_GENERIC_MODEL_IDS else self.moss_execution_provider
            normalized_item = normalize_config_model_id(item, provider)
            if not self.moss_cuda_enabled and normalized_item == "moss-nano-cuda":
                logger.warning("Ignoring %s because MOSS_CUDA_ENABLED=false", item)
                continue
            if normalized_item not in filtered_models:
                filtered_models.append(normalized_item)
        self.enabled_models = filtered_models or ["kokoro"]

    def _normalize_default_model(self) -> None:
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

    def _normalize_moss_text_options(self) -> None:
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

    def _normalize_text_policy(self) -> None:
        self.text_single_newline_policy = str(self.text_single_newline_policy or "auto").strip().lower()
        if self.text_single_newline_policy not in {"auto", "preserve", "space"}:
            raise ValueError("ANGEVOICE_SINGLE_NEWLINE_POLICY must be auto, preserve, or space")
        self.angevoice_tn_engine = str(self.angevoice_tn_engine or "wetext").strip().lower()
        if self.angevoice_tn_engine in {"0", "false", "no", "none"}:
            self.angevoice_tn_engine = "off"
        if self.angevoice_tn_engine not in {"wetext", "legacy", "off"}:
            raise ValueError("ANGEVOICE_TN_ENGINE must be wetext, legacy, or off")

    def _normalize_audio_transcoding(self) -> None:
        # 兼容旧部署：KOKORO_MP3_ENABLED=true 继续代表允许 FFmpeg 转码。
        if self.mp3_enabled:
            self.ffmpeg_enabled = True
        self.ffmpeg_binary = str(self.ffmpeg_binary or "ffmpeg").strip() or "ffmpeg"
        self.mp3_bitrate = str(self.mp3_bitrate or "192k").strip().lower()
        self.audio_opus_bitrate = str(self.audio_opus_bitrate or "32k").strip().lower()
        self.audio_aac_bitrate = str(self.audio_aac_bitrate or "96k").strip().lower()
        try:
            self.ffmpeg_timeout_seconds = max(1.0, float(self.ffmpeg_timeout_seconds))
        except (TypeError, ValueError):
            self.ffmpeg_timeout_seconds = 30.0

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
    if isinstance(config.credentials_dir, str):
        config.credentials_dir = Path(config.credentials_dir).expanduser()
    if isinstance(config.api_key_file, str):
        config.api_key_file = Path(config.api_key_file).expanduser()
    if isinstance(config.admin_credentials_file, str):
        config.admin_credentials_file = Path(config.admin_credentials_file).expanduser()
    if isinstance(config.runtime_config_file, str):
        config.runtime_config_file = Path(config.runtime_config_file).expanduser()
    if isinstance(config.model_dir, str):
        config.model_dir = Path(config.model_dir).expanduser()
    if isinstance(config.moss_model_dir, str):
        config.moss_model_dir = Path(config.moss_model_dir).expanduser()
    if isinstance(config.moss_audio_tokenizer_model_dir, str):
        config.moss_audio_tokenizer_model_dir = Path(config.moss_audio_tokenizer_model_dir).expanduser()
    if isinstance(config.moss_repo_path, str):
        config.moss_repo_path = Path(config.moss_repo_path).expanduser()
    if isinstance(config.moss_prompt_audio_path, str):
        config.moss_prompt_audio_path = Path(config.moss_prompt_audio_path).expanduser()
    config.validate_security()
    return config
