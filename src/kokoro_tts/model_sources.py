"""模型源选择与可选 ModelScope / Hugging Face 预取工具。"""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from .kokoro_assets import (
    KOKORO_MODEL_FILENAME,
    default_kokoro_model_dir,
    default_moss_audio_tokenizer_dir,
    default_moss_model_dir,
    has_valid_kokoro_local_assets,
    is_valid_kokoro_voice_file,
    kokoro_voice_dir_candidates,
)

logger = logging.getLogger(__name__)

_CHINA_COUNTRY_CODES = {"CN"}

_MOSS_VALID_MODEL_SUFFIXES = {".onnx", ".ort", ".bin", ".safetensors", ".data"}
_MOSS_BROWSER_MANIFEST = "browser_poc_manifest.json"
_MOSS_BROWSER_DIR_NAMES = ("", "MOSS-TTS-Nano-100M-ONNX", "MOSS-TTS-Nano-ONNX-CPU")
_MOSS_TOKENIZER_META = "codec_browser_onnx_meta.json"
_MOSS_TOKENIZER_DIR_NAMES = ("", "MOSS-Audio-Tokenizer-Nano-ONNX")
_KOKORO_MIN_PREFETCHED_VOICES = 2
_KOKORO_HF_ALLOW_PATTERNS = ("config.json", KOKORO_MODEL_FILENAME, "voices/*.pt")


def _is_probably_lfs_pointer(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(256)
    except OSError:
        return False
    return head.startswith(b"version https://git-lfs.github.com/spec/v1")


def _asset_candidate_dirs(path: Path, names: tuple[str, ...]) -> list[Path]:
    root = Path(path).expanduser()
    dirs: list[Path] = []
    for name in names:
        candidate = root / name if name else root
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


def _moss_browser_asset_dirs(path: Path) -> list[Path]:
    """返回官方 runtime 会尝试读取 browser_onnx 资产的目录。"""

    return _asset_candidate_dirs(path, _MOSS_BROWSER_DIR_NAMES)


def _moss_audio_tokenizer_asset_dirs(path: Path) -> list[Path]:
    """返回 MOSS codec/audio-tokenizer 资产目录候选。"""

    return _asset_candidate_dirs(path, _MOSS_TOKENIZER_DIR_NAMES)


def _has_runtime_manifest(path: Path) -> bool:
    """判断目录是否包含官方 MOSS runtime 必需的 manifest。"""

    return (Path(path) / _MOSS_BROWSER_MANIFEST).is_file()


def _has_tokenizer_meta(path: Path) -> bool:
    """判断目录是否包含 MOSS Audio Tokenizer 必需的 codec meta。"""

    return (Path(path) / _MOSS_TOKENIZER_META).is_file()


def _has_real_onnx_asset(path: Path, *, min_total_bytes: int = 1024 * 1024) -> bool:
    root = Path(path)
    if not root.exists() or not root.is_dir():
        return False
    total_bytes = 0
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
        if file_path.suffix.lower() == ".data" and size >= min_total_bytes:
            return True
    return total_bytes >= min_total_bytes


def _has_real_moss_asset(path: Path) -> bool:
    """判断目录下是否有官方 runtime 可用的真实 MOSS 资产。

    ModelScope 仓库里的大权重主要是 ``*.data``，而部分 ``*.onnx``
    只是几十 KB 的图结构文件。旧逻辑只接受大于 1MB 的 ONNX/ORT/BIN，
    会把已经下载完成的官方模型误判为无效。
    """

    root = Path(path)
    if not root.exists() or not root.is_dir():
        return False
    return _has_runtime_manifest(root) and _has_real_onnx_asset(root)


def _has_real_moss_audio_tokenizer_asset(path: Path) -> bool:
    """判断目录下是否有 MOSS Audio Tokenizer 的真实 ONNX 资产。"""

    root = Path(path)
    if not root.exists() or not root.is_dir():
        return False
    return _has_tokenizer_meta(root) and _has_real_onnx_asset(root)


def resolve_valid_moss_model_dir(path: Path, *, log: logging.Logger | None = None) -> Path | None:
    """解析可直接交给官方 runtime 的 MOSS 模型目录。"""

    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        return None
    for candidate in _moss_browser_asset_dirs(root):
        if _has_real_moss_asset(candidate):
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


def resolve_valid_moss_audio_tokenizer_dir(path: Path, *, log: logging.Logger | None = None) -> Path | None:
    """解析可直接交给官方 runtime 的 MOSS Audio Tokenizer 目录。"""

    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        return None
    for candidate in _moss_audio_tokenizer_asset_dirs(root):
        if _has_real_moss_audio_tokenizer_asset(candidate):
            return candidate
    if log and any(root.rglob("*")):
        lfs_files = [item for item in root.rglob("*") if item.is_file() and _is_probably_lfs_pointer(item)]
        if lfs_files:
            log.warning("MOSS Audio Tokenizer 目录 %s 似乎只有 Git LFS 指针或不完整文件，将继续尝试下载/补全。", root)
        else:
            log.warning(
                "MOSS Audio Tokenizer 目录 %s 缺少 %s 或真实 ONNX 权重，将继续尝试下载/补全。",
                root,
                _MOSS_TOKENIZER_META,
            )
    return None


def has_valid_moss_model_assets(path: Path, *, log: logging.Logger | None = None) -> bool:
    """判断 MOSS 模型目录是否能被官方 runtime 直接加载。"""

    return resolve_valid_moss_model_dir(path, log=log) is not None


def has_valid_moss_audio_tokenizer_assets(path: Path, *, log: logging.Logger | None = None) -> bool:
    """判断 MOSS Audio Tokenizer 目录是否能被官方 runtime 直接加载。"""

    return resolve_valid_moss_audio_tokenizer_dir(path, log=log) is not None


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

    显式设置 ``ANGEVOICE_MODEL_SOURCE=huggingface/modelscope/offline`` 时直接优先。
    auto 模式会先探测 Hugging Face 和 ModelScope 的真实可达性，避免国内
    部署仅因地区探测接口缓慢或不可用而误选源站。地区判断只作为兜底依据。
    """
    mode = str(getattr(config, "model_source", "auto") or "auto").strip().lower()
    if mode in {"huggingface", "modelscope", "offline"}:
        config.model_source_effective = mode
        if mode == "offline":
            logger.info("Model source resolved: offline; automatic model download is disabled")
        return mode

    cached = str(getattr(config, "model_source_effective", "") or "").strip().lower()
    if cached in {"huggingface", "modelscope", "offline"}:
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


def _huggingface_snapshot_download(
    repo_id: str,
    target_dir: Path,
    *,
    logger: logging.Logger,
    allow_patterns: tuple[str, ...] | list[str] | None = None,
) -> Path | None:
    try:
        from huggingface_hub import snapshot_download
    except Exception:
        logger.warning(
            "huggingface_hub 不可用，无法从 Hugging Face 下载模型：%s",
            repo_id,
        )
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    logger.info("从 Hugging Face 下载模型：%s -> %s", repo_id, target_dir)
    try:
        kwargs = {
            "repo_id": repo_id,
            "local_dir": str(target_dir),
            "local_dir_use_symlinks": False,
        }
        if allow_patterns:
            kwargs["allow_patterns"] = list(allow_patterns)
        path = snapshot_download(**kwargs)
    except Exception:
        logger.warning("Hugging Face 模型下载失败：%s", repo_id, exc_info=True)
        return None
    return Path(path)


def _generic_download_plan(config, *, hf_attr: str, ms_attr: str) -> list[tuple[str, str]]:
    source = resolve_model_source(config)
    hf_repo = str(getattr(config, hf_attr, "") or "").strip()
    ms_repo = str(getattr(config, ms_attr, "") or "").strip()
    plan: list[tuple[str, str]] = []

    def add(kind: str, repo: str) -> None:
        if repo and (kind, repo) not in plan:
            plan.append((kind, repo))

    if source == "offline":
        return plan
    if source == "modelscope":
        add("modelscope", ms_repo)
        add("huggingface", hf_repo)
    elif source == "huggingface":
        add("huggingface", hf_repo)
        # 部分模型默认只有 ModelScope 仓库配置，HF 未配置或失败时仍需兜底。
        add("modelscope", ms_repo)
    else:
        add("modelscope", ms_repo)
        add("huggingface", hf_repo)
    return plan


def _kokoro_download_plan(config) -> list[tuple[str, str]]:
    return _generic_download_plan(config, hf_attr="kokoro_hf_repo", ms_attr="kokoro_modelscope_repo")


def _moss_download_plan(config) -> list[tuple[str, str]]:
    """返回 MOSS 模型下载顺序。"""

    return _generic_download_plan(config, hf_attr="moss_hf_repo", ms_attr="moss_modelscope_repo")


def _moss_audio_tokenizer_download_plan(config) -> list[tuple[str, str]]:
    """返回 MOSS Audio Tokenizer 下载顺序。"""

    return _generic_download_plan(
        config,
        hf_attr="moss_audio_tokenizer_hf_repo",
        ms_attr="moss_audio_tokenizer_modelscope_repo",
    )


def _kokoro_voice_count(model_dir: Path) -> int:
    count = 0
    for voice_dir in kokoro_voice_dir_candidates(model_dir):
        if not voice_dir.is_dir():
            continue
        for item in voice_dir.glob("*.pt"):
            if is_valid_kokoro_voice_file(item, log=logger):
                count += 1
    return count


def _download_kokoro_assets(config, target: Path, *, logger: logging.Logger) -> Path | None:
    """按可用源预取 Kokoro 主模型、config 和全部 voices/*.pt。"""

    for source, repo in _kokoro_download_plan(config):
        if source == "modelscope":
            path = _modelscope_snapshot_download(repo, target, logger=logger)
        else:
            path = _huggingface_snapshot_download(
                repo,
                target,
                logger=logger,
                allow_patterns=_KOKORO_HF_ALLOW_PATTERNS,
            )
        candidates = [target]
        if path:
            candidates.insert(0, Path(path).expanduser())
        for candidate in candidates:
            if has_valid_kokoro_local_assets(candidate, log=logger):
                return candidate
        logger.warning("从 %s 下载后仍未发现有效 Kokoro 模型资产：%s", source, repo)
    return None


def ensure_kokoro_model_dir(config, *, logger: logging.Logger) -> Path | None:
    """确保 Kokoro 本地模型目录可用，并尽量预取完整音色库。

    旧逻辑在 Hugging Face 模式下把下载交给 ``kokoro`` 上游包懒加载，
    结果只会在用户第一次选择某个音色时下载该 ``.pt``，前端音色库经常
    只剩 ``zm_010``。这里统一在模型目录中预取 ``config.json``、主权重
    和 ``voices/*.pt``，让 Docker 持久化目录真正自洽。
    """

    current_dir = Path(config.model_dir).expanduser()
    prefetch_voices = bool(getattr(config, "kokoro_prefetch_voices", True))

    def _is_good_enough(path: Path) -> bool:
        if not has_valid_kokoro_local_assets(path, log=logger):
            return False
        if not prefetch_voices:
            return True
        return _kokoro_voice_count(path) >= _KOKORO_MIN_PREFETCHED_VOICES

    if _is_good_enough(current_dir):
        return current_dir

    target_dir = default_kokoro_model_dir()
    if _is_good_enough(target_dir):
        config.model_dir = target_dir
        return target_dir

    if str(getattr(config, "model_source", "auto") or "auto").strip().lower() == "offline":
        logger.warning(
            "ANGEVOICE_MODEL_SOURCE=offline，已禁用 Kokoro 自动下载；请预先把 config.json、权重和 voices/*.pt 放入：%s",
            current_dir,
        )
        config.model_dir = current_dir
        return current_dir if has_valid_kokoro_local_assets(current_dir, log=logger) else None

    # 若模型已有效但音色不足，仍尝试在同一目录补齐 voices/*.pt。
    download_target = current_dir if has_valid_kokoro_local_assets(current_dir, log=logger) else target_dir
    path = _download_kokoro_assets(config, download_target, logger=logger)
    for candidate in [Path(path).expanduser()] if path else []:
        if has_valid_kokoro_local_assets(candidate, log=logger):
            if prefetch_voices and _kokoro_voice_count(candidate) < _KOKORO_MIN_PREFETCHED_VOICES:
                logger.warning(
                    "Kokoro 模型已下载但音色预取不完整 (%d/%d)，"
                    "运行时仍可能按需下载缺失音色。",
                    _kokoro_voice_count(candidate),
                    _KOKORO_MIN_PREFETCHED_VOICES,
                )
            config.model_dir = candidate
            return candidate
    if has_valid_kokoro_local_assets(download_target, log=logger):
        config.model_dir = download_target
        if prefetch_voices and _kokoro_voice_count(download_target) < _KOKORO_MIN_PREFETCHED_VOICES:
            logger.warning("Kokoro 主模型可用，但音色预取不完整；运行时仍可能按需下载缺失音色。")
        return download_target

    logger.warning("下载后仍未找到有效 Kokoro 权重，将回退到上游 repo_id 懒加载路径。")
    config.model_dir = target_dir
    return None


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


def _download_moss_audio_tokenizer_assets(config, target: Path, *, logger: logging.Logger) -> Path | None:
    """按可用源下载 MOSS Audio Tokenizer / codec ONNX 资产。"""

    for source, repo in _moss_audio_tokenizer_download_plan(config):
        if source == "modelscope":
            path = _modelscope_snapshot_download(repo, target, logger=logger)
        else:
            path = _huggingface_snapshot_download(repo, target, logger=logger)
        candidates = [target]
        if path:
            candidates.insert(0, Path(path).expanduser())
        for candidate in candidates:
            if has_valid_moss_audio_tokenizer_assets(candidate, log=logger):
                return candidate
        logger.warning("从 %s 下载后仍未发现有效 MOSS Audio Tokenizer 资产：%s", source, repo)
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

    if str(getattr(config, "model_source", "auto") or "auto").strip().lower() == "offline":
        config.moss_model_dir = target
        logger.warning(
            "ANGEVOICE_MODEL_SOURCE=offline，已禁用 MOSS 自动下载；请预先把 browser_poc_manifest.json 及 ONNX 资产放入：%s",
            target,
        )
        return target

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


def ensure_moss_audio_tokenizer_dir(config, *, logger: logging.Logger) -> Path | None:
    """确保 MOSS Audio Tokenizer / codec ONNX 模型目录可用。

    OpenMOSS 官方 runtime 不只需要 ``MOSS-TTS-Nano-100M-ONNX``，还会读取
    同级 ``MOSS-Audio-Tokenizer-Nano-ONNX/codec_browser_onnx_meta.json``。
    之前只下载 TTS ONNX 仓库，导致切换 MOSS 后在 codec meta 处 500。
    """

    if getattr(config, "moss_audio_tokenizer_model_dir", None):
        target = Path(config.moss_audio_tokenizer_model_dir).expanduser()
    else:
        moss_dir = Path(getattr(config, "moss_model_dir", None) or default_moss_model_dir()).expanduser()
        target = default_moss_audio_tokenizer_dir(moss_dir.parent)

    resolved = resolve_valid_moss_audio_tokenizer_dir(target, log=logger)
    if resolved:
        config.moss_audio_tokenizer_model_dir = resolved
        return resolved

    if str(getattr(config, "model_source", "auto") or "auto").strip().lower() == "offline":
        config.moss_audio_tokenizer_model_dir = target
        logger.warning(
            "ANGEVOICE_MODEL_SOURCE=offline，已禁用 MOSS Audio Tokenizer 自动下载；请预先把 codec_browser_onnx_meta.json 及 ONNX 资产放入：%s",
            target,
        )
        return target

    downloaded = _download_moss_audio_tokenizer_assets(config, target, logger=logger)
    if downloaded:
        resolved = resolve_valid_moss_audio_tokenizer_dir(downloaded, log=logger) or resolve_valid_moss_audio_tokenizer_dir(target, log=logger)
        if resolved:
            config.moss_audio_tokenizer_model_dir = resolved
            return resolved

    config.moss_audio_tokenizer_model_dir = target
    logger.warning(
        "未找到有效的 MOSS Audio Tokenizer ONNX 资产，已尝试自动下载但仍不可用。"
        "请检查网络，或手动把 codec_browser_onnx_meta.json 及 ONNX 资产放入：%s",
        target,
    )
    return target
