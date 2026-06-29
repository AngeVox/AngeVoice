"""kokoro admin configuration fields."""

from __future__ import annotations

from ..fields import AdminConfigField, field_def


FIELDS: tuple[AdminConfigField, ...] = (
    field_def(
        "default_speed",
        "KOKORO_DEFAULT_SPEED",
        "Kokoro 默认语速",
        "kokoro",
        "float",
        1.0,
        0.5,
        2.0,
        0.05,
        help="MOSS 暂不支持语速调节，此项只影响 Kokoro。",
    ),
    field_def(
        "segment_length",
        "KOKORO_SEGMENT_LENGTH",
        "Kokoro 分句长度",
        "kokoro",
        "int",
        160,
        60,
        400,
        10,
        help="Kokoro 长文本切片长度，常用 120-200。",
    ),
    field_def(
        "stream_chunk_seconds",
        "KOKORO_STREAM_CHUNK_SECONDS",
        "Kokoro 分包秒",
        "kokoro",
        "float",
        0.55,
        0.05,
        2.0,
        0.01,
    ),
    field_def(
        "stream_prebuffer_seconds",
        "KOKORO_STREAM_PREBUFFER_SECONDS",
        "Kokoro 预缓冲",
        "kokoro",
        "float",
        0.25,
        0,
        3.0,
        0.05,
    ),
    field_def(
        "kokoro_process_isolation_enabled",
        "KOKORO_PROCESS_ISOLATION_ENABLED",
        "Kokoro 进程隔离",
        "kokoro",
        "bool",
        False,
        rebuild_moss=True,
        advanced=True,
        help="正式 Docker/fnOS 部署默认开启。开启后模型在独立 Worker 中运行，释放时可完整回收 RAM/VRAM；关闭后仅作线程内尽力释放。",
    ),
)
