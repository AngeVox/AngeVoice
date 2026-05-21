"""模型源选择与可选 ModelScope 预取工具。"""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from .kokoro_assets import default_kokoro_model_dir, default_moss_model_dir, has_valid_kokoro_local_assets

logger = logging.getLogger(__name__)

_CHINA_COUNTRY_CODES = {"CN"}



_MOSS_VALID_MODEL_SUFFIXES = {".onnx", ".ort", ".bin", ".safetensors", ".data"}
_MOSS_BROWSER_MANIFEST = "browser_poc_manifest.json"
_MOSS_BROWSER_DIR_NAMES = ("", "MOSS-TTS-Nano-100M-ONNX", "MOSS-TTS-Nano-ONNX-CPU")


def _is_probably_lfs_pointer(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(256)
    except OSError:
        return False
    return head.startswith(b"version https://git-lfs.github.com/spec/v1")


def _moss_browser_asset_dirs(path: Path) -> list[Path]:
    """返回官方 runtime 会尝试读取 browser_onnx 资产的目录。"""

    root = Path(path).expanduser()
    dirs: list[Path] = []
    for name in _MOSS_BROWSER_DIR_NAMES:
        candidate = root / name if name else root
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


def _has_runtime_manifest(path: Path) -> bool:
    """判断目录是否包含官方 MOSS runtime 必需的 manifest。"""

    return (Path(path) / _MOSS_BROWSER_MANIFEST).is_file()


def _has_real_moss_asset(path: Path) -> bool:
    """判断目录下是否有官方 runtime 可用的真实 MOSS 资产。

    ModelScope 仓库里的大权重主要是 ``*.data``，而部分 ``*.onnx``
    只是几十 KB 的图结构文件。旧逻辑只接受大于 1MB 的 ONNX/ORT/BIN，
    会把已经下载完成的官方模型误判为无效。
    """

    root = Path(path)
    if not root.exists() or not root.is_dir():
        return False
    total_bytes = 0
    has_manifest = _has_runtime_manifest(root)
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part.startswith(".") for part in file_path.relative_to(root).parts):
            continue
        if file_path.suffix.lower() not in _MOSS_VALID_MODEL_SUFFIXES:
            continue
        if _is_probably_lfs_pointer(file_path):
            continue
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size <= 0:
            continue
        total_bytes += size
        if file_path.suffix.lower() == ".data" and size >= 1024 * 1024:
            return True
    return has_manifest and total_bytes >= 1024 * 1024


def resolve_valid_moss_model_dir(path: Path, *, log: logging.Logger | None = None) -> Path | None:
    """解析可直接交给官方 runtime 的 MOSS 模型目录。"""

    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        return None
    for candidate in _moss_browser_asset_dirs(root):
        if _has_runtime_manifest(candidate) and _has_real_moss_asset(candidate):
            return candidate
    if log and any(root.rglob("*")):
        lfs_files = [item for item in root.rglob("*") if item.is_file() and _is_probably_lfs_pointer(item)]
        if lfs_files:
            log.warning("MOSS 模型目录 %s 似乎只有 Git LFS 指针或不完整文件，将继续尝试下载/补全。", root)
        else:
            log.warning(
                "MOSS 模型目录 %s 缺少 %s 或真实 ONNX 权重，将继续尝试下载/补全。",
                root,
                _MOSS_BROWSER_MANIFEST,
            )
    return None


def has_valid_moss_model_assets(path: Path, *, log: logging.Logger | None = None) -> bool:
    """判断 MOSS 模型目录是否能被官方 runtime 直接加载。"""

    return resolve_valid_moss_model_dir(path, log=log) is not None

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
    """判断模型源主机是否能在短超时时间内连通。"""
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
    """解析实际使用的模型源。

    显式设置 ``ANGEVOICE_MODEL_SOURCE=huggingface/modelscope`` 时直接优先。
    auto 模式会先探测 Hugging Face 和 ModelScope 的真实可达性，避免国内
    部署仅因地区探测接口缓慢或不可用而误选源站。地区判断只作为兜底依据。
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


def _huggingface_snapshot_download(repo_id: str, target_dir: Path, *, logger: logging.Logger) -> Path | None:
    try:
        from huggingface_hub import snapshot_download
    except Exception:
        logger.warning(
            "huggingface_hub 不可用，无法从 Hugging Face 下载 MOSS 模型：%s",
            repo_id,
        )
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    logger.info("从 Hugging Face 下载 MOSS 模型：%s -> %s", repo_id, target_dir)
    try:
        path = snapshot_download(
            repo_id=repo_id,
            local_dir=str(target_dir),
            local_dir_use_symlinks=False,
        )
    except Exception:
        logger.warning("Hugging Face MOSS 模型下载失败：%s", repo_id, exc_info=True)
        return None
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


def _moss_download_plan(config) -> list[tuple[str, str]]:
    """返回 MOSS 模型下载顺序。"""

    source = resolve_model_source(config)
    hf_repo = str(getattr(config, "moss_hf_repo", "") or "").strip()
    ms_repo = str(getattr(config, "moss_modelscope_repo", "") or "").strip()
    plan: list[tuple[str, str]] = []

    def add(kind: str, repo: str) -> None:
        if repo and (kind, repo) not in plan:
            plan.append((kind, repo))

    if source == "modelscope":
        add("modelscope", ms_repo)
        add("huggingface", hf_repo)
    elif source == "huggingface":
        add("huggingface", hf_repo)
        # MOSS ONNX 默认仓库主要通过 ModelScope 配置，HF 未配置或失败时仍需兜底。
        add("modelscope", ms_repo)
    else:
        add("modelscope", ms_repo)
        add("huggingface", hf_repo)
    return plan


def _download_moss_model_assets(config, target: Path, *, logger: logging.Logger) -> Path | None:
    """按可用源下载 MOSS ONNX 资产。"""

    for source, repo in _moss_download_plan(config):
        if source == "modelscope":
            path = _modelscope_snapshot_download(repo, target, logger=logger)
        else:
            path = _huggingface_snapshot_download(repo, target, logger=logger)
        candidates = [target]
        if path:
            candidates.insert(0, Path(path).expanduser())
        for candidate in candidates:
            if has_valid_moss_model_assets(candidate, log=logger):
                return candidate
        logger.warning("从 %s 下载后仍未发现有效 MOSS 模型资产：%s", source, repo)
    return None


def ensure_moss_model_dir(config, *, logger: logging.Logger) -> Path | None:
    """确保 MOSS ONNX 模型目录可用。

    统一模型目录迁移后，目录可能已经存在但只有 README、Git LFS 指针
    或空占位文件。此时必须继续自动下载，而不能把空目录交给官方
    runtime，否则会在切换 MOSS 时抛出 browser_poc_manifest.json 缺失错误。
    """

    target = Path(getattr(config, "moss_model_dir", None) or default_moss_model_dir()).expanduser()
    resolved = resolve_valid_moss_model_dir(target, log=logger)
    if resolved:
        config.moss_model_dir = resolved
        return resolved

    downloaded = _download_moss_model_assets(config, target, logger=logger)
    if downloaded:
        resolved = resolve_valid_moss_model_dir(downloaded, log=logger) or resolve_valid_moss_model_dir(target, log=logger)
        if resolved:
            config.moss_model_dir = resolved
            return resolved

    config.moss_model_dir = target
    logger.warning(
        "未找到有效的 MOSS ONNX 模型资产，已尝试自动下载但仍不可用。"
        "请检查网络，或手动把 browser_poc_manifest.json 及 ONNX 资产放入：%s",
        target,
    )
    return target
