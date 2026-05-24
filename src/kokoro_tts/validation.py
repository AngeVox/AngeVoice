"""Shared request validation helpers for all public TTS entry points."""

from __future__ import annotations

from fastapi import HTTPException


def normalize_text_input(value: object) -> str:
    """Normalize user supplied text without changing semantic content."""

    return str(value or "").strip()


def validate_text_input(value: object, *, max_length: int, field_name: str = "text") -> str:
    """Validate and return a normalized text value.

    This is intentionally used by every HTTP, WebSocket and batch entry point so
    the public API cannot bypass ``KOKORO_MAX_TEXT_LENGTH`` accidentally.
    """

    text = normalize_text_input(value)
    if not text:
        raise HTTPException(status_code=400, detail=f"缺少 {field_name} 参数")
    limit = max(1, int(max_length))
    if len(text) > limit:
        raise HTTPException(status_code=400, detail=f"文本过长，上限 {limit} 字符，当前 {len(text)} 字符")
    return text


def validate_tts_text(value: object, cfg, *, field_name: str = "text") -> str:
    return validate_text_input(value, max_length=int(getattr(cfg, "max_text_length", 10000)), field_name=field_name)


def is_moss_model_id(model_id: object) -> bool:
    return str(model_id or "").strip().lower().startswith("moss")


def validate_model_speed(model_id: object, speed: object) -> float:
    """Validate ``speed`` and reject unsupported MOSS speed control.

    MOSS-TTS-Nano runtime currently ignores/does not expose stable speed control.
    Failing fast avoids the front-end being honest while API users can still pass
    a misleading value.
    """

    try:
        value = float(speed)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="speed 必须是数字") from None
    if is_moss_model_id(model_id) and abs(value - 1.0) > 1e-6:
        raise HTTPException(status_code=400, detail="MOSS-TTS-Nano 暂不支持语速调节，请使用 speed=1.0")
    return value
