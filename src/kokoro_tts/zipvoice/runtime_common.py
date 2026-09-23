"""ZipVoice 共用的路径解析、纯参数规则与临时输出清理。

模型加载、设备参数、推理和可变状态仍由各 runtime 自己管理。"""

from contextlib import contextmanager
from pathlib import Path
import tempfile
import os


def upstream_path(cfg) -> Path:
    """按显式配置、环境变量、内置目录的优先级确定上游路径。"""
    configured = getattr(cfg, "zipvoice_repo_path", None) or os.environ.get("ZIPVOICE_REPO_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[3] / "vendor" / "ZipVoice"


def prepare_reference(cfg, *, prompt_audio_path, prompt_text, num_steps, remove_long_sil):
    """校验参考输入并解析本次请求的采样参数覆盖。"""
    if not prompt_audio_path or not Path(prompt_audio_path).is_file():
        raise ValueError("ZipVoice 需要可读取的参考音频")
    if not str(prompt_text or "").strip():
        raise ValueError("ZipVoice 需要参考音频对应文本 prompt_text")
    steps = min(32, max(1, int(num_steps or getattr(cfg, "zipvoice_num_steps", 8))))
    remove_sil = bool(getattr(cfg, "zipvoice_remove_long_sil", False) if remove_long_sil is None else remove_long_sil)
    return str(prompt_text).strip(), steps, remove_sil


def generation_settings(cfg, *, speed):
    """提取共用数值设置，设备专属参数留在具体运行时。"""
    return {
        "guidance_scale": float(getattr(cfg, "zipvoice_guidance_scale", 3.0)),
        "speed": float(speed),
        "t_shift": float(getattr(cfg, "zipvoice_t_shift", 0.5)),
        "target_rms": float(getattr(cfg, "zipvoice_target_rms", 0.1)),
        "feat_scale": float(getattr(cfg, "zipvoice_feat_scale", 0.1)),
    }


def generation_metrics(metrics, *, elapsed, steps):
    """生成指标快照；最近一次结果的更新时间由具体运行时决定。"""
    return {
        "last_generation_seconds": round(float(elapsed), 4),
        "last_audio_seconds": round(float(metrics.get("wav_seconds", 0.0)), 4),
        "last_rtf": round(float(metrics.get("rtf", elapsed / max(float(metrics.get("wav_seconds", 1.0)), 0.001))), 4),
        "zipvoice_num_steps": steps,
    }


@contextmanager
def temporary_output(*, prefix):
    """推理前关闭文件句柄，退出时清理临时输出。"""
    with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".wav", delete=False) as temp:
        output_path = Path(temp.name)
    try:
        yield output_path
    finally:
        try:
            output_path.unlink()
        except OSError:
            pass
