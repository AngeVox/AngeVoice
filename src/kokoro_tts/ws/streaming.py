"""Streaming producer and sender helpers for WebSocket TTS."""

from __future__ import annotations

import asyncio
import base64
import binascii
import concurrent.futures
import logging
import time
from contextlib import suppress

from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect

from ..validation import websocket_error_frame_from_http
from .errors import WebSocketPayloadInvalid, WebSocketPayloadTooLarge
from .state import WsSessionState

logger = logging.getLogger("kokoro_tts.routes.ws")


class StreamingLoopMixin:
    """Producer thread, control listener and outbound send loop."""

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

    def _thread_put(self, item) -> bool:
        """放入生产者帧，不让停滞的消费者永久占用 worker。"""
        assert self.loop is not None
        request_timeout = float(getattr(self.cfg, "request_timeout_seconds", 300) or 300)
        stream_timeout = float(getattr(self.cfg, "websocket_stream_idle_timeout_seconds", request_timeout) or request_timeout)
        process_stream_timeout = float(
            getattr(self.cfg, "engine_process_stream_idle_timeout_seconds", stream_timeout) or stream_timeout
        )
        queue_wait_limit = min(max(60.0, request_timeout, stream_timeout, process_stream_timeout, 1800.0), 3600.0)
        deadline = time.monotonic() + queue_wait_limit
        last_error = ""
        while not self.cancel_event.is_set() and not self.state.is_cancelled(self.request_id):
            if time.monotonic() >= deadline:
                if last_error:
                    logger.warning(
                        "WebSocket 发送队列写入持续失败：%s",
                        last_error,
                        extra={"request_id": self.request_id},
                    )
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
            except concurrent.futures.CancelledError:
                continue
            except Exception as exc:
                last_error = repr(exc)
                fut.cancel()
                time.sleep(0.01)
                continue
        return False

    def _producer(self, request: StreamingRequest) -> None:
        produced_terminal = False
        produced_count = 0
        last_chunk_type = ""
        try:
            cancel_check = lambda: self.cancel_event.is_set() or self.state.is_cancelled(self.request_id)
            for chunk in self.state.streaming.iter_frames(request, cancel_check=cancel_check):
                if isinstance(chunk, dict):
                    last_chunk_type = str(chunk.get("type") or "")
                    if last_chunk_type in {"done", "cancelled", "error", "segment_error"}:
                        produced_terminal = True
                produced_count += 1
                if cancel_check():
                    # 用户停止后继续消费底层迭代器，让隔离 worker 在软取消后
                    # 收到 done 并释放请求锁；取消后的旧音频不再推给前端。
                    continue
                if not self._thread_put(chunk):
                    if cancel_check():
                        continue
                    logger.warning(
                        "WebSocket 发送队列写入失败，生产任务提前结束（frames=%d, last=%s）",
                        produced_count,
                        last_chunk_type,
                        extra={"request_id": self.request_id},
                    )
                    break
        except HTTPException as exc:
            logger.warning("WebSocket 音频生产任务返回参数错误", extra={"request_id": self.request_id})
            if not self.cancel_event.is_set():
                with suppress(Exception):
                    self._thread_put(websocket_error_frame_from_http(exc, request_id=self.request_id))
        except Exception:
            logger.exception("WebSocket 音频生产任务失败", extra={"request_id": self.request_id})
            if not self.cancel_event.is_set():
                with suppress(Exception):
                    self._thread_put({"type": "error", "message": "流式合成失败", "request_id": self.request_id})
        finally:
            if not produced_terminal and not self.cancel_event.is_set() and not self.state.is_cancelled(self.request_id):
                logger.warning(
                    "WebSocket 生产任务结束但未收到终止帧（frames=%d, last=%s）",
                    produced_count,
                    last_chunk_type,
                    extra={"request_id": self.request_id},
                )
            if self.loop is not None:
                if self.cancel_event.is_set() or self.state.is_cancelled(self.request_id):
                    # 仅在回调被实际接受后才在循环回调内创建协程。
                    # 这避免了在生产者关闭和 call_soon_threadsafe() 之间
                    # 事件循环关闭时泄漏未等待的协程。
                    if not self.loop.is_closed():
                        with suppress(RuntimeError):
                            self.loop.call_soon_threadsafe(self._schedule_cancelled_notice)
                else:
                    with suppress(Exception):
                        self._thread_put(self.done_marker)

    def _record_stream_error(self, message: str) -> None:
        """记录每个请求的一个终止流错误，即使多个帧格式错误。"""
        self._transition(WsSessionState.ERROR, reason="stream-error-frame")
        self.saw_stream_error = True
        self.saw_stream_terminal = True
        if not self.stream_error_counted:
            self.state.inc_stat("requests_error")
            self.stream_error_counted = True
        self.state.mark_request(self.request_id, "error", error=message)

    def _stream_idle_timeout(self) -> float:
        """返回等待下一帧流式事件的空闲超时。"""
        request_timeout = float(getattr(self.cfg, "request_timeout_seconds", 300.0) or 300.0)
        stream_timeout = float(getattr(self.cfg, "websocket_stream_idle_timeout_seconds", 120.0) or 120.0)
        return max(5.0, request_timeout, stream_timeout)

    async def _send_waiting_notice(self, *, elapsed: float) -> bool:
        """模型暂时没有输出时发送轻量进度帧，避免连接被误判空闲。"""
        try:
            await self.websocket.send_json({
                "type": "progress",
                "stage": "waiting_audio",
                "message": "模型正在生成音频，请稍候",
                "elapsed_seconds": round(float(elapsed), 1),
                "request_id": self.request_id,
            })
            return True
        except Exception:
            self._transition(WsSessionState.CANCELLING, reason="send-progress-failed")
            self.state.request_cancel(self.request_id)
            self.cancel_event.set()
            self.cancelled_by_client = True
            logger.info("WebSocket 客户端在等待音频时断开连接", extra={"request_id": self.request_id})
            return False

    async def _send_loop(self, *, binary: bool) -> None:
        idle_timeout = self._stream_idle_timeout()
        last_model_event = time.monotonic()
        last_notice = 0.0
        poll_interval = 1.0
        notice_interval = 2.0
        while True:
            try:
                chunk = await asyncio.wait_for(self.queue.get(), timeout=poll_interval)
            except asyncio.TimeoutError:
                now = time.monotonic()
                idle_for = now - last_model_event
                if idle_for >= idle_timeout:
                    message = f"流式合成等待音频超时（{idle_timeout:.0f}s）"
                    self._record_stream_error(message)
                    with suppress(Exception):
                        await self.websocket.send_json({"type": "error", "message": message, "request_id": self.request_id})
                    break
                if now - last_notice >= notice_interval:
                    last_notice = now
                    if not await self._send_waiting_notice(elapsed=idle_for):
                        break
                continue
            last_model_event = time.monotonic()
            if chunk is self.done_marker:
                if (
                    not self.saw_stream_terminal
                    and not self.cancel_event.is_set()
                    and not self.state.is_cancelled(self.request_id)
                ):
                    message = "流式合成提前结束，未收到完成帧"
                    self._record_stream_error(message)
                    with suppress(Exception):
                        await self.websocket.send_json({"type": "error", "message": message, "request_id": self.request_id})
                break
            if isinstance(chunk, dict):
                chunk.setdefault("request_id", self.request_id)
                chunk_type = str(chunk.get("type") or "")
                if chunk_type == "done":
                    self.saw_stream_terminal = True
                elif chunk_type == "cancelled":
                    self.saw_stream_terminal = True
                elif chunk_type in {"error", "segment_error"}:
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
