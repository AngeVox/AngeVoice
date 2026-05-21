"""Kokoro 本地模型与音色文件校验工具。

GitHub 源码 zip 中的 ``models/`` 往往只包含 Git LFS 指针文件，文件内容是
``version https://git-lfs.github.com/spec/v1``，而不是真正的 PyTorch 权重。
如果把这类文本指针交给 ``torch.load``，会触发 ``WeightsUnpickler error:
Unsupported operand 118``。这里统一做本地文件有效性判断，避免 config、engine
和 ModelScope 下载逻辑各自使用不同阈值。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

KOKORO_MODEL_FILENAME = "kokoro-v1_1-zh.pth"
KOKORO_REPO_CACHE_DIR = "models--hexgrad--Kokoro-82M-v1.1-zh"
MOSS_ONNX_DIR = "MOSS-TTS-Nano-100M-ONNX"
KOKORO_MODEL_MIN_BYTES = 10 * 1024 * 1024
# Kokoro 音色文件确实比主模型小很多，不能只用 10KB 这类粗阈值判断。
# 这里用文件头识别 PyTorch zip/pickle 权重，只把 LFS 指针、HTML/JSON 错误页
# 和极小文本占位符判为无效。
KOKORO_VOICE_MIN_BYTES = 512
_GIT_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_TEXT_ERROR_PREFIXES = (
    b"<!doctype html",
    b"<html",
    b"<?xml",
    b"{\"error\"",
    b"{\"message\"",
    b"version https://",
)
_TORCH_SIGNATURES = (b"PK\x03\x04", b"\x80")
_WARNED_INVALID_PATHS: set[str] = set()


def models_root() -> Path:
    """返回统一模型根目录。"""

    return Path(os.environ.get("ANGEVOICE_MODELS_ROOT", "/app/models")).expanduser()


def default_kokoro_model_dir(root: Path | None = None) -> Path:
    """返回 Kokoro 推荐持久化目录。"""

    return (root or models_root()) / KOKORO_REPO_CACHE_DIR


def default_moss_model_dir(root: Path | None = None) -> Path:
    """返回 MOSS ONNX 推荐持久化目录。"""

    return (root or models_root()) / MOSS_ONNX_DIR


def _warn_once(log: logging.Logger, key: str, message: str, *args) -> None:
    if key in _WARNED_INVALID_PATHS:
        return
    _WARNED_INVALID_PATHS.add(key)
    log.warning(message, *args)


def _read_head(path: Path, size: int = 512) -> bytes:
    try:
        with Path(path).open("rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def is_git_lfs_pointer(path: Path) -> bool:
    """判断文件是否是 Git LFS 指针。"""

    return _read_head(path).lstrip().startswith(_GIT_LFS_PREFIX)


def looks_like_text_placeholder(path: Path) -> bool:
    """识别 HTML/JSON 错误页、LFS 指针等明显不是权重的文本文件。"""

    head = _read_head(path).lstrip().lower()
    if not head:
        return True
    if head.startswith(_TEXT_ERROR_PREFIXES):
        return True
    if head.startswith(_TORCH_SIGNATURES):
        return False
    # 小型纯 ASCII 文件更像下载错误页、LFS 指针或占位符；真实 torch 权重
    # 通常是 zip/pickle 二进制，即使体积很小也不会是这种纯文本。
    if len(head) < 512 and all(byte in b"\t\n\r " or 32 <= byte < 127 for byte in head):
        return True
    return False


def _has_torch_signature(path: Path) -> bool:
    return _read_head(path, 8).startswith(_TORCH_SIGNATURES)




def kokoro_voice_dir_candidates(model_dir: Path | None = None) -> list[Path]:
    """返回 Kokoro 音色目录候选，兼容本地目录和 Hugging Face 缓存快照。"""

    root = models_root()
    repo_dir = default_kokoro_model_dir(root)
    candidates: list[Path] = []
    if model_dir:
        base = Path(model_dir).expanduser()
        candidates.append(base / "voices")
        candidates.extend(sorted((base / "snapshots").glob("*/voices")))
    candidates.extend(
        [
            repo_dir / "voices",
            root / "voices",
        ]
    )
    candidates.extend(sorted((repo_dir / "snapshots").glob("*/voices")))
    candidates.extend(sorted((root / "models--hexgrad--Kokoro-82M-v1.1-zh" / "snapshots").glob("*/voices")))

    seen: set[str] = set()
    deduped: list[Path] = []
    for item in candidates:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped

def is_valid_kokoro_weight_file(path: Path, *, min_bytes: int, label: str, log: logging.Logger | None = None) -> bool:
    """校验 Kokoro 模型/音色权重是否像真实本地文件。"""

    log = log or logger
    path = Path(path)
    if not path.exists() or not path.is_file():
        return False
    try:
        file_size = path.stat().st_size
    except OSError:
        return False
    key = str(path.resolve()) if path.exists() else str(path)
    if is_git_lfs_pointer(path) or looks_like_text_placeholder(path):
        _warn_once(log, key, "跳过 %s：%s 看起来是 Git LFS 指针、文本占位符或下载错误页。", label, path)
        return False
    if file_size < int(min_bytes) and not _has_torch_signature(path):
        _warn_once(
            log,
            key,
            "跳过 %s：%s 大小 %d 字节 < %d 字节，且不是 PyTorch 权重文件头。",
            label,
            path,
            file_size,
            int(min_bytes),
        )
        return False
    return True


def is_valid_kokoro_model_file(path: Path, *, log: logging.Logger | None = None) -> bool:
    """校验 Kokoro 主模型权重文件。"""

    return is_valid_kokoro_weight_file(path, min_bytes=KOKORO_MODEL_MIN_BYTES, label="Kokoro 模型文件", log=log)


def is_valid_kokoro_voice_file(path: Path, *, log: logging.Logger | None = None) -> bool:
    """校验 Kokoro 音色 ``.pt`` 文件。

    音色文件可能远小于主模型，因此以文件头和占位符识别为主，不再对所有
    小文件刷屏 warning。
    """

    return is_valid_kokoro_weight_file(path, min_bytes=KOKORO_VOICE_MIN_BYTES, label="Kokoro 音色文件", log=log)


def is_valid_kokoro_config_file(path: Path, *, log: logging.Logger | None = None) -> bool:
    """校验 Kokoro config.json 是否不是 LFS/错误页，且内容是合法 JSON。"""

    log = log or logger
    path = Path(path)
    if not path.exists() or not path.is_file():
        return False
    if is_git_lfs_pointer(path):
        _warn_once(log, str(path.resolve()), "跳过 Kokoro 配置文件：%s 是 Git LFS 指针。", path)
        return False
    if looks_like_text_placeholder(path):
        # 短 JSON 配置可能被纯文本启发式误判，额外尝试 JSON 解析验证。
        import json as _json
        try:
            with path.open("r", encoding="utf-8") as fh:
                _json.load(fh)
        except (ValueError, UnicodeDecodeError):
            _warn_once(log, str(path.resolve()), "跳过 Kokoro 配置文件：%s 看起来不是有效 JSON 配置。", path)
            return False
    return True


def has_valid_kokoro_local_assets(model_dir: Path, *, log: logging.Logger | None = None) -> bool:
    """判断本地目录是否具备可直接加载的 Kokoro 模型与配置。"""

    model_dir = Path(model_dir)
    return is_valid_kokoro_model_file(model_dir / KOKORO_MODEL_FILENAME, log=log) and is_valid_kokoro_config_file(
        model_dir / "config.json", log=log
    )


def kokoro_model_dir_candidates(extra: Iterable[Path] | None = None) -> list[Path]:
    """返回 Kokoro 本地目录候选列表，兼容新旧持久化布局。"""

    root = models_root()
    candidates: list[Path] = []
    if extra:
        candidates.extend(Path(item).expanduser() for item in extra if item)
    env_dir = os.environ.get("KOKORO_MODEL_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.extend(
        [
            default_kokoro_model_dir(root),
            root,
            Path.cwd() / "models" / KOKORO_REPO_CACHE_DIR,
            Path.cwd() / "models",
            Path(__file__).resolve().parent.parent.parent / "models" / KOKORO_REPO_CACHE_DIR,
            Path(__file__).resolve().parent.parent.parent / "models",
            Path("/app/models") / KOKORO_REPO_CACHE_DIR,
            Path("/app/models"),
        ]
    )
    seen: set[str] = set()
    deduped: list[Path] = []
    for item in candidates:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
