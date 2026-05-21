"""Model source selection and optional ModelScope prefetch helpers."""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from .kokoro_assets import default_kokoro_model_dir, default_moss_model_dir, has_valid_kokoro_local_assets

logger = logging.getLogger(__name__)

_CHINA_COUNTRY_CODES = {"CN"}



_MOSS_VALID_MODEL_SUFFIXES = {".onnx", ".ort", ".bin", ".safetensors"}
_MOSS_VALID_METADATA_SUFFIXES = {".json", ".yaml", ".yml", ".txt"}


def _is_probably_lfs_pointer(path: Path) -> bool:
    try:
        head = path.read_bytes()[:256]
    except OSError:
        return False
    return head.startswith(b"version https://git-lfs.github.com/spec/v1")


def has_valid_moss_model_assets(path: Path, *, log: logging.Logger | None = None) -> bool:
    """判断 MOSS 模型目录是否至少包含一个可信的真实模型文件。

    MOSS 模型目录允许包含 README、配置和缓存文件，但不能只有 Git LFS 指针、
    空文件或很小的占位文件。这里优先寻找较大的 ONNX/ORT/bin/safetensors
    文件；如果目录里只有文本类元数据，则认为还未下载完整模型。
    """

    path = Path(path).expanduser()
    if not path.exists() or not path.is_dir():
        return False

    saw_file = False
    saw_lfs_pointer = False
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part.startswith(".") for part in file_path.relative_to(path).parts):
            continue
        saw_file = True
        suffix = file_path.suffix.lower()
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size <= 0:
            continue
        if _is_probably_lfs_pointer(file_path):
            saw_lfs_pointer = True
            continue
        if suffix in _MOSS_VALID_MODEL_SUFFIXES and size >= 1024 * 1024:
            return True
        if suffix in _MOSS_VALID_METADATA_SUFFIXES:
            continue
        if size >= 5 * 1024 * 1024:
            return True

    if log and saw_file:
        if saw_lfs_pointer:
            log.warning("MOSS 模型目录 %s 似乎只有 Git LFS 指针或不完整文件，将继续尝试下载/补全。", path)
        else:
            log.warning("MOSS 模型目录 %s 未发现有效模型文件，将继续尝试下载/补全。", path)
    return False


def _detect_country(config) -> str:
    cached = str(getattr(config, "model_source_country", "") or "").strip().upper()
    if cached:
        return cached
    env_country = os.environ.get("ANGEVOICE_MODEL_SOURCE_COUNTRY") or os.environ.get("MODEL_SOURCE_COUNTRY")
    if env_country:
        country = env_country.strip().upper()
        config.model_source_country = country
        return country
    url = str(getattr(config, "model_source_detect_url", "") or "").strip()
    if not url:
        return ""
    timeout = float(getattr(config, "model_source_detect_timeout_seconds", 1.5) or 1.5)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            country = resp.read(16).decode("utf-8", errors="ignore").strip().upper()
    except Exception:
        logger.debug("Model source country detection failed", exc_info=True)
        country = ""
    config.model_source_country = country
    return country


def _probe_url(url: str, timeout: float) -> bool:
    """Return whether a model host is reachable within a short timeout."""
    if not url:
        return False
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "AngeVoice/model-source-probe"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            return 200 <= int(getattr(resp, "status", 200)) < 500
    except urllib.error.HTTPError as exc:
        # 401/403/404 仍说明主机可达；5xx 视为不可靠。
        return 400 <= int(exc.code) < 500
    except Exception:
        logger.debug("Model source probe failed: %s", url, exc_info=True)
        return False


def _probe_reachability(config) -> tuple[bool, bool]:
    timeout = float(getattr(config, "model_source_probe_timeout_seconds", 1.5) or 1.5)
    hf_url = str(getattr(config, "model_source_probe_hf_url", "https://huggingface.co") or "")
    ms_url = str(getattr(config, "model_source_probe_modelscope_url", "https://www.modelscope.cn") or "")
    hf_ok = _probe_url(hf_url, timeout)
    ms_ok = _probe_url(ms_url, timeout)
    config.model_source_hf_reachable = hf_ok
    config.model_source_modelscope_reachable = ms_ok
    return hf_ok, ms_ok


def resolve_model_source(config) -> str:
    """Resolve effective model source.

    Explicit ``ANGEVOICE_MODEL_SOURCE=huggingface/modelscope`` always wins.
    In auto mode we first test real reachability so domestic deployments do not
    accidentally fall back to Hugging Face just because ipapi.co is slow/blocked.
    Country detection is only used when reachability is ambiguous.
    """
    mode = str(getattr(config, "model_source", "auto") or "auto").strip().lower()
    if mode in {"huggingface", "modelscope"}:
        config.model_source_effective = mode
        return mode

    cached = str(getattr(config, "model_source_effective", "") or "").strip().lower()
    if cached in {"huggingface", "modelscope"}:
        logger.debug("Using cached model source: %s", cached)
        return cached

    hf_ok, ms_ok = _probe_reachability(config)
    if ms_ok and not hf_ok:
        source = "modelscope"
    elif hf_ok and not ms_ok:
        source = "huggingface"
    else:
        country = _detect_country(config)
        if country in _CHINA_COUNTRY_CODES:
            source = "modelscope"
        elif hf_ok:
            source = "huggingface"
        elif ms_ok:
            source = "modelscope"
        else:
            # 最后兜底：Hugging Face 仍是上游默认源，但只在可达性
            # 和地区判断都失败后使用。
            source = "huggingface"
    config.model_source_effective = source
    logger.info(
        "Model source resolved: mode=%s effective=%s hf_ok=%s modelscope_ok=%s country=%s",
        mode,
        source,
        getattr(config, "model_source_hf_reachable", None),
        getattr(config, "model_source_modelscope_reachable", None),
        getattr(config, "model_source_country", ""),
    )
    return source


def _modelscope_snapshot_download(repo_id: str, target_dir: Path, *, logger: logging.Logger) -> Path | None:
    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except Exception:
        logger.warning(
            "ModelScope package is not installed, so ModelScope downloads cannot be used for %s. "
            "Run `pip install modelscope>=1.20.0` or use the official Docker image; falling back to Hugging Face.",
            repo_id,
        )
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading model from ModelScope: %s -> %s", repo_id, target_dir)
    path = snapshot_download(repo_id, local_dir=str(target_dir))
    return Path(path)


def ensure_kokoro_model_dir(config, *, logger: logging.Logger) -> Path | None:
    """确保 Kokoro 本地模型目录可用。

    只在 ModelScope 模式下主动预取。若本地目录只有 Git LFS 指针或损坏文件，
    不会误判为可用；Hugging Face 模式则交给上游 ``kokoro`` 包按 repo_id 下载。
    ModelScope 下载目标也统一放进 ``models/models--hexgrad--Kokoro-82M-v1.1-zh``。
    """

    current_dir = Path(config.model_dir)
    if has_valid_kokoro_local_assets(current_dir, log=logger):
        return current_dir
    target_dir = default_kokoro_model_dir()
    if has_valid_kokoro_local_assets(target_dir, log=logger):
        config.model_dir = target_dir
        return target_dir
    if resolve_model_source(config) != "modelscope":
        config.model_dir = target_dir
        return None
    repo = str(getattr(config, "kokoro_modelscope_repo", "") or "").strip()
    if not repo:
        config.model_dir = target_dir
        return None
    path = _modelscope_snapshot_download(repo, target_dir, logger=logger)
    if has_valid_kokoro_local_assets(target_dir, log=logger):
        config.model_dir = target_dir
        return target_dir
    if path and has_valid_kokoro_local_assets(Path(path), log=logger):
        config.model_dir = Path(path)
        return Path(path)
    logger.warning("ModelScope 下载后仍未找到有效 Kokoro 权重，将回退到上游 repo_id 下载路径。")
    config.model_dir = target_dir
    return None


def ensure_moss_model_dir(config, *, logger: logging.Logger) -> Path | None:
    target = Path(getattr(config, "moss_model_dir", None) or default_moss_model_dir()).expanduser()
    if has_valid_moss_model_assets(target, log=logger):
        config.moss_model_dir = target
        return target
    if resolve_model_source(config) != "modelscope":
        config.moss_model_dir = target
        return target
    repo = str(getattr(config, "moss_modelscope_repo", "") or "").strip()
    if not repo:
        config.moss_model_dir = target
        return target
    path = _modelscope_snapshot_download(repo, target, logger=logger)
    candidate = Path(path).expanduser() if path else target
    if has_valid_moss_model_assets(candidate, log=logger):
        config.moss_model_dir = candidate
    else:
        logger.warning("ModelScope 下载后仍未找到有效 MOSS 模型文件，将保留统一模型目录等待 runtime 补全。")
        config.moss_model_dir = target
    return config.moss_model_dir
