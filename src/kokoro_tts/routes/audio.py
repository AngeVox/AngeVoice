"""HTTP audio synthesis routes."""

import asyncio
import logging
from contextlib import suppress
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..api_models import TTSRequest
from ..prompt_audio import save_prompt_audio_bytes
from ..service_state import ServiceState
from ..validation import validate_model_speed, validate_tts_text

logger = logging.getLogger(__name__)


def _parse_content_length(request: Request) -> int:
    raw = request.headers.get("Content-Length")
    if not raw:
        raise HTTPException(status_code=411, detail="缺少 Content-Length")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Content-Length 非法")
    if value < 0:
        raise HTTPException(status_code=400, detail="Content-Length 非法")
    return value


def _enforce_request_size_limit(request: Request, max_bytes: int) -> None:
    length = _parse_content_length(request)
    if length > max_bytes:
        raise HTTPException(status_code=413, detail=f"请求体过大，最大 {max_bytes} 字节")

async def _run_tts_call(callable_, request_id: str):
    try:
        return await callable_()
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="合成超时")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("TTS request failed", extra={"request_id": request_id})
        raise HTTPException(status_code=500, detail="合成失败，请检查参数")


async def _save_prompt_audio_upload(upload, request_id: str, max_bytes: int) -> tuple[str | None, str]:
    if not upload or not getattr(upload, "filename", "") or not callable(getattr(upload, "read", None)):
        return None, ""
    content = await upload.read(int(max_bytes) + 1)
    with suppress(Exception):
        await upload.close()
    if not content:
        raise HTTPException(status_code=400, detail="参考音频为空")
    return save_prompt_audio_bytes(
        content=content,
        filename=str(upload.filename or "prompt.wav"),
        request_id=request_id,
        max_bytes=max_bytes,
    )


def create_audio_router(state: ServiceState, verify_api_key) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg

    @router.post("/v1/audio/speech")
    async def openai_tts(req: TTSRequest, _=Depends(verify_api_key)):
        request_id = state.new_request_id()
        text = validate_tts_text(req.input, cfg, field_name="input")
        model = state.model_manager.normalize_model_id(req.model)
        speed = validate_model_speed(model, req.speed)
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesize_response_threaded(text, req.voice, speed, req.response_format, request_id, model),
            request_id,
        )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    @router.post("/api/tts")
    async def tts_post(request: Request, _=Depends(verify_api_key)):
        request_id = state.new_request_id()
        content_type = request.headers.get("Content-Type", "")
        _enforce_request_size_limit(request, cfg.tts_request_max_bytes)
        prompt_audio_path: str | None = None
        prompt_audio_id = ""
        if "application/json" in content_type:
            data = await request.json()
            text = data.get("text") or data.get("input") or data.get("prompt")
            voice = data.get("voice") or data.get("speaker") or cfg.default_voice
            speed = data.get("speed", data.get("rate", cfg.default_speed))
            fmt = data.get("response_format", data.get("format", "wav"))
            model = data.get("model")
        else:
            form = await request.form()
            text = form.get("text")
            voice = form.get("voice", cfg.default_voice)
            speed = form.get("speed", cfg.default_speed)
            fmt = form.get("response_format", form.get("format", "wav"))
            model = form.get("model")
            upload = form.get("prompt_audio") or form.get("reference_audio")
            prompt_audio_path, prompt_audio_id = await _save_prompt_audio_upload(upload, request_id, cfg.moss_prompt_upload_max_bytes)

        try:
            text = validate_tts_text(text, cfg)
            model = state.model_manager.normalize_model_id(model)
            speed = validate_model_speed(model, speed)
            audio_bytes, media_type = await _run_tts_call(
                lambda: state.synthesize_response_threaded(
                    text,
                    voice,
                    speed,
                    fmt,
                    request_id,
                    model,
                    prompt_audio_path,
                    prompt_audio_id,
                ),
                request_id,
            )
        finally:
            if prompt_audio_path:
                with suppress(OSError):
                    Path(prompt_audio_path).unlink()
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    @router.get("/api/tts")
    async def tts_get(
        text: str,
        voice: str = "zm_010",
        speed: float = 1.0,
        response_format: str = "wav",
        model: str | None = None,
        _=Depends(verify_api_key),
    ):
        request_id = state.new_request_id()
        text = validate_tts_text(text, cfg)
        model = state.model_manager.normalize_model_id(model)
        speed = validate_model_speed(model, speed)
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesize_response_threaded(text, voice, speed, response_format, request_id, model),
            request_id,
        )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    return router
