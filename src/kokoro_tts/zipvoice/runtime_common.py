"""Shared synthesis rules and temporary output ownership for ZipVoice runtimes.

Model loading, device arguments, inference and runtime state stay with callers.
"""

from contextlib import contextmanager
from pathlib import Path
import tempfile


def prepare_reference(cfg, *, prompt_audio_path, prompt_text, num_steps, remove_long_sil):
    """Validate reference inputs and resolve request-local sampling overrides."""
    if not prompt_audio_path or not Path(prompt_audio_path).is_file():
        raise ValueError("ZipVoice 需要可读取的参考音频")
    if not str(prompt_text or "").strip():
        raise ValueError("ZipVoice 需要参考音频对应文本 prompt_text")
    steps = min(32, max(1, int(num_steps or getattr(cfg, "zipvoice_num_steps", 8))))
    remove_sil = bool(getattr(cfg, "zipvoice_remove_long_sil", False) if remove_long_sil is None else remove_long_sil)
    return str(prompt_text).strip(), steps, remove_sil


def generation_settings(cfg, *, speed):
    """Project common numeric settings without CUDA-specific arguments."""
    return {
        "guidance_scale": float(getattr(cfg, "zipvoice_guidance_scale", 3.0)),
        "speed": float(speed),
        "t_shift": float(getattr(cfg, "zipvoice_t_shift", 0.5)),
        "target_rms": float(getattr(cfg, "zipvoice_target_rms", 0.1)),
        "feat_scale": float(getattr(cfg, "zipvoice_feat_scale", 0.1)),
    }


def generation_metrics(metrics, *, elapsed, steps):
    """Return metrics; each runtime owns when to replace its last result."""
    return {
        "last_generation_seconds": round(float(elapsed), 4),
        "last_audio_seconds": round(float(metrics.get("wav_seconds", 0.0)), 4),
        "last_rtf": round(float(metrics.get("rtf", elapsed / max(float(metrics.get("wav_seconds", 1.0)), 0.001))), 4),
        "zipvoice_num_steps": steps,
    }


@contextmanager
def temporary_output(*, prefix):
    """Close the file before inference and remove it on every exit path."""
    with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".wav", delete=False) as temp:
        output_path = Path(temp.name)
    try:
        yield output_path
    finally:
        try:
            output_path.unlink()
        except OSError:
            pass
