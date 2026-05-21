"""WebSocket 流式合成路由。"""

from __future__ import annotations

import asyncio
import base64
import inspect
import logging
import time
from contextlib import suppress
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..prompt_audio import decode_prompt_audio_base64, save_prompt_audio_bytes
from ..security import verify_ws_key
from ..service_state import ServiceState
from ..validation import validate_model_speed, validate_tts_text

logger = logging.getLogger(__name__)


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
        self.cancel_flag = {"cancelled": False, "by_client": False, "notified": False}
        self.saw_stream_error = False
        self.stream_error_counted = False
        self.done_marker = object()
        self.queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=4)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.phase = WsSessionState.CREATED

    def _transition(self, phase: WsSessionState, **extra) -> None:
        self.phase = phase
        logger.debug("WS state -> %s", phase.value, extra={"request_id": self.request_id, "phase": phase.value, **extra})

    async def run(self) -> None:
        await self.websocket.accept()
        self._transition(WsSessionState.ACCEPTED)
        try:
            msg = await self.websocket.receive_json()
            params = await self._parse_and_validate_first_message(msg)
            if params is None:
                return
            await self._stream(params)
        except asyncio.TimeoutError:
            self._transition(WsSessionState.ERROR, reason="timeout")
            self.state.inc_stat("requests_error")
            self.state.finish_request(self.request_id, "timeout")
            with suppress(Exception):
                await self.websocket.send_json({"type": "error", "message": "合成超时", "request_id": self.request_id})
        except WebSocketDisconnect as exc:
            self._transition(WsSessionState.CANCELLING, reason="disconnect-before-payload")
            self.state.request_cancel(self.request_id)
            self.state.finish_request(self.request_id, "cancelled")
            logger.info("WS client disconnected before first request payload", extra={"request_id": self.request_id, "code": exc.code})
        except Exception:
            self._transition(WsSessionState.ERROR, reason="exception")
            self.state.inc_stat("requests_error")
            self.state.finish_request(self.request_id, "error")
            logger.exception("WS TTS failed", extra={"request_id": self.request_id})
            with suppress(Exception):
                await self.websocket.send_json({"type": "error", "message": "流式合成失败", "request_id": self.request_id})
        finally:
            if self.prompt_audio_path:
                with suppress(OSError):
                    Path(self.prompt_audio_path).unlink()
            with suppress(Exception):
                await self.websocket.close()

    async def _parse_and_validate_first_message(self, msg: dict) -> dict | None:
        token = msg.get("token", "")
        if not await verify_ws_key(self.cfg, self.websocket, token=token):
            await self.websocket.send_json({"type": "error", "message": "Unauthorized", "request_id": self.request_id})
            return None
        self._transition(WsSessionState.AUTHENTICATED)
        if not self.cfg.stream_enabled:
            await self.websocket.send_json({"type": "error", "message": "流式合成未启用", "request_id": self.request_id})
            return None

        try:
            text = validate_tts_text(msg.get("text", ""), self.cfg)
            model = self.state.model_manager.normalize_model_id(msg.get("model"))
            speed = validate_model_speed(model, msg.get("speed", self.cfg.default_speed))
        except HTTPException as exc:
            await self.websocket.send_json({"type": "error", "message": str(exc.detail), "request_id": self.request_id})
            return None

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
            try:
                self.prompt_audio_path, self.prompt_audio_id = save_prompt_audio_bytes(
                    content=decode_prompt_audio_base64(str(prompt_audio_data)),
                    filename=str((prompt_payload or {}).get("filename") or msg.get("prompt_audio_filename") or "prompt.wav"),
                    request_id=self.request_id,
                    max_bytes=self.cfg.moss_prompt_upload_max_bytes,
                )
            except HTTPException as exc:
                await self.websocket.send_json({"type": "error", "message": str(exc.detail), "request_id": self.request_id})
                return None

        return {"text": text, "model": model, "voice": voice, "speed": speed, "fmt": fmt, "binary": binary}

    async def _stream(self, params: dict) -> None:
        self.loop = asyncio.get_running_loop()
        self.state.inc_stat("requests_total")
        self.state.inc_stat("characters_total", len(params["text"] or ""))
        start = time.perf_counter()
        self._transition(WsSessionState.QUEUED, model=params["model"])
        self.state.mark_request(
            self.request_id,
            "queued",
            voice=params["voice"],
            format=params["fmt"],
            model=params["model"],
            chars=len(params["text"] or ""),
            websocket=True,
            voice_clone=bool(self.prompt_audio_path),
            prompt_audio_id=self.prompt_audio_id,
        )

        async with self.state.tts_semaphore:
            self._transition(WsSessionState.RUNNING, model=params["model"])
            self.state.mark_request(self.request_id, "running")
            self.control_task = asyncio.create_task(self._control_listener())
            self.producer_task = asyncio.create_task(asyncio.to_thread(self._producer, params))
            try:
                await self._send_loop(binary=params["binary"])
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
        if self.cancel_flag["notified"]:
            return
        self.cancel_flag["notified"] = True
        await self._drain_queue()
        await self.queue.put({"type": "cancelled", "request_id": self.request_id})
        await self.queue.put(self.done_marker)

    async def _control_listener(self) -> None:
        while not self.cancel_flag["cancelled"]:
            try:
                control_msg = await self.websocket.receive_json()
            except WebSocketDisconnect:
                await self._mark_client_cancelled()
                break
            except Exception:
                logger.debug("WS control listener error", exc_info=True, extra={"request_id": self.request_id})
                break
            msg_type = str(control_msg.get("type", "")).lower()
            if msg_type in {"cancel", "stop"}:
                await self._mark_client_cancelled()
                break

    async def _mark_client_cancelled(self) -> None:
        self._transition(WsSessionState.CANCELLING, reason="client")
        self.state.request_cancel(self.request_id)
        self.cancel_flag["cancelled"] = True
        self.cancel_flag["by_client"] = True
        await self._notify_cancelled()

    def _thread_put(self, item) -> bool:
        assert self.loop is not None
        while not self.cancel_flag["cancelled"] and not self.state.is_cancelled(self.request_id):
            fut = asyncio.run_coroutine_threadsafe(self.queue.put(item), self.loop)
            try:
                fut.result(timeout=0.5)
                return True
            except TimeoutError:
                fut.cancel()
                continue
            except Exception:
                fut.cancel()
                return False
        return False

    def _producer(self, params: dict) -> None:
        try:
            with self.state.model_manager.borrow(params["model"]) as eng:
                prompt_kwargs = {"prompt_audio_path": self.prompt_audio_path} if self.prompt_audio_path else {}
                try:
                    stream_params = inspect.signature(eng.synthesize_stream).parameters
                except (TypeError, ValueError):
                    stream_params = {}
                if "cancel_check" in stream_params:
                    prompt_kwargs["cancel_check"] = lambda: self.cancel_flag["cancelled"] or self.state.is_cancelled(self.request_id)
                for chunk in eng.synthesize_stream(params["text"], params["voice"], params["speed"], params["fmt"], **prompt_kwargs):
                    if self.cancel_flag["cancelled"] or self.state.is_cancelled(self.request_id):
                        break
                    if isinstance(chunk, dict):
                        chunk.setdefault("model", params["model"])
                    if not self._thread_put(chunk):
                        break
        except Exception:
            logger.exception("WS TTS producer failed", extra={"request_id": self.request_id})
            if not self.cancel_flag["cancelled"]:
                with suppress(Exception):
                    self._thread_put({"type": "error", "message": "流式合成失败", "request_id": self.request_id})
        finally:
            if self.loop is not None:
                if self.cancel_flag["cancelled"] or self.state.is_cancelled(self.request_id):
                    self.loop.call_soon_threadsafe(asyncio.create_task, self._notify_cancelled())
                else:
                    with suppress(Exception):
                        self._thread_put(self.done_marker)

    async def _send_loop(self, *, binary: bool) -> None:
        while True:
            chunk = await asyncio.wait_for(self.queue.get(), timeout=self.cfg.request_timeout_seconds)
            if chunk is self.done_marker:
                break
            if isinstance(chunk, dict):
                chunk.setdefault("request_id", self.request_id)
                if chunk.get("type") in {"error", "segment_error"}:
                    self._transition(WsSessionState.ERROR, reason="stream-error-frame")
                    self.saw_stream_error = True
                    if not self.stream_error_counted:
                        self.state.inc_stat("requests_error")
                        self.stream_error_counted = True
                        self.state.mark_request(self.request_id, "error", error="stream returned error frame")
            try:
                if binary and isinstance(chunk, dict) and chunk.get("type") == "audio":
                    await self.websocket.send_json({k: v for k, v in chunk.items() if k != "data"})
                    await self.websocket.send_bytes(base64.b64decode(chunk["data"]))
                else:
                    await self.websocket.send_json(chunk)
            except Exception:
                self._transition(WsSessionState.CANCELLING, reason="send-failed")
                self.state.request_cancel(self.request_id)
                self.cancel_flag["cancelled"] = True
                self.cancel_flag["by_client"] = True
                logger.info("WS client disconnected while sending audio", extra={"request_id": self.request_id})
                break
            if isinstance(chunk, dict) and chunk.get("type") == "cancelled":
                break

    async def _cancel_background_tasks(self) -> None:
        self.cancel_flag["cancelled"] = True
        if self.control_task:
            self.control_task.cancel()
        if self.producer_task:
            try:
                await asyncio.wait_for(self.producer_task, timeout=5.0)
            except asyncio.TimeoutError:
                self.producer_task.cancel()
                logger.warning("WS producer did not exit within cancellation grace window", extra={"request_id": self.request_id})
            except asyncio.CancelledError:
                pass

    def _finish(self, start: float) -> None:
        elapsed = time.perf_counter() - start
        if self.cancel_flag["by_client"] or self.state.is_cancelled(self.request_id):
            self._transition(WsSessionState.CANCELLING, reason="finish-cancelled")
            self.state.finish_request(self.request_id, "cancelled", elapsed_seconds=round(elapsed, 3))
        elif self.saw_stream_error:
            self._transition(WsSessionState.ERROR, reason="finish-error")
            if not self.stream_error_counted:
                self.state.inc_stat("requests_error")
            self.state.finish_request(self.request_id, "error", elapsed_seconds=round(elapsed, 3), error="stream returned error frame")
        else:
            self._transition(WsSessionState.DONE)
            self.state.inc_stat("requests_ok")
            self.state.inc_stat("synthesis_seconds_total", elapsed)
            self.state.finish_request(self.request_id, "done", elapsed_seconds=round(elapsed, 3))


def create_ws_router(state: ServiceState) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/v1/tts")
    async def ws_tts(websocket: WebSocket):
        await TtsWebSocketSession(websocket=websocket, state=state).run()

    return router
