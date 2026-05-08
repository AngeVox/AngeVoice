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

logger = logging.getLogger(__name__)

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
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesize_response_threaded(req.input, req.voice, req.speed, req.response_format, request_id, req.model),
            request_id,
        )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    @router.post("/api/tts")
    async def tts_post(request: Request, _=Depends(verify_api_key)):
        request_id = state.new_request_id()
        content_type = request.headers.get("Content-Type", "")
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
            if not text:
                raise HTTPException(status_code=400, detail="缺少 text 参数")
            if len(text) > cfg.max_text_length:
                raise HTTPException(status_code=400, detail=f"文本过长，上限 {cfg.max_text_length} 字符")
            audio_bytes, media_type = await _run_tts_call(
                lambda: state.synthesize_response_threaded(
                    text,
                    voice,
                    float(speed),
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
    async def tts_get(text: str, voice: str = "zm_010", speed: float = 1.0, response_format: str = "wav", model: str | None = None, _=Depends(verify_api_key)):
        request_id = state.new_request_id()
        if not text:
            raise HTTPException(status_code=400, detail="缺少 text 参数")
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesize_response_threaded(text, voice, speed, response_format, request_id, model),
            request_id,
        )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    return router
