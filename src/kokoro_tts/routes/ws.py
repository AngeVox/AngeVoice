"""WebSocket streaming synthesis route."""

import asyncio
import base64
import logging
import time

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..security import verify_ws_key
from ..service_state import ServiceState

logger = logging.getLogger(__name__)


def create_ws_router(state: ServiceState) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg

    @router.websocket("/ws/v1/tts")
    async def ws_tts(websocket: WebSocket):
        await websocket.accept()
        request_id = state.new_request_id()
        producer_task = None
        control_task = None
        saw_stream_error = False
        stream_error_counted = False
        try:
            msg = await websocket.receive_json()
            text = msg.get("text", "")
            model = state.model_manager.normalize_model_id(msg.get("model"))
            target_engine = state.model_manager.get_engine(model, load=False)
            voice = msg.get("voice") or getattr(target_engine, "default_voice", cfg.default_voice)
            speed = msg.get("speed", cfg.default_speed)
            fmt = msg.get("format", cfg.stream_format)
            token = msg.get("token", "")
            binary = bool(msg.get("binary", False)) and cfg.stream_binary_enabled

            if not await verify_ws_key(cfg, websocket, token=token):
                await websocket.send_json({"type": "error", "message": "Unauthorized", "request_id": request_id})
                return
            if not cfg.stream_enabled:
                await websocket.send_json({"type": "error", "message": "流式合成未启用", "request_id": request_id})
                return
            if not text:
                await websocket.send_json({"type": "error", "message": "缺少 text 参数", "request_id": request_id})
                return
            if len(text) > cfg.max_text_length:
                await websocket.send_json({"type": "error", "message": f"文本过长，上限 {cfg.max_text_length}", "request_id": request_id})
                return

            queue: asyncio.Queue = asyncio.Queue(maxsize=1)
            loop = asyncio.get_running_loop()
            done_marker = object()
            cancel_flag = {"cancelled": False, "by_client": False, "notified": False}

            async def drain_queue():
                while True:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

            async def notify_cancelled():
                if cancel_flag["notified"]:
                    return
                cancel_flag["notified"] = True
                await drain_queue()
                await queue.put({"type": "cancelled", "request_id": request_id})
                await queue.put(done_marker)

            async def control_listener():
                while not cancel_flag["cancelled"]:
                    try:
                        control_msg = await websocket.receive_json()
                    except WebSocketDisconnect:
                        state.request_cancel(request_id)
                        cancel_flag["cancelled"] = True
                        cancel_flag["by_client"] = True
                        await notify_cancelled()
                        break
                    except Exception:
                        break
                    msg_type = str(control_msg.get("type", "")).lower()
                    if msg_type in {"cancel", "stop"}:
                        state.request_cancel(request_id)
                        cancel_flag["cancelled"] = True
                        cancel_flag["by_client"] = True
                        await notify_cancelled()
                        break

            def thread_put(item):
                fut = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
                fut.result(timeout=max(1.0, float(cfg.request_timeout_seconds)))

            def producer():
                try:
                    with state.model_manager.borrow(model) as eng:
                        for chunk in eng.synthesize_stream(text, voice, speed, fmt):
                            if cancel_flag["cancelled"] or state.is_cancelled(request_id):
                                break
                            if isinstance(chunk, dict):
                                chunk.setdefault("model", model)
                            thread_put(chunk)
                except Exception:
                    logger.exception("WS TTS producer failed", extra={"request_id": request_id})
                    if not cancel_flag["cancelled"]:
                        try:
                            thread_put({"type": "error", "message": "流式合成失败", "request_id": request_id})
                        except Exception:
                            logger.exception("Failed to deliver WS error message", extra={"request_id": request_id})
                finally:
                    if cancel_flag["cancelled"] or state.is_cancelled(request_id):
                        loop.call_soon_threadsafe(asyncio.create_task, notify_cancelled())
                    else:
                        try:
                            thread_put(done_marker)
                        except Exception:
                            logger.exception("Failed to deliver WS completion marker", extra={"request_id": request_id})

            state.inc_stat("requests_total")
            state.inc_stat("characters_total", len(text or ""))
            start = time.perf_counter()
            state.mark_request(request_id, "queued", voice=voice, format=fmt, model=model, chars=len(text or ""), websocket=True)

            async with state.tts_semaphore:
                state.mark_request(request_id, "running")
                control_task = asyncio.create_task(control_listener())
                producer_task = asyncio.create_task(asyncio.to_thread(producer))
                try:
                    while True:
                        chunk = await asyncio.wait_for(queue.get(), timeout=cfg.request_timeout_seconds)
                        if chunk is done_marker:
                            break
                        if isinstance(chunk, dict):
                            chunk.setdefault("request_id", request_id)
                            if chunk.get("type") in {"error", "segment_error"}:
                                saw_stream_error = True
                                if not stream_error_counted:
                                    state.inc_stat("requests_error")
                                    stream_error_counted = True
                                    state.mark_request(request_id, "error", error="stream returned error frame")
                        if binary and isinstance(chunk, dict) and chunk.get("type") == "audio":
                            await websocket.send_json({k: v for k, v in chunk.items() if k != "data"})
                            await websocket.send_bytes(base64.b64decode(chunk["data"]))
                        else:
                            await websocket.send_json(chunk)
                        if isinstance(chunk, dict) and chunk.get("type") == "cancelled":
                            break
                finally:
                    cancel_flag["cancelled"] = True
                    if control_task:
                        control_task.cancel()
                    if producer_task:
                        await producer_task

            elapsed = time.perf_counter() - start
            if cancel_flag["by_client"] or state.is_cancelled(request_id):
                state.finish_request(request_id, "cancelled", elapsed_seconds=round(elapsed, 3))
            elif saw_stream_error:
                if not stream_error_counted:
                    state.inc_stat("requests_error")
                state.finish_request(request_id, "error", elapsed_seconds=round(elapsed, 3), error="stream returned error frame")
            else:
                state.inc_stat("requests_ok")
                state.inc_stat("synthesis_seconds_total", elapsed)
                state.finish_request(request_id, "done", elapsed_seconds=round(elapsed, 3))
        except asyncio.TimeoutError:
            state.inc_stat("requests_error")
            state.finish_request(request_id, "timeout")
            try:
                await websocket.send_json({"type": "error", "message": "合成超时", "request_id": request_id})
            except Exception:
                pass
        except Exception:
            state.inc_stat("requests_error")
            state.finish_request(request_id, "error")
            logger.exception("WS TTS failed", extra={"request_id": request_id})
            try:
                await websocket.send_json({"type": "error", "message": "流式合成失败", "request_id": request_id})
            except Exception:
                pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    return router
