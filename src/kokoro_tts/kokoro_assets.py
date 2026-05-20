"""Kokoro 本地模型与音色文件校验工具。

GitHub 源码 zip 中的 `models/` 往往只包含 Git LFS 指针文件，文件内容是
`version https://git-lfs.github.com/spec/v1`，而不是真正的 PyTorch 权重。
如果把这类文本指针交给 `torch.load`，会触发 `WeightsUnpickler error:
Unsupported operand 118`。这里统一做本地文件有效性判断，避免 config、engine
和 ModelScope 下载逻辑各自使用不同阈值。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

KOKORO_MODEL_MIN_BYTES = 10 * 1024 * 1024
KOKORO_VOICE_MIN_BYTES = 10 * 1024
_GIT_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_TEXT_ERROR_PREFIXES = (
    b"<!doctype html",
    b"<html",
    b"<?xml",
    b"{\"error\"",
    b"{\"message\"",
    b"version https://",
)


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
    # PyTorch 常见权重文件通常是 zip(`PK`) 或 pickle(0x80) 开头；纯 ASCII
    # 小文本更像下载错误页、LFS 指针或占位符。
    if len(head) < 512 and all(byte in b"\t\n\r " or 32 <= byte < 127 for byte in head):
        return True
    return False


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
    if file_size < int(min_bytes):
        log.warning(
            "跳过 %s：%s 大小 %d 字节 < %d 字节，可能是 Git LFS 指针或不完整下载。",
            label,
            path,
            file_size,
            int(min_bytes),
        )
        return False
    if is_git_lfs_pointer(path) or looks_like_text_placeholder(path):
        log.warning("跳过 %s：%s 看起来是 Git LFS 指针/文本占位符/下载错误页。", label, path)
        return False
    return True


def is_valid_kokoro_model_file(path: Path, *, log: logging.Logger | None = None) -> bool:
    """校验 Kokoro 主模型权重文件。"""

    return is_valid_kokoro_weight_file(path, min_bytes=KOKORO_MODEL_MIN_BYTES, label="Kokoro 模型文件", log=log)


def is_valid_kokoro_voice_file(path: Path, *, log: logging.Logger | None = None) -> bool:
    """校验 Kokoro 音色 `.pt` 文件。"""

    return is_valid_kokoro_weight_file(path, min_bytes=KOKORO_VOICE_MIN_BYTES, label="Kokoro 音色文件", log=log)


def is_valid_kokoro_config_file(path: Path, *, log: logging.Logger | None = None) -> bool:
    """校验 Kokoro config.json 是否不是 LFS/错误页。"""

    log = log or logger
    path = Path(path)
    if not path.exists() or not path.is_file():
        return False
    if is_git_lfs_pointer(path) or looks_like_text_placeholder(path):
        log.warning("跳过 Kokoro 配置文件：%s 看起来不是有效 JSON 配置。", path)
        return False
    return True


def has_valid_kokoro_local_assets(model_dir: Path, *, log: logging.Logger | None = None) -> bool:
    """判断本地目录是否具备可直接加载的 Kokoro 模型与配置。"""

    model_dir = Path(model_dir)
    return is_valid_kokoro_model_file(model_dir / "kokoro-v1_1-zh.pth", log=log) and is_valid_kokoro_config_file(
        model_dir / "config.json", log=log
    )
