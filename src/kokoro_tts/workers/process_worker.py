"""可杀死的 Kokoro 和 ZipVoice 运行时 worker 进程。

API 进程负责路由、持久化配置档案元数据和配置。重量级推理运行时在
生成的子进程中构建，空闲/模型释放时操作系统可可靠回收 CPU RSS 和 GPU 内存。
"""

from __future__ import annotations

from contextlib import suppress
import multiprocessing as mp
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Callable, Iterator

from .factories import create_worker_engine, supported_worker_engines


@dataclass(frozen=True)
class WorkerResult:
    request_id: str
    kind: str
    payload: object


class EngineProcessTimeoutError(TimeoutError):
    """模型 worker 在请求截止时间前停止产生结果。"""


class EngineProcessClient:
    """为推理运行时懒启动的单次执行子进程。"""

    def __init__(self, *, config, engine_id: str, requested_provider: str | None = None, logger=None):
        if engine_id not in supported_worker_engines():
            raise ValueError(f"Unsupported generic worker engine: {engine_id}")
        self.config = config
        self.engine_id = engine_id
        self.requested_provider = requested_provider
        self.logger = logger
        self._ctx = mp.get_context("spawn")
        self._command_queue = None
        self._result_queue = None
        self._process: mp.Process | None = None
        self._lifecycle_lock = threading.RLock()
        # 已加载的运行时是有意设计为单次执行的。序列化所有队列
        # 消费者可防止同时的 HTTP/WebSocket 调用者互相抢消息
        # 导致伪超时。
        self._request_lock = threading.RLock()
        self._loaded = False
        self._last_metadata: dict = {}
        self._unhealthy = False
        self._last_exit_reason = ""
        # 共享内存标志：主进程置 1 通知 worker 子进程放弃当前 synthesize_stream，
        # 但不杀进程。worker 在每次新命令开始时重置为 0。
        self._cancel_flag = self._ctx.Value("b", 0)

    @property
    def alive(self) -> bool:
        process = self._process
        return bool(process is not None and process.is_alive())

    @property
    def pid(self) -> int | None:
        return self._process.pid if self.alive and self._process is not None else None

    @property
    def is_loaded(self) -> bool:
        return bool(self.alive and self._loaded)

    @property
    def last_metadata(self) -> dict:
        return dict(self._last_metadata)

    @property
    def is_healthy(self) -> bool:
        """空闲 worker 是健康的；崩溃的已加载 worker 不健康。"""

        process = self._process
        if self._unhealthy:
            return False
        if self._loaded and process is not None and not process.is_alive():
            return False
        return True

    @property
    def last_exit_reason(self) -> str:
        return self._last_exit_reason

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.alive:
                return
            # 被杀死的 worker 可能残留未消费的命令/结果。新队列
            # 让下次唤醒成为一次干净的运行时代次。
            self._command_queue = self._ctx.Queue()
            self._result_queue = self._ctx.Queue()
            self._loaded = False
            # 启动新 worker 进程时重置取消标志。
            try:
                self._cancel_flag.value = 0
            except Exception:
                if self.logger:
                    self.logger.debug("重置 cancel_flag 失败", exc_info=True)
            self._process = self._ctx.Process(
                target=_worker_main,
                args=(self.config, self.engine_id, self.requested_provider,
                      self._command_queue, self._result_queue, self._cancel_flag),
                name=f"angevoice-{self.engine_id}-worker",
                daemon=True,
            )
            self._process.start()

    def close(self, *, kill: bool = False) -> None:
        # 强制释放/取消必须能够杀死卡住的推理，即使请求线程持有 _request_lock。
        # 优雅的空闲释放被序列化，以避免意外中断已接受的请求。
        if kill:
            with self._lifecycle_lock:
                self._close_locked(kill=True)
            return
        with self._request_lock, self._lifecycle_lock:
            self._close_locked(kill=False)

    def _close_locked(self, *, kill: bool) -> None:
        process = self._process
        if process is None:
            self._loaded = False
            self._discard_queues()
            return
        # CUDA 上下文（context）销毁可能需要额外时间；kill 模式给更长的宽限期。
        base_grace = float(getattr(self.config, "engine_process_kill_grace_seconds", 2.0) or 2.0)
        grace = max(base_grace, 5.0) if kill else base_grace
        if process.is_alive() and not kill:
            try:
                if self._command_queue is not None:
                    self._command_queue.put_nowait((uuid.uuid4().hex, "shutdown", {}))
            except Exception:
                pass
            process.join(timeout=grace)
        if process.is_alive():
            process.terminate()
            process.join(timeout=grace)
        if process.is_alive():
            process.kill()
            process.join(timeout=min(1.0, grace))
        self._process = None
        self._loaded = False
        self._unhealthy = False
        self._last_exit_reason = ""
        # 在下次全新启动前重置取消标志。
        try:
            self._cancel_flag.value = 0
        except Exception:
            if self.logger:
                self.logger.debug("重置 cancel_flag 失败", exc_info=True)
        self._discard_queues()

    def load(self, *, timeout: float) -> dict:
        value = self.request("load", {}, timeout=timeout)
        self._loaded = True
        self._unhealthy = False
        self._last_exit_reason = ""
        self._last_metadata = dict(value) if isinstance(value, dict) else {}
        return dict(self._last_metadata)

    def request(self, command: str, payload: dict | None = None, *, timeout: float) -> object:
        with self._request_lock:
            request_id = self._send(command, payload or {})
            result = self._wait_for(request_id, timeout=timeout)
            if result.kind == "error":
                raise RuntimeError(str(result.payload))
            if result.kind != "result":
                raise RuntimeError(f"{self.engine_id} worker returned unexpected message: {result.kind}")
            if command in {"load", "metadata"} and isinstance(result.payload, dict):
                self._last_metadata = dict(result.payload)
                self._loaded = bool(self._last_metadata.get("loaded", command == "load"))
            return result.payload

    def stream(
        self,
        payload: dict,
        *,
        timeout: float,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Iterator[dict]:
        with self._request_lock:
            # 确保取消标志在新请求开始前清空，避免上一次软取消信号泄漏到本次请求。
            try:
                self._cancel_flag.value = 0
            except Exception:
                if self.logger:
                    self.logger.debug("重置 cancel_flag 失败", exc_info=True)
            request_id = self._send("synthesize_stream", payload)
            idle_timeout = max(1.0, float(timeout))
            deadline = time.monotonic() + idle_timeout
            drain_deadline: float | None = None
            while True:
                if cancel_check is not None:
                    try:
                        if cancel_check():
                            # 向 worker 子进程发送软取消信号（在 yield 间隙检查），
                            # 而非杀掉整个进程重新加载模型。worker 在下一个
                            # 命令开始时重置标志，故为一次性信号。
                            try:
                                self._cancel_flag.value = 1
                            except Exception:
                                if self.logger:
                                    self.logger.debug("设置 cancel_flag 失败", exc_info=True)
                            # cancel 后设置 drain 上限，避免 stale frames 无限重置 deadline。
                            drain_deadline = time.monotonic() + 5.0
                    except Exception:
                        if self.logger:
                            self.logger.debug("%s worker cancel_check 失败", self.engine_id, exc_info=True)
                remaining = deadline - time.monotonic()
                if drain_deadline is not None:
                    drain_remaining = drain_deadline - time.monotonic()
                    if drain_remaining <= 0:
                        # cancel 后 stale frames 超出宽限时间，强制终止 worker。
                        self.close(kill=True)
                        return
                    remaining = min(remaining, drain_remaining)
                if remaining <= 0:
                    # 硬超时：worker 确实卡死了，kill 合理。
                    self.close(kill=True)
                    raise EngineProcessTimeoutError(f"{self.engine_id} worker stream idle timed out after {timeout}s")
                self._raise_if_worker_exited()
                try:
                    raw = self._require_result_queue().get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue
                result = WorkerResult(*raw)
                if result.request_id != request_id:
                    # 上一次取消请求的残留帧，worker 仍在排空。
                    # worker 存活且在工作，重置 deadline 避免伪超时；
                    # 但若已处于 cancel drain 阶段则不重置 drain_deadline。
                    deadline = time.monotonic() + idle_timeout
                    if self.logger:
                        self.logger.debug(
                            "%s worker: 丢弃取消请求的残留帧 %s",
                            self.engine_id, result.request_id,
                        )
                    continue
                deadline = time.monotonic() + idle_timeout
                # 收到属于当前请求的帧，清除 drain 状态。
                drain_deadline = None
                if result.kind == "event":
                    yield result.payload
                elif result.kind == "done":
                    return
                elif result.kind == "error":
                    raise RuntimeError(str(result.payload))
                else:
                    raise RuntimeError(f"{self.engine_id} worker returned unexpected stream message: {result.kind}")

    def _send(self, command: str, payload: dict) -> str:
        self.start()
        request_id = uuid.uuid4().hex
        if self._command_queue is None:
            raise RuntimeError(f"{self.engine_id} worker command queue is unavailable")
        self._command_queue.put((request_id, command, payload))
        return request_id

    def _wait_for(self, request_id: str, *, timeout: float) -> WorkerResult:
        deadline = time.monotonic() + max(0.01, float(timeout))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close(kill=True)
                raise EngineProcessTimeoutError(f"{self.engine_id} worker timed out after {timeout}s")
            self._raise_if_worker_exited()
            try:
                raw = self._require_result_queue().get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            result = WorkerResult(*raw)
            if result.request_id == request_id:
                return result

    def _raise_if_worker_exited(self) -> None:
        if self._process is not None and not self._process.is_alive():
            code = self._process.exitcode
            was_loaded = self._loaded
            self._loaded = False
            if was_loaded:
                self._unhealthy = True
                self._last_exit_reason = f"worker exited unexpectedly with code {code}"
            raise RuntimeError(f"{self.engine_id} worker exited unexpectedly with code {code}")

    def _require_result_queue(self):
        if self._result_queue is None:
            raise RuntimeError(f"{self.engine_id} worker result queue is unavailable")
        return self._result_queue

    def _discard_queues(self) -> None:
        result_queue = self._result_queue
        command_queue = self._command_queue

        if result_queue is not None:
            while True:
                try:
                    result_queue.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    break

        for managed_queue in (command_queue, result_queue):
            if managed_queue is None:
                continue
            with suppress(Exception):
                managed_queue.close()
            with suppress(Exception):
                managed_queue.join_thread()

        self._command_queue = None
        self._result_queue = None


def _worker_main(config, engine_id: str, requested_provider: str | None,
                 command_queue, result_queue, cancel_flag) -> None:
    engine = None

    def ensure_engine():
        nonlocal engine
        if engine is None:
            engine = create_worker_engine(config, engine_id, requested_provider)
            engine.load()
        return engine

    while True:
        request_id, command, payload = command_queue.get()
        # 在每个命令开始时重置取消标志，
        # 避免之前的软取消信号意外中止下一个请求。
        try:
            cancel_flag.value = 0
        except Exception:
            pass  # 子进程内无法用 logger，静默处理
        if command == "shutdown":
            try:
                if engine is not None:
                    engine.unload()
            finally:
                result_queue.put((request_id, "result", {"ok": True}))
            return
        try:
            current = ensure_engine()
            if command == "load":
                result_queue.put((request_id, "result", current.metadata()))
            elif command == "metadata":
                result_queue.put((request_id, "result", current.metadata()))
            elif command == "synthesize":
                result_queue.put((request_id, "result", current.synthesize(**payload)))
            elif command == "synthesize_array":
                result_queue.put((request_id, "result", current.synthesize_array(**payload)))
            elif command == "synthesize_stream":
                payload.pop("cancel_check", None)
                cancelled = False
                for item in current.synthesize_stream(**payload):
                    # 在每个 yield 的帧之间检查共享取消标志。
                    # 这允许主进程中止流消费，
                    # 而无需杀死 worker 进程或重新加载模型。
                    try:
                        if cancel_flag.value:
                            cancelled = True
                            break
                    except Exception:
                        pass
                    result_queue.put((request_id, "event", item))
                # 始终发送终止消息，以便消费者可以干净地排空。
                result_queue.put((request_id, "done", None))
                if cancelled:
                    # 立即重置标志，使下一个命令能干净启动。
                    try:
                        cancel_flag.value = 0
                    except Exception:
                        pass  # 子进程内无法用 logger
            elif command == "get_voices":
                result_queue.put((request_id, "result", current.get_voices()))
            else:
                raise RuntimeError(f"Unknown {engine_id} worker command: {command}")
        except BaseException as exc:  # noqa: BLE001
            result_queue.put((request_id, "error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))
