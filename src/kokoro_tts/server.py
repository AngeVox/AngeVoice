"""Kokoro TTS HTTP 服务

提供 OpenAI 兼容的 TTS API 和 Web UI。
FastAPI 在启动时才导入。
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import time
import uuid
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from typing import Optional

from .config import TTSConfig, load_config
from .engine import TTSEngine

logger = logging.getLogger(__name__)


def create_app(config: Optional[TTSConfig] = None, engine: Optional[TTSEngine] = None):
    """创建 FastAPI 应用（延迟导入 FastAPI）

    可传入自定义 config 和 engine，用于嵌入场景。
    """
    from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, StreamingResponse
    from pydantic import BaseModel, ConfigDict, Field
    from starlette.concurrency import run_in_threadpool
    from starlette.websockets import WebSocketDisconnect

    cfg = config or load_config()
    eng = engine or TTSEngine(cfg)
    tts_semaphore = asyncio.Semaphore(max(1, int(cfg.max_concurrent_requests)))
    tts_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
    active_requests: dict[str, dict] = {}
    stats = {
        "requests_total": 0,
        "requests_ok": 0,
        "requests_error": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "characters_total": 0,
        "audio_bytes_total": 0,
        "synthesis_seconds_total": 0.0,
        "ws_cancelled_total": 0,
        "started_at": time.time(),
    }

    def _new_request_id() -> str:
        return uuid.uuid4().hex[:12]

    def _cache_key(text: str, voice: str, speed: float, fmt: str) -> str:
        payload = f"{voice}\0{float(speed):.3f}\0{fmt}\0{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _cache_get(key: str):
        if not cfg.cache_enabled or cfg.cache_max_items <= 0:
            return None
        item = tts_cache.get(key)
        if item is None:
            stats["cache_misses"] += 1
            return None
        tts_cache.move_to_end(key)
        stats["cache_hits"] += 1
        return item

    def _cache_set(key: str, value: tuple[bytes, str]) -> None:
        if not cfg.cache_enabled or cfg.cache_max_items <= 0:
            return
        tts_cache[key] = value
        tts_cache.move_to_end(key)
        while len(tts_cache) > cfg.cache_max_items:
            tts_cache.popitem(last=False)

    def _mark_request(request_id: str, status: str, **extra) -> None:
        if not cfg.queue_status_enabled:
            return
        item = active_requests.setdefault(
            request_id,
            {"id": request_id, "created_at": time.time(), "status": status},
        )
        item.update({"status": status, "updated_at": time.time(), **extra})

    def _finish_request(request_id: str, status: str, **extra) -> None:
        _mark_request(request_id, status, **extra)
        if cfg.queue_status_enabled:
            # 保留最近状态，避免无限增长
            if len(active_requests) > 100:
                oldest = sorted(active_requests.items(), key=lambda kv: kv[1].get("updated_at", 0))[:20]
                for key, _ in oldest:
                    active_requests.pop(key, None)

    # Lifespan
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        eng.load()
        logger.info(f"Kokoro TTS 服务启动 (device={eng._device})")
        yield

    app = FastAPI(
        title="Kokoro TTS",
        description="轻量级中文 TTS 服务 (Kokoro v1.1)",
        version="2.4.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 模板（可选）
    templates = None
    try:
        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    except Exception:
        pass

    # 请求模型
    class TTSRequest(BaseModel):
        model: str = Field(default="kokoro", description="模型名称，兼容 OpenAI 请求")
        input: str = Field(..., description="要合成的文本", alias="text")
        voice: str = Field(default="zm_010", description="音色名称")
        speed: float = Field(default=1.0, ge=0.5, le=2.0, description="语速")
        response_format: str = Field(default="wav", description="音频格式：wav、pcm，启用 ffmpeg 后可用 mp3")

        model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # API Key 验证
    async def verify_api_key(request: Request):
        if cfg.api_key:
            auth = request.headers.get("Authorization", "")
            token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
            if not hmac.compare_digest(token, cfg.api_key or ""):
                raise HTTPException(status_code=401, detail="Invalid API key")

    def _normalize_response_format(fmt: str) -> str:
        fmt = (fmt or "wav").lower()
        if fmt in {"wav", "pcm"}:
            return fmt
        if fmt == "mp3" and getattr(cfg, "mp3_enabled", False):
            return fmt
        if fmt == "mp3":
            raise HTTPException(
                status_code=400,
                detail="MP3 output disabled. Set KOKORO_MP3_ENABLED=true and install ffmpeg.",
            )
        supported = "wav, pcm" + (", mp3" if getattr(cfg, "mp3_enabled", False) else "")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported response_format. Currently supported: {supported}",
        )

    def _synthesize_response_bytes(text: str, voice: str, speed: float, fmt: str) -> tuple[bytes, str]:
        fmt = _normalize_response_format(fmt)
        key = _cache_key(text, voice, speed, fmt)
        cached = _cache_get(key)
        if cached is not None:
            return cached

        if fmt == "pcm":
            wav = eng.synthesize_array(text=text, voice=voice, speed=speed)
            result = (eng._encode_segment(wav, "pcm_s16le"), "audio/pcm")
        elif fmt == "mp3":
            from .service_extras import _wav_to_mp3
            wav_bytes = eng.synthesize(text=text, voice=voice, speed=speed)
            result = (_wav_to_mp3(wav_bytes, getattr(cfg, "mp3_bitrate", "192k")), "audio/mpeg")
        else:
            result = (eng.synthesize(text=text, voice=voice, speed=speed), "audio/wav")
        _cache_set(key, result)
        return result

    async def _synthesize_response_threaded(text: str, voice: str, speed: float, fmt: str, request_id: str):
        start = time.perf_counter()
        stats["requests_total"] += 1
        stats["characters_total"] += len(text or "")
        _mark_request(request_id, "queued", voice=voice, format=fmt, chars=len(text or ""))
        try:
            async with tts_semaphore:
                _mark_request(request_id, "running")
                result = await asyncio.wait_for(
                    run_in_threadpool(_synthesize_response_bytes, text, voice, speed, fmt),
                    timeout=cfg.request_timeout_seconds,
                )
            elapsed = time.perf_counter() - start
            stats["requests_ok"] += 1
            stats["audio_bytes_total"] += len(result[0])
            stats["synthesis_seconds_total"] += elapsed
            _finish_request(request_id, "done", elapsed_seconds=round(elapsed, 3), bytes=len(result[0]))
            return result
        except Exception as exc:
            stats["requests_error"] += 1
            _finish_request(request_id, "error", error=str(exc))
            raise

    async def _verify_ws_key(websocket: WebSocket, token: str = "") -> bool:
        if not cfg.api_key:
            return True

        auth = websocket.headers.get("authorization", "")
        header_token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
        supplied = token or header_token
        return hmac.compare_digest(supplied, cfg.api_key or "")

    # ── 路由 ──

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if templates:
            voices = cfg.get_voices()
            return templates.TemplateResponse(request, "index.html", {"voices": voices})
        return HTMLResponse("<h1>Kokoro TTS</h1><p>API 文档: <a href='/docs'>/docs</a></p>")

    @app.get("/health")
    async def health():
        return {
            "status": "ok" if eng.is_loaded else "loading",
            "device": eng._device,
            "voices": cfg.get_voices(),
            "sample_rate": cfg.sample_rate,
            "max_concurrent_requests": cfg.max_concurrent_requests,
            "cache_enabled": cfg.cache_enabled,
            "cache_items": len(tts_cache),
            "batch_enabled": getattr(cfg, "batch_enabled", False),
            "admin_enabled": getattr(cfg, "admin_enabled", False),
            "mp3_enabled": getattr(cfg, "mp3_enabled", False),
        }

    @app.get("/v1/audio/voices")
    async def list_voices():
        return {"voices": cfg.get_voices()}

    @app.get("/stats")
    async def get_stats(_=Depends(verify_api_key)):
        if not cfg.metrics_enabled:
            raise HTTPException(status_code=404, detail="Metrics disabled")
        uptime = time.time() - stats["started_at"]
        return {
            **stats,
            "uptime_seconds": round(uptime, 3),
            "cache_items": len(tts_cache),
            "active_requests": len([r for r in active_requests.values() if r.get("status") in {"queued", "running"}]),
        }

    @app.get("/requests")
    async def get_requests(_=Depends(verify_api_key)):
        if not cfg.queue_status_enabled:
            raise HTTPException(status_code=404, detail="Queue status disabled")
        return {"requests": list(active_requests.values())[-100:]}

    @app.post("/v1/audio/speech")
    async def openai_tts(req: TTSRequest, _=Depends(verify_api_key)):
        """OpenAI 兼容 TTS 接口"""
        request_id = _new_request_id()
        try:
            audio_bytes, media_type = await _synthesize_response_threaded(
                text=req.input,
                voice=req.voice,
                speed=req.speed,
                fmt=req.response_format,
                request_id=request_id,
            )
            return StreamingResponse(
                BytesIO(audio_bytes),
                media_type=media_type,
                headers={"X-Request-ID": request_id},
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="合成超时")
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            raise HTTPException(status_code=500, detail="合成失败，请检查参数")

    @app.post("/api/tts")
    async def tts_post(request: Request, _=Depends(verify_api_key)):
        """兼容旧版接口（支持 JSON 和 Form）"""
        request_id = _new_request_id()
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

        try:
            audio_bytes, media_type = await _synthesize_response_threaded(
                text=text,
                voice=voice,
                speed=float(speed),
                fmt=fmt,
                request_id=request_id,
            )
            return StreamingResponse(
                BytesIO(audio_bytes),
                media_type=media_type,
                headers={"X-Request-ID": request_id},
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="合成超时")
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            raise HTTPException(status_code=500, detail="合成失败，请检查参数")

    @app.get("/api/tts")
    async def tts_get(
        text: str,
        voice: str = "zm_010",
        speed: float = 1.0,
        response_format: str = "wav",
        _=Depends(verify_api_key),
    ):
        """GET 方式调用"""
        request_id = _new_request_id()
        if not text:
            raise HTTPException(status_code=400, detail="缺少 text 参数")
        try:
            audio_bytes, media_type = await _synthesize_response_threaded(
                text=text,
                voice=voice,
                speed=speed,
                fmt=response_format,
                request_id=request_id,
            )
            return StreamingResponse(
                BytesIO(audio_bytes),
                media_type=media_type,
                headers={"X-Request-ID": request_id},
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="合成超时")
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            raise HTTPException(status_code=500, detail="合成失败，请检查参数")

    # ── WebSocket 流式合成 ──

    @app.websocket("/ws/v1/tts")
    async def ws_tts(websocket: WebSocket):
        await websocket.accept()
        request_id = _new_request_id()
        producer_task = None
        control_task = None
        try:
            msg = await websocket.receive_json()
            text = msg.get("text", "")
            voice = msg.get("voice", cfg.default_voice)
            speed = msg.get("speed", cfg.default_speed)
            fmt = msg.get("format", cfg.stream_format)
            token = msg.get("token", "")
            binary = bool(msg.get("binary", False)) and cfg.stream_binary_enabled

            # API Key 验证：支持首帧 token 或 Authorization: Bearer
            if not await _verify_ws_key(websocket, token=token):
                await websocket.send_json({"type": "error", "message": "Unauthorized", "request_id": request_id})
                return

            if not cfg.stream_enabled:
                await websocket.send_json({"type": "error", "message": "流式合成未启用", "request_id": request_id})
                return

            if not text:
                await websocket.send_json({"type": "error", "message": "缺少 text 参数", "request_id": request_id})
                return

            if len(text) > cfg.max_text_length:
                await websocket.send_json(
                    {"type": "error", "message": f"文本过长，上限 {cfg.max_text_length}", "request_id": request_id}
                )
                return

            queue: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            done_marker = object()
            cancel_flag = {"cancelled": False, "by_client": False}

            async def control_listener():
                """Listen for client-side {type: cancel|stop} control frames."""
                while not cancel_flag["cancelled"]:
                    try:
                        control_msg = await websocket.receive_json()
                    except WebSocketDisconnect:
                        cancel_flag["cancelled"] = True
                        cancel_flag["by_client"] = True
                        await queue.put(done_marker)
                        break
                    except Exception:
                        break

                    msg_type = str(control_msg.get("type", "")).lower()
                    if msg_type in {"cancel", "stop"}:
                        cancel_flag["cancelled"] = True
                        cancel_flag["by_client"] = True
                        stats["ws_cancelled_total"] = stats.get("ws_cancelled_total", 0) + 1
                        await queue.put({"type": "cancelled", "request_id": request_id})
                        await queue.put(done_marker)
                        break

            def producer():
                try:
                    for chunk in eng.synthesize_stream(text, voice, speed, fmt):
                        if cancel_flag["cancelled"]:
                            break
                        loop.call_soon_threadsafe(queue.put_nowait, chunk)
                except Exception as exc:
                    logger.error(f"WS TTS 生产者错误: {exc}")
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "error", "message": str(exc), "request_id": request_id},
                    )
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, done_marker)

            stats["requests_total"] += 1
            stats["characters_total"] += len(text or "")
            start = time.perf_counter()
            _mark_request(request_id, "queued", voice=voice, format=fmt, chars=len(text or ""), websocket=True)

            async with tts_semaphore:
                _mark_request(request_id, "running")
                control_task = asyncio.create_task(control_listener())
                producer_task = asyncio.create_task(asyncio.to_thread(producer))
                try:
                    while True:
                        chunk = await asyncio.wait_for(queue.get(), timeout=cfg.request_timeout_seconds)
                        if chunk is done_marker:
                            break
                        if isinstance(chunk, dict):
                            chunk.setdefault("request_id", request_id)
                        if binary and isinstance(chunk, dict) and chunk.get("type") == "audio":
                            await websocket.send_json({k: v for k, v in chunk.items() if k != "data"})
                            await websocket.send_bytes(base64.b64decode(chunk["data"]))
                        else:
                            await websocket.send_json(chunk)
                finally:
                    cancel_flag["cancelled"] = True
                    if control_task:
                        control_task.cancel()
                    await producer_task

            elapsed = time.perf_counter() - start
            if cancel_flag["by_client"]:
                _finish_request(request_id, "cancelled", elapsed_seconds=round(elapsed, 3))
            else:
                stats["requests_ok"] += 1
                stats["synthesis_seconds_total"] += elapsed
                _finish_request(request_id, "done", elapsed_seconds=round(elapsed, 3))
        except asyncio.TimeoutError:
            stats["requests_error"] += 1
            _finish_request(request_id, "timeout")
            try:
                await websocket.send_json({"type": "error", "message": "合成超时", "request_id": request_id})
            except Exception:
                pass
        except Exception as e:
            stats["requests_error"] += 1
            _finish_request(request_id, "error", error=str(e))
            logger.error(f"WS TTS 错误: {e}")
            try:
                await websocket.send_json({"type": "error", "message": str(e), "request_id": request_id})
            except Exception:
                pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    from .service_extras import register_extra_routes
    register_extra_routes(
        app=app,
        cfg=cfg,
        eng=eng,
        verify_api_key=verify_api_key,
        tts_cache=tts_cache,
        active_requests=active_requests,
        stats=stats,
        synthesize_threaded=_synthesize_response_threaded,
        new_request_id=_new_request_id,
        normalize_response_format=_normalize_response_format,
        mark_request=_mark_request,
        finish_request=_finish_request,
    )

    return app


def run_server(config: Optional[TTSConfig] = None):
    """启动 HTTP 服务"""
    import uvicorn

    cfg = config or load_config()
    app = create_app(config=cfg)
    logger.info(f"启动服务: {cfg.host}:{cfg.port}")
    uvicorn.run(app, host=cfg.host, port=cfg.port, workers=cfg.workers)
