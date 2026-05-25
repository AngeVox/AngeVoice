"""WebSocket 流式合成路由。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import threading
import time
from contextlib import suppress
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..contracts import StreamingRequest
from ..prompt_audio import decode_prompt_audio_base64, save_prompt_audio_bytes, validate_reference_audio_duration
from ..security import _extract_bearer_token, verify_ws_key
from ..service_state import ServiceState

logger = logging.getLogger(__name__)


class WebSocketPayloadTooLarge(ValueError):
    """Raised when an inbound WebSocket JSON message exceeds configured limits."""


class WebSocketPayloadInvalid(ValueError):
    """Raised when an inbound WebSocket frame is not a JSON object."""


class WsSessionState(str, Enum):
    CREATED = "created"
    ACCEPTED = "accepted"
    AUTHENTICATED = "authenticated"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    DONE = "done"
    ERROR = "error"


class TtsWebSocketSession:
    """单次 WebSocket 请求会话。

    路由层保持精简；解析、校验、生产者生命周期和取消处理
    都在此类中，避免未来新功能不断膨胀单个 ws_tts 函数。
    """

    def __init__(self, *, websocket: WebSocket, state: ServiceState):
        self.websocket = websocket
        self.state = state
        self.cfg = state.cfg
        self.request_id = state.new_request_id()
        self.prompt_audio_path: str | None = None
        self.prompt_audio_id = ""
        self.producer_task: asyncio.Task | None = None
        self.control_task: asyncio.Task | None = None
        self.cancel_event = threading.Event()
        self.cancelled_by_client = False
        self.cancel_notified = False
        self.saw_stream_error = False
        self.stream_error_counted = False
        self.done_marker = object()
        self.queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=4)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.phase = WsSessionState.CREATED

    def _transition(self, phase: WsSessionState, **extra) -> None:
        self.phase = phase
        logger.debug("WS state -> %s", phase.value, extra={"request_id": self.request_id, "phase": phase.value, **extra})

    async def _receive_json_limited(self) -> dict:
        """Read a JSON object while enforcing a per-message allocation budget.

        ``run_server`` also forwards this limit to Uvicorn as ``ws_max_size`` so
        normal deployments reject large frames before decoding. This route-level
        guard remains effective under TestClient or alternative ASGI launchers.
        """
        frame = await self.websocket.receive()
        if frame.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(code=int(frame.get("code") or 1000))
        raw = frame.get("text")
        if raw is None:
            raw_bytes = frame.get("bytes") or b""
        else:
            raw_bytes = str(raw).encode("utf-8")
        limit = max(1024, int(getattr(self.cfg, "websocket_max_message_bytes", 32 * 1024 * 1024) or 32 * 1024 * 1024))
        if len(raw_bytes) > limit:
            raise WebSocketPayloadTooLarge(f"WebSocket message exceeds {limit} bytes")
        try:
            value = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSocketPayloadInvalid("WebSocket message must be a JSON object") from exc
        if not isinstance(value, dict):
            raise WebSocketPayloadInvalid("WebSocket message must be a JSON object")
        return value

    async def run(self) -> None:
        # New clients can authenticate during the handshake through Authorization
        # or ?token=, allowing invalid connections to be refused before accept.
        # The first-message token remains supported for existing Studio clients.
        preauth_token = str(self.websocket.query_params.get("token", "") or "")
        auth_header = self.websocket.headers.get("authorization", "")
        bearer_token = _extract_bearer_token(auth_header)
        has_preauth = bool(preauth_token or bearer_token)
        if has_preauth and not await verify_ws_key(self.cfg, self.websocket, token=preauth_token):
            with suppress(Exception):
                await self.websocket.close(code=1008, reason="authentication failed")
            return
        await self.websocket.accept()
        self._transition(WsSessionState.ACCEPTED)
        try:
            handshake_timeout = min(15.0, max(1.0, float(getattr(self.cfg, "request_timeout_seconds", 300.0) or 300.0)))
            msg = await asyncio.wait_for(self._receive_json_limited(), timeout=handshake_timeout)
            if has_preauth and not msg.get("token"):
                msg["token"] = preauth_token
            params = await self._parse_and_validate_first_message(msg)
            if params is None:
                return
            await self._stream(params)
        except WebSocketPayloadTooLarge:
            self._transition(WsSessionState.ERROR, reason="message-too-large")
            self.state.inc_stat("requests_error")
            self.state.finish_request(self.request_id, "error", error="WebSocket 请求过大")
            with suppress(Exception):
                await self.websocket.send_json({"type": "error", "message": "WebSocket 请求内容过大", "request_id": self.request_id})
                await self.websocket.close(code=1009, reason="message too large")
        except WebSocketPayloadInvalid:
            self._transition(WsSessionState.ERROR, reason="invalid-json")
            self.state.inc_stat("requests_error")
            self.state.finish_request(self.request_id, "error", error="WebSocket JSON 无效")
            with suppress(Exception):
                await self.websocket.send_json({"type": "error", "message": "WebSocket 请求格式无效", "request_id": self.request_id})
                await self.websocket.close(code=1003, reason="invalid JSON")
        except asyncio.TimeoutError:
            self._transition(WsSessionState.ERROR, reason="timeout")
            self.state.inc_stat("requests_error")
            self.state.finish_request(self.request_id, "timeout")
            with suppress(Exception):
                await self.websocket.send_json({"type": "error", "message": "WebSocket 请求超时", "request_id": self.request_id})
        except WebSocketDisconnect as exc:
            self._transition(WsSessionState.CANCELLING, reason="disconnect-before-payload")
            self.state.request_cancel(self.request_id)
            self.state.finish_request(self.request_id, "cancelled")
            logger.info("WebSocket 客户端在提交首个请求前断开连接", extra={"request_id": self.request_id, "code": exc.code})
        except Exception:
            self._transition(WsSessionState.ERROR, reason="exception")
            self.state.inc_stat("requests_error")
            self.state.finish_request(self.request_id, "error")
            logger.exception("WebSocket 流式合成失败", extra={"request_id": self.request_id})
            with suppress(Exception):
                await self.websocket.send_json({"type": "error", "message": "流式合成失败", "request_id": self.request_id})
        finally:
            if self.prompt_audio_path:
                with suppress(OSError):
                    Path(self.prompt_audio_path).unlink()
            with suppress(Exception):
                await self.websocket.close()

    async def _parse_and_validate_first_message(self, msg: dict) -> StreamingRequest | None:
        token = msg.get("token", "")
        if not await verify_ws_key(self.cfg, self.websocket, token=token):
            await self.websocket.send_json({"type": "error", "message": "认证失败，请检查 API Key", "request_id": self.request_id})
            return None
        self._transition(WsSessionState.AUTHENTICATED)
        if not self.cfg.stream_enabled:
            await self.websocket.send_json({"type": "error", "message": "流式合成未启用", "request_id": self.request_id})
            return None

        try:
            model = self.state.model_manager.normalize_model_id(msg.get("model"))
            target_engine = self.state.model_manager.get_engine(model, load=False)
            voice = msg.get("voice") or getattr(target_engine, "default_voice", self.cfg.default_voice)
            fmt = msg.get("format", self.cfg.stream_format)
            binary = bool(msg.get("binary", False)) and self.cfg.stream_binary_enabled

            prompt_payload = msg.get("prompt_audio") if isinstance(msg.get("prompt_audio"), dict) else {}
            prompt_audio_data = (
                (prompt_payload or {}).get("data")
                or msg.get("prompt_audio_data")
                or msg.get("reference_audio_data")
            )
            if prompt_audio_data:
                if not self.state.engine_supports_voice_clone(target_engine):
                    await self.websocket.send_json({"type": "error", "message": "当前模型不支持参考音频克隆", "request_id": self.request_id})
                    return None
                max_prompt_bytes = self.state.voice_profiles.upload_limit_bytes(model)
                self.prompt_audio_path, self.prompt_audio_id = save_prompt_audio_bytes(
                    content=decode_prompt_audio_base64(str(prompt_audio_data), max_bytes=max_prompt_bytes),
                    filename=str((prompt_payload or {}).get("filename") or msg.get("prompt_audio_filename") or "prompt.wav"),
                    request_id=self.request_id,
                    max_bytes=max_prompt_bytes,
                )
                if self.prompt_audio_path and model == "zipvoice":
                    validate_reference_audio_duration(
                        self.prompt_audio_path, max_seconds=self.state.voice_profiles.reference_max_seconds(model)
                    )

            supplied = msg.get("engine_params") if isinstance(msg.get("engine_params"), dict) else {}
            return self.state.streaming.build_request(
                text=msg.get("text", ""), model_id=model, voice=voice,
                speed=msg.get("speed", self.cfg.default_speed), audio_format=fmt, binary=binary,
                prompt_audio_path=self.prompt_audio_path, prompt_audio_id=self.prompt_audio_id,
                prompt_text=str(msg.get("prompt_text") or "").strip(),
                engine_params=supplied, parameter_source=msg, request_id=self.request_id,
            )
        except HTTPException as exc:
            await self.websocket.send_json({"type": "error", "message": str(exc.detail), "request_id": self.request_id})
            return None
        except OSError:
            logger.exception("WebSocket 参考音频或请求资源处理失败", extra={"request_id": self.request_id})
            await self.websocket.send_json({"type": "error", "message": "参考音频处理失败", "request_id": self.request_id})
            return None

    async def _stream(self, request: StreamingRequest) -> None:
        self.loop = asyncio.get_running_loop()
        self.state.inc_stat("requests_total")
        self.state.inc_stat("characters_total", len(request.text or ""))
        start = time.perf_counter()
        self._transition(WsSessionState.QUEUED, model=request.model_id)
        self.state.mark_request(
            self.request_id,
            "queued",
            voice=request.voice,
            format=request.audio_format,
            model=request.model_id,
            chars=len(request.text or ""),
            websocket=True,
            voice_clone=request.condition.is_reference_conditioned,
            prompt_audio_id=request.condition.prompt_audio_id,
            profile_revision=request.condition.revision,
            voice_condition=request.condition.as_dict(),
        )

        async with self.state.tts_semaphore:
            self._transition(WsSessionState.RUNNING, model=request.model_id)
            self.state.mark_request(self.request_id, "running")
            self.control_task = asyncio.create_task(self._control_listener())
            self.producer_task = asyncio.create_task(asyncio.to_thread(self._producer, request))
            try:
                await self._send_loop(binary=request.binary)
            finally:
                await self._cancel_background_tasks()

        self._finish(start)

    async def _drain_queue(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _notify_cancelled(self) -> None:
        if self.cancel_notified:
            return
        self.cancel_notified = True
        await self._drain_queue()
        await self.queue.put({"type": "cancelled", "request_id": self.request_id})
        await self.queue.put(self.done_marker)

    async def _control_listener(self) -> None:
        while not self.cancel_event.is_set():
            try:
                control_msg = await self._receive_json_limited()
            except WebSocketDisconnect:
                await self._mark_client_cancelled()
                break
            except (WebSocketPayloadTooLarge, WebSocketPayloadInvalid):
                logger.warning("WebSocket 控制消息无效或过大", extra={"request_id": self.request_id})
                await self._mark_client_cancelled()
                break
            except Exception:
                logger.debug("WebSocket 控制消息监听异常", exc_info=True, extra={"request_id": self.request_id})
                break
            msg_type = str(control_msg.get("type", "")).lower()
            if msg_type in {"cancel", "stop"}:
                await self._mark_client_cancelled()
                break

    async def _mark_client_cancelled(self) -> None:
        self._transition(WsSessionState.CANCELLING, reason="client")
        self.state.request_cancel(self.request_id)
        self.cancel_event.set()
        self.cancelled_by_client = True
        await self._notify_cancelled()

    def _thread_put(self, item) -> bool:
        """Put a producer frame without letting a stalled consumer pin a worker forever."""
        assert self.loop is not None
        queue_wait_limit = min(max(float(getattr(self.cfg, "request_timeout_seconds", 30) or 30), 1.0), 30.0)
        deadline = time.monotonic() + queue_wait_limit
        while not self.cancel_event.is_set() and not self.state.is_cancelled(self.request_id):
            if time.monotonic() >= deadline:
                logger.warning("WebSocket 发送队列持续阻塞，终止生产任务", extra={"request_id": self.request_id})
                return False
            if self.loop.is_closed():
                return False
            pending_put = self.queue.put(item)
            try:
                fut = asyncio.run_coroutine_threadsafe(pending_put, self.loop)
            except RuntimeError:
                pending_put.close()
                return False
            try:
                fut.result(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
                return True
            except TimeoutError:
                fut.cancel()
                continue
            except Exception:
                fut.cancel()
                return False
        return False

    def _producer(self, request: StreamingRequest) -> None:
        try:
            cancel_check = lambda: self.cancel_event.is_set() or self.state.is_cancelled(self.request_id)
            for chunk in self.state.streaming.iter_frames(request, cancel_check=cancel_check):
                if cancel_check():
                    break
                if not self._thread_put(chunk):
                    break
        except Exception:
            logger.exception("WebSocket 音频生产任务失败", extra={"request_id": self.request_id})
            if not self.cancel_event.is_set():
                with suppress(Exception):
                    self._thread_put({"type": "error", "message": "流式合成失败", "request_id": self.request_id})
        finally:
            if self.loop is not None:
                if self.cancel_event.is_set() or self.state.is_cancelled(self.request_id):
                    # Create the coroutine inside the loop callback only after the callback
                    # has actually been accepted. This avoids leaking an un-awaited
                    # coroutine when the event loop closes between producer shutdown
                    # and call_soon_threadsafe().
                    if not self.loop.is_closed():
                        with suppress(RuntimeError):
                            self.loop.call_soon_threadsafe(self._schedule_cancelled_notice)
                else:
                    with suppress(Exception):
                        self._thread_put(self.done_marker)

    def _schedule_cancelled_notice(self) -> None:
        """Notify cancellation from the event-loop thread without pre-creating a coroutine."""
        asyncio.create_task(self._notify_cancelled())

    def _record_stream_error(self, message: str) -> None:
        """Record one terminal stream error per request, even if multiple frames are malformed."""
        self._transition(WsSessionState.ERROR, reason="stream-error-frame")
        self.saw_stream_error = True
        if not self.stream_error_counted:
            self.state.inc_stat("requests_error")
            self.stream_error_counted = True
        self.state.mark_request(self.request_id, "error", error=message)

    async def _send_loop(self, *, binary: bool) -> None:
        while True:
            chunk = await asyncio.wait_for(self.queue.get(), timeout=self.cfg.request_timeout_seconds)
            if chunk is self.done_marker:
                break
            if isinstance(chunk, dict):
                chunk.setdefault("request_id", self.request_id)
                if chunk.get("type") in {"error", "segment_error"}:
                    self._record_stream_error("流式引擎返回错误帧")
            try:
                if binary and isinstance(chunk, dict) and chunk.get("type") == "audio":
                    payload = chunk.get("data")
                    if not isinstance(payload, str) or not payload:
                        logger.error("WebSocket 音频帧缺少 data 字段", extra={"request_id": self.request_id})
                        self._record_stream_error("音频帧缺少 data")
                        await self.websocket.send_json({
                            "type": "error",
                            "message": "流式音频帧无效",
                            "request_id": self.request_id,
                        })
                        break
                    try:
                        audio_payload = base64.b64decode(payload, validate=True)
                    except (binascii.Error, ValueError):
                        logger.error("WebSocket 音频帧 base64 无效", extra={"request_id": self.request_id})
                        self._record_stream_error("音频帧编码无效")
                        await self.websocket.send_json({
                            "type": "error",
                            "message": "流式音频帧无效",
                            "request_id": self.request_id,
                        })
                        break
                    await self.websocket.send_json({k: v for k, v in chunk.items() if k != "data"})
                    await self.websocket.send_bytes(audio_payload)
                else:
                    await self.websocket.send_json(chunk)
            except Exception:
                self._transition(WsSessionState.CANCELLING, reason="send-failed")
                self.state.request_cancel(self.request_id)
                self.cancel_event.set()
                self.cancelled_by_client = True
                logger.info("WebSocket 客户端在音频发送过程中断开连接", extra={"request_id": self.request_id})
                break
            if isinstance(chunk, dict) and chunk.get("type") == "cancelled":
                break

    async def _cancel_background_tasks(self) -> None:
        self.cancel_event.set()
        if self.control_task:
            self.control_task.cancel()
        if self.producer_task:
            try:
                await asyncio.wait_for(self.producer_task, timeout=5.0)
            except asyncio.TimeoutError:
                self.producer_task.cancel()
                logger.warning("WebSocket 音频生产任务未在取消宽限时间内退出", extra={"request_id": self.request_id})
            except asyncio.CancelledError:
                pass

    def _finish(self, start: float) -> None:
        elapsed = time.perf_counter() - start
        if self.cancelled_by_client or self.state.is_cancelled(self.request_id):
            self._transition(WsSessionState.CANCELLING, reason="finish-cancelled")
            self.state.finish_request(self.request_id, "cancelled", elapsed_seconds=round(elapsed, 3))
        elif self.saw_stream_error:
            self._transition(WsSessionState.ERROR, reason="finish-error")
            if not self.stream_error_counted:
                self.state.inc_stat("requests_error")
            self.state.finish_request(self.request_id, "error", elapsed_seconds=round(elapsed, 3), error="流式引擎返回错误帧")
        else:
            self._transition(WsSessionState.DONE)
            self.state.inc_stat("requests_ok")
            self.state.inc_stat("synthesis_seconds_total", elapsed)
            self.state.finish_request(self.request_id, "done", elapsed_seconds=round(elapsed, 3))


def create_ws_router(state: ServiceState) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/v1/tts")
    async def ws_tts(websocket: WebSocket):
        if not await state.try_acquire_websocket_connection():
            with suppress(Exception):
                await websocket.close(code=1013, reason="WebSocket connection capacity reached")
            return
        try:
            await TtsWebSocketSession(websocket=websocket, state=state).run()
        finally:
            await state.release_websocket_connection()

    return router
