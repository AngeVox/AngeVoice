"""HTTP 音频合成路由。"""

import asyncio
import base64
import json
import logging
from contextlib import suppress
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from ..api_models import TTSRequest
from ..prompt_audio import delete_prompt_audio_path, save_prompt_audio_upload, validate_reference_audio_duration
from ..validation import is_no_synthesizable_text_error, no_synthesizable_text_detail
from ..service_state import ServiceState

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
    if value == 0:
        raise HTTPException(status_code=400, detail="请求体为空")
    return value


def _enforce_request_size_limit(request: Request, max_bytes: int) -> None:
    length = _parse_content_length(request)
    if length > max_bytes:
        raise HTTPException(status_code=413, detail=f"请求体过大，最大 {max_bytes} 字节")


async def _read_limited_json(request: Request, max_bytes: int) -> dict:
    """先校验请求体大小，再解析 JSON。"""
    _enforce_request_size_limit(request, max_bytes)
    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 请求体格式非法") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON 请求体必须是对象")
    return data


def _build_openai_request(data: dict) -> TTSRequest:
    try:
        return TTSRequest.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def _normalize_response_encoding(value: str | None) -> str:
    """归一化前端友好的响应编码格式。

    ``binary`` 保持 OpenAI 兼容行为，返回原始音频字节流；
    ``base64``/``json`` 返回包含裸 base64 和 data URL 的 JSON 对象。
    两种表示为现有 API/阅读器客户端兼容而保留；二进制响应可避免 JSON 体积开销。
    """
    normalized = str(value or "binary").strip().lower().replace("-", "_")
    if normalized in {"", "binary", "bytes", "stream", "audio"}:
        return "binary"
    if normalized in {"base64", "json", "data_url", "dataurl"}:
        return "base64"
    raise HTTPException(status_code=400, detail="response_encoding must be binary or base64")


def _text_normalization_from(data) -> str | None:
    if not hasattr(data, "get"):
        return None
    value = data.get("text_normalization")
    if value in {None, ""}:
        value = data.get("tn_engine")
    if value in {None, ""}:
        return None
    return str(value)


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


def _request_id_for_http_request(request: Request, state: ServiceState) -> str:
    return state.request_id_from_client(
        request.headers.get("X-Client-Request-ID")
        or request.headers.get("X-Request-ID")
        or request.query_params.get("request_id")
    )


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
    except ZeroDivisionError as exc:
        logger.warning("TTS 文本无可合成 token，已转换为结构化错误", extra={"request_id": request_id})
        raise HTTPException(status_code=400, detail=no_synthesizable_text_detail(request_id=request_id, reason=str(exc))) from exc
    except ValueError as exc:
        if is_no_synthesizable_text_error(exc):
            raise HTTPException(status_code=400, detail=no_synthesizable_text_detail(request_id=request_id, reason=str(exc))) from exc
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        if is_no_synthesizable_text_error(exc):
            logger.warning("TTS 底层返回无可合成文本错误", extra={"request_id": request_id})
            raise HTTPException(status_code=400, detail=no_synthesizable_text_detail(request_id=request_id, reason=str(exc))) from exc
        logger.exception("TTS 请求失败", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail=f"合成失败，请检查参数（请求 ID: {request_id}）",
            headers={"X-Request-ID": request_id},
        )

async def _save_prompt_audio_upload(upload, request_id: str, max_bytes: int) -> tuple[str | None, str]:
    if not upload or not getattr(upload, "filename", "") or not callable(getattr(upload, "read", None)):
        return None, ""
    try:
        path, digest = await save_prompt_audio_upload(
            upload=upload,
            filename=str(upload.filename or "prompt.wav"),
            request_id=request_id,
            max_bytes=max_bytes,
        )
    finally:
        with suppress(Exception):
            await upload.close()
    if not path:
        raise HTTPException(status_code=400, detail="参考音频为空")
    return path, digest


async def _parse_json_tts_parameters(request: Request, cfg) -> dict:
    data = await _read_limited_json(request, cfg.tts_request_max_bytes)
    return {
        "text": data.get("text") or data.get("input") or data.get("prompt"),
        "voice": data.get("voice") or data.get("speaker") or cfg.default_voice,
        "speed": data.get("speed", data.get("rate", cfg.default_speed)),
        "fmt": data.get("response_format", data.get("format", "wav")),
        "response_encoding": data.get("response_encoding", data.get("encoding", "binary")),
        "model": data.get("model"),
        "prompt_text": str(data.get("prompt_text") or ""),
        "prompt_audio_path": None,
        "prompt_audio_id": "",
        "engine_params": data.get("engine_params") if isinstance(data.get("engine_params"), dict) else {},
        "text_normalization": _text_normalization_from(data),
        "parameter_source": data,
    }


async def _parse_form_tts_parameters(request: Request, state: ServiceState, request_id: str, cfg) -> dict:
    form = await request.form()
    model = form.get("model")
    upload_model = state.model_manager.normalize_model_id(model)
    upload = form.get("prompt_audio") or form.get("reference_audio")
    max_upload = state.voice_profiles.upload_limit_bytes(upload_model)
    prompt_audio_path, prompt_audio_id = await _save_prompt_audio_upload(upload, request_id, max_upload)
    if prompt_audio_path and upload_model == "zipvoice":
        try:
            validate_reference_audio_duration(
                prompt_audio_path, max_seconds=state.voice_profiles.reference_max_seconds(upload_model)
            )
        except HTTPException:
            delete_prompt_audio_path(prompt_audio_path)
            prompt_audio_path = None
            raise
    return {
        "text": form.get("text"),
        "voice": form.get("voice", cfg.default_voice),
        "speed": form.get("speed", cfg.default_speed),
        "fmt": form.get("response_format", form.get("format", "wav")),
        "response_encoding": form.get("response_encoding", form.get("encoding", "binary")),
        "model": model,
        "prompt_text": str(form.get("prompt_text") or ""),
        "prompt_audio_path": prompt_audio_path,
        "prompt_audio_id": prompt_audio_id,
        "engine_params": {},
        "text_normalization": _text_normalization_from(form),
        "parameter_source": form,
    }


async def _parse_tts_post_parameters(request: Request, state: ServiceState, request_id: str, cfg) -> dict:
    if "application/json" in request.headers.get("Content-Type", ""):
        return await _parse_json_tts_parameters(request, cfg)
    _enforce_request_size_limit(request, cfg.tts_request_max_bytes)
    return await _parse_form_tts_parameters(request, state, request_id, cfg)


def create_audio_router(state: ServiceState, verify_api_key) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg

    @router.post("/v1/audio/speech")
    async def openai_tts(request: Request, _=Depends(verify_api_key)):
        request_id = _request_id_for_http_request(request, state)
        req = _build_openai_request(await _read_limited_json(request, cfg.tts_request_max_bytes))
        response_encoding = _normalize_response_encoding(req.response_encoding)
        internal_request = state.synthesis.build_request(
            text=req.input,
            voice=req.voice,
            speed=req.speed,
            response_format=req.response_format,
            response_encoding=response_encoding,
            model_id=req.model,
            engine_params=req.engine_params,
            parameter_source=req.model_dump(),
            text_normalization=req.text_normalization,
            request_id=request_id,
        )
        model = internal_request.model_id
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesis.response_threaded(internal_request), request_id
        )
        if response_encoding == "base64":
            return _audio_json_response(
                audio_bytes=audio_bytes,
                media_type=media_type,
                request_id=request_id,
                model_id=model,
                voice=internal_request.voice,
                response_format=req.response_format,
                state=state,
            )
        return StreamingResponse(BytesIO(audio_bytes), media_type=media_type, headers={"X-Request-ID": request_id})

    @router.post("/api/tts")
    async def tts_post(request: Request, _=Depends(verify_api_key)):
        request_id = _request_id_for_http_request(request, state)
        params = await _parse_tts_post_parameters(request, state, request_id, cfg)
        prompt_audio_path = params["prompt_audio_path"]

        try:
            response_encoding = _normalize_response_encoding(params["response_encoding"])
            internal_request = state.synthesis.build_request(
                text=params["text"], voice=params["voice"], speed=params["speed"], response_format=params["fmt"],
                response_encoding=response_encoding, model_id=params["model"], request_id=request_id,
                prompt_audio_path=prompt_audio_path, prompt_audio_id=params["prompt_audio_id"],
                prompt_text=params["prompt_text"], engine_params=params["engine_params"],
                parameter_source=params["parameter_source"], text_normalization=params["text_normalization"],
            )
            model = internal_request.model_id
            audio_bytes, media_type = await _run_tts_call(
                lambda: state.synthesis.response_threaded(internal_request), request_id
            )
        finally:
            if prompt_audio_path:
                delete_prompt_audio_path(prompt_audio_path)
        if response_encoding == "base64":
            return _audio_json_response(
                audio_bytes=audio_bytes,
                media_type=media_type,
                request_id=request_id,
                model_id=model,
                voice=params["voice"],
                response_format=params["fmt"],
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
        zipvoice_num_steps: int | None = None,
        zipvoice_remove_long_sil: bool | None = None,
        text_normalization: str | None = None,
        request_id: str | None = None,
        _=Depends(verify_api_key),
    ):
        request_id = state.request_id_from_client(request_id)
        response_encoding = _normalize_response_encoding(response_encoding)
        internal_request = state.synthesis.build_request(
            text=text, voice=voice, speed=speed, response_format=response_format,
            response_encoding=response_encoding, model_id=model, request_id=request_id,
            text_normalization=text_normalization,
            parameter_source={"zipvoice_num_steps": zipvoice_num_steps, "zipvoice_remove_long_sil": zipvoice_remove_long_sil},
        )
        model = internal_request.model_id
        audio_bytes, media_type = await _run_tts_call(
            lambda: state.synthesis.response_threaded(internal_request), request_id
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
