"""HTTP 音频合成路由。"""

import asyncio
import base64
import logging
from contextlib import suppress
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

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


def _normalize_response_encoding(value: str | None) -> str:
    """归一化前端友好的响应编码格式。

    ``binary`` 保持 OpenAI 兼容行为，返回原始音频字节流；
    ``base64``/``json`` 返回包含裸 base64 和 data URL 的 JSON 对象，
    更适合 WebView/PWA 阅读器缓存和播放。
    """
    normalized = str(value or "binary").strip().lower().replace("-", "_")
    if normalized in {"", "binary", "bytes", "stream", "audio"}:
        return "binary"
    if normalized in {"base64", "json", "data_url", "dataurl"}:
        return "base64"
    raise HTTPException(status_code=400, detail="response_encoding must be binary or base64")


def _audio_metadata_for_model(state: ServiceState, model_id: str) -> dict:
    """尽力获取音频元数据，不强制加载模型。"""
    try:
        if model_id == state.model_manager.current_model_id:
            snapshot = state.model_manager.current_snapshot()
        else:
            snapshot = next((m for m in state.model_manager.list_models() if m.get("id") == model_id), {})
    except Exception:
        snapshot = {}
    return {
        "sample_rate": snapshot.get("sample_rate") or state.cfg.sample_rate,
        "channels": snapshot.get("channels") or 1,
    }


def _audio_json_response(
    *,
    audio_bytes: bytes,
    media_type: str,
    request_id: str,
    model_id: str,
    voice: str,
    response_format: str,
    state: ServiceState,
) -> JSONResponse:
    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    data_url = f"data:{media_type};base64,{audio_b64}"
    fmt = state.normalize_response_format(response_format)
    payload = {
        "request_id": request_id,
        "model": model_id,
        "voice": voice,
        "response_format": fmt,
        "media_type": media_type,
        "encoding": "base64",
        "audio_base64": data_url,
        "audio": audio_b64,
        "bytes": len(audio_bytes),
        **_audio_metadata_for_model(state, model_id),
    }
    return JSONResponse(payload, headers={"X-Request-ID": request_id})


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
        response_encoding = _normalize_response_encoding(req.response_encoding)
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesize_response_threaded(text, req.voice, speed, req.response_format, request_id, model),
            request_id,
        )
        if response_encoding == "base64":
            return _audio_json_response(
                audio_bytes=audio_bytes,
                media_type=media_type,
                request_id=request_id,
                model_id=model,
                voice=req.voice,
                response_format=req.response_format,
                state=state,
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
            response_encoding = data.get("response_encoding", data.get("encoding", "binary"))
            model = data.get("model")
        else:
            form = await request.form()
            text = form.get("text")
            voice = form.get("voice", cfg.default_voice)
            speed = form.get("speed", cfg.default_speed)
            fmt = form.get("response_format", form.get("format", "wav"))
            response_encoding = form.get("response_encoding", form.get("encoding", "binary"))
            model = form.get("model")
            upload = form.get("prompt_audio") or form.get("reference_audio")
            prompt_audio_path, prompt_audio_id = await _save_prompt_audio_upload(upload, request_id, cfg.moss_prompt_upload_max_bytes)

        try:
            text = validate_tts_text(text, cfg)
            model = state.model_manager.normalize_model_id(model)
            speed = validate_model_speed(model, speed)
            response_encoding = _normalize_response_encoding(response_encoding)
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
        if response_encoding == "base64":
            return _audio_json_response(
                audio_bytes=audio_bytes,
                media_type=media_type,
                request_id=request_id,
                model_id=model,
                voice=voice,
                response_format=fmt,
                state=state,
            )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    @router.get("/api/tts")
    async def tts_get(
        text: str,
        voice: str = "zm_010",
        speed: float = 1.0,
        response_format: str = "wav",
        response_encoding: str = "binary",
        model: str | None = None,
        _=Depends(verify_api_key),
    ):
        request_id = state.new_request_id()
        text = validate_tts_text(text, cfg)
        model = state.model_manager.normalize_model_id(model)
        speed = validate_model_speed(model, speed)
        response_encoding = _normalize_response_encoding(response_encoding)
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesize_response_threaded(text, voice, speed, response_format, request_id, model),
            request_id,
        )
        if response_encoding == "base64":
            return _audio_json_response(
                audio_bytes=audio_bytes,
                media_type=media_type,
                request_id=request_id,
                model_id=model,
                voice=voice,
                response_format=response_format,
                state=state,
            )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    return router
