"""MOSS 官方 runtime 加载、自检和质量分析。"""

from __future__ import annotations

import inspect
import os
import sys
import tempfile
from pathlib import Path
from threading import Lock

import numpy as np

from ..audio import normalize_audio_array
from ..model_sources import ensure_moss_audio_tokenizer_dir, ensure_moss_model_dir


def ensure_import_path(repo_path) -> None:
    """把本地 OpenMOSS 仓库加入导入路径。"""

    if not repo_path:
        return
    resolved = str(Path(repo_path).expanduser().resolve())
    if resolved not in sys.path:
        sys.path.insert(0, resolved)


def create_runtime(*, config, provider: str, provider_patch_lock: Lock, logger):
    """创建官方 ONNX runtime，并在需要时注入 CUDA 显存上限。"""

    try:
        from onnx_tts_runtime import OnnxTtsRuntime
    except ModuleNotFoundError as exc:
        missing = exc.name or "unknown"
        if missing != "onnx_tts_runtime":
            raise RuntimeError(
                f"MOSS-TTS-Nano runtime dependency is missing: {missing}. "
                "Use an AngeVoice MOSS-enabled image or install the official MOSS runtime dependencies."
            ) from exc
        raise RuntimeError(
            "MOSS-TTS-Nano runtime is not installed. Install the official OpenMOSS package "
            "or set MOSS_TTS_NANO_PATH to a local clone."
        ) from exc

    model_dir = ensure_moss_model_dir(config, logger=logger)
    tokenizer_dir = ensure_moss_audio_tokenizer_dir(config, logger=logger)
    if tokenizer_dir:
        # 兼容官方 runtime 通过环境变量或 model_dir 同级目录寻找 codec 资产的实现。
        os.environ["MOSS_AUDIO_TOKENIZER_MODEL_DIR"] = str(tokenizer_dir)
        os.environ["MOSS_AUDIO_TOKENIZER_DIR"] = str(tokenizer_dir)

    runtime_kwargs = {
        "model_dir": str(model_dir) if model_dir else None,
        "thread_count": config.moss_cpu_threads,
        "max_new_frames": config.moss_max_new_frames,
        "do_sample": config.moss_sample_mode != "greedy",
        "sample_mode": config.moss_sample_mode,
        "execution_provider": provider,
    }
    try:
        parameters = inspect.signature(OnnxTtsRuntime).parameters
    except (TypeError, ValueError):
        parameters = {}
    if tokenizer_dir:
        # 不同 OpenMOSS runtime 版本对 codec/tokenizer 目录参数命名可能不同；
        # 只在签名明确支持或接收 **kwargs 时传入，避免旧版本 TypeError。
        accepts_var_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
        for candidate_key in (
            "codec_model_dir",
            "codec_dir",
            "audio_tokenizer_dir",
            "audio_tokenizer_model_dir",
            "tokenizer_model_dir",
        ):
            if candidate_key in parameters or accepts_var_kwargs:
                runtime_kwargs[candidate_key] = str(tokenizer_dir)
                break
    if provider != "cuda" or int(config.moss_cuda_memory_limit_mb) <= 0:
        return OnnxTtsRuntime(**runtime_kwargs)

    import ort_cpu_runtime

    original_resolver = ort_cpu_runtime._resolve_ort_providers
    limit_bytes = int(config.moss_cuda_memory_limit_mb) * 1024 * 1024

    def _resolve_limited_ort_providers(execution_provider: str):
        resolved = original_resolver(execution_provider)
        has_cuda = any(
            item == "CUDAExecutionProvider"
            or (isinstance(item, tuple) and item[0] == "CUDAExecutionProvider")
            for item in resolved
        )
        if not has_cuda:
            return resolved
        logger.info("Applying MOSS CUDA memory limit: %d MB", int(config.moss_cuda_memory_limit_mb))
        return [
            (
                "CUDAExecutionProvider",
                {
                    "gpu_mem_limit": limit_bytes,
                    "arena_extend_strategy": "kSameAsRequested",
                    "cudnn_conv_use_max_workspace": 0,
                },
            ),
            "CPUExecutionProvider",
        ]

    with provider_patch_lock:
        try:
            ort_cpu_runtime._resolve_ort_providers = _resolve_limited_ort_providers
            return OnnxTtsRuntime(**runtime_kwargs)
        finally:
            ort_cpu_runtime._resolve_ort_providers = original_resolver


def analyze_waveform(waveform, sample_rate: int, *, max_clip_ratio: float) -> dict:
    """分析自检音频质量，避免空音频、NaN 和严重削波。"""

    audio = normalize_audio_array(waveform)
    if audio.size == 0:
        return {"ok": False, "reason": "empty audio"}
    if not np.isfinite(audio).all():
        return {"ok": False, "reason": "audio contains NaN or Inf"}
    max_abs = float(np.max(np.abs(audio)))
    if max_abs < 1e-4:
        return {"ok": False, "reason": "near-silent audio", "max_abs": max_abs}
    clip_ratio = float(np.mean(np.abs(audio) >= 0.999))
    if clip_ratio > float(max_clip_ratio):
        return {"ok": False, "reason": "audio clipping ratio is too high", "clip_ratio": clip_ratio}
    return {
        "ok": True,
        "sample_rate": int(sample_rate),
        "channels": int(audio.shape[1]) if audio.ndim == 2 else 1,
        "samples": int(audio.shape[0]),
        "max_abs": round(max_abs, 6),
        "clip_ratio": round(clip_ratio, 6),
    }


def temp_output_path() -> str:
    """返回 MOSS runtime 自检使用的临时输出路径。"""

    temp_dir = Path(tempfile.gettempdir()) / "angevoice_moss"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return str(temp_dir / "last_output.wav")
