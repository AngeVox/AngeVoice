"""Cancellation and cleanup helpers for WebSocket sessions."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

from .state import WsSessionState

logger = logging.getLogger("kokoro_tts.routes.ws")


class CancelLifecycleMixin:
    """Stop/cancel/disconnect cleanup behavior shared by TTS sessions."""

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

    async def _mark_client_cancelled(self) -> None:
        if self.saw_stream_terminal:
            logger.debug("WebSocket 终止帧后收到断开，按正常收尾处理", extra={"request_id": self.request_id})
            return
        self._transition(WsSessionState.CANCELLING, reason="client")
        self.state.request_cancel(self.request_id)
        self.cancel_event.set()
        self.cancelled_by_client = True
        await self._notify_cancelled()

    def _schedule_cancelled_notice(self) -> None:
        """从事件循环线程通知取消，无需预先创建协程。"""
        asyncio.create_task(self._notify_cancelled())

    async def _cancel_background_tasks(self) -> None:
        normal_terminal = self.saw_stream_terminal and not self.cancelled_by_client and not self.state.is_cancelled(self.request_id)
        if not normal_terminal:
            self.cancel_event.set()
        if self.control_task:
            self.control_task.cancel()
        if self.producer_task:
            try:
                await asyncio.wait_for(self.producer_task, timeout=5.0)
            except asyncio.TimeoutError:
                self.cancel_event.set()
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
