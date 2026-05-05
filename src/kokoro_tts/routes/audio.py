"""HTTP audio synthesis routes."""

import asyncio
import logging
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..api_models import TTSRequest
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


def create_audio_router(state: ServiceState, verify_api_key) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg

    @router.post("/v1/audio/speech")
    async def openai_tts(req: TTSRequest, _=Depends(verify_api_key)):
        request_id = state.new_request_id()
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesize_response_threaded(req.input, req.voice, req.speed, req.response_format, request_id),
            request_id,
        )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    @router.post("/api/tts")
    async def tts_post(request: Request, _=Depends(verify_api_key)):
        request_id = state.new_request_id()
        content_type = request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            data = await request.json()
            text = data.get("text") or data.get("input") or data.get("prompt")
            voice = data.get("voice") or data.get("speaker") or cfg.default_voice
            speed = data.get("speed", data.get("rate", cfg.default_speed))
            fmt = data.get("response_format", data.get("format", "wav"))
        else:
            form = await request.form()
            text = form.get("text")
            voice = form.get("voice", cfg.default_voice)
            speed = form.get("speed", cfg.default_speed)
            fmt = form.get("response_format", form.get("format", "wav"))

        if not text:
            raise HTTPException(status_code=400, detail="缺少 text 参数")
        if len(text) > cfg.max_text_length:
            raise HTTPException(status_code=400, detail=f"文本过长，上限 {cfg.max_text_length} 字符")

        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesize_response_threaded(text, voice, float(speed), fmt, request_id),
            request_id,
        )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    @router.get("/api/tts")
    async def tts_get(text: str, voice: str = "zm_010", speed: float = 1.0, response_format: str = "wav", _=Depends(verify_api_key)):
        request_id = state.new_request_id()
        if not text:
            raise HTTPException(status_code=400, detail="缺少 text 参数")
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesize_response_threaded(text, voice, speed, response_format, request_id),
            request_id,
        )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    return router
