"""Model source selection and optional ModelScope prefetch helpers."""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from .kokoro_assets import has_valid_kokoro_local_assets

logger = logging.getLogger(__name__)

_CHINA_COUNTRY_CODES = {"CN"}


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
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - deployment helper, URL is configurable
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
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 - fixed/configurable public model host probe
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
            # 兜底：Hugging Face 仍为上游默认源，但仅在可达性和地区检查均失败后使用。
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
    不会误判为可用；Hugging Face 模式则交给上游 `kokoro` 包按 repo_id 下载。
    """

    if has_valid_kokoro_local_assets(Path(config.model_dir), log=logger):
        return Path(config.model_dir)
    if resolve_model_source(config) != "modelscope":
        return None
    repo = str(getattr(config, "kokoro_modelscope_repo", "") or "").strip()
    if not repo:
        return None
    path = _modelscope_snapshot_download(repo, Path(config.model_dir), logger=logger)
    if has_valid_kokoro_local_assets(Path(config.model_dir), log=logger):
        return Path(config.model_dir)
    if path and has_valid_kokoro_local_assets(Path(path), log=logger):
        return Path(path)
    logger.warning("ModelScope 下载后仍未找到有效 Kokoro 权重，将回退到上游 repo_id 下载路径。")
    return None


def ensure_moss_model_dir(config, *, logger: logging.Logger) -> Path | None:
    if getattr(config, "moss_model_dir", None):
        return Path(config.moss_model_dir).expanduser()
    if resolve_model_source(config) != "modelscope":
        return None
    repo = str(getattr(config, "moss_modelscope_repo", "") or "").strip()
    if not repo:
        return None
    base = Path(os.environ.get("MODELSCOPE_CACHE", Path.home() / ".cache" / "modelscope"))
    target = base / "hub" / repo.replace("/", "_")
    path = _modelscope_snapshot_download(repo, target, logger=logger)
    if path:
        config.moss_model_dir = path
    return path
