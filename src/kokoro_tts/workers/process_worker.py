"""Killable worker processes for Kokoro and ZipVoice runtimes.

The API process owns routing, persistent profile metadata and configuration.  A
heavy inference runtime is constructed in a spawned child process so idle/model
release can let the operating system reliably reclaim CPU RSS and GPU memory.
"""

from __future__ import annotations

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
    """A model worker stopped producing results before its request deadline."""


class EngineProcessClient:
    """One lazily started, single-flight child process for an inference runtime."""

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
        # A loaded runtime is intentionally single-flight.  Serialising all queue
        # consumers prevents simultaneous HTTP/WebSocket callers from stealing
        # each other's messages and producing false timeouts.
        self._request_lock = threading.RLock()
        self._loaded = False
        self._last_metadata: dict = {}
        self._unhealthy = False
        self._last_exit_reason = ""

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
        """Idle workers are healthy; loaded workers that crash are not."""

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
            # A killed worker may leave unconsumed commands/results behind.  New
            # queues make the next wake-up a clean runtime generation.
            self._command_queue = self._ctx.Queue()
            self._result_queue = self._ctx.Queue()
            self._loaded = False
            self._process = self._ctx.Process(
                target=_worker_main,
                args=(self.config, self.engine_id, self.requested_provider, self._command_queue, self._result_queue),
                name=f"angevoice-{self.engine_id}-worker",
                daemon=True,
            )
            self._process.start()

    def close(self, *, kill: bool = False) -> None:
        # Force release/cancellation must be able to kill a stuck inference even
        # while the request thread owns _request_lock.  Graceful idle release is
        # serialised so it never interrupts an accepted request accidentally.
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
        grace = float(getattr(self.config, "engine_process_kill_grace_seconds", 2.0) or 2.0)
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
            request_id = self._send("synthesize_stream", payload)
            idle_timeout = max(1.0, float(timeout))
            deadline = time.monotonic() + idle_timeout
            while True:
                if cancel_check is not None:
                    try:
                        if cancel_check():
                            # Torch/ONNX execution cannot always be interrupted
                            # safely inside a thread.  Killing this isolated worker
                            # is intentional and keeps the API wakeable.
                            self.close(kill=True)
                            return
                    except Exception:
                        if self.logger:
                            self.logger.debug("%s worker cancel_check failed", self.engine_id, exc_info=True)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.close(kill=True)
                    raise EngineProcessTimeoutError(f"{self.engine_id} worker stream idle timed out after {timeout}s")
                self._raise_if_worker_exited()
                try:
                    raw = self._require_result_queue().get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue
                result = WorkerResult(*raw)
                if result.request_id != request_id:
                    continue
                deadline = time.monotonic() + idle_timeout
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
        if self._result_queue is not None:
            while True:
                try:
                    self._result_queue.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    break
        self._command_queue = None
        self._result_queue = None


def _worker_main(config, engine_id: str, requested_provider: str | None, command_queue, result_queue) -> None:
    engine = None

    def ensure_engine():
        nonlocal engine
        if engine is None:
            engine = create_worker_engine(config, engine_id, requested_provider)
            engine.load()
        return engine

    while True:
        request_id, command, payload = command_queue.get()
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
                for item in current.synthesize_stream(**payload):
                    result_queue.put((request_id, "event", item))
                result_queue.put((request_id, "done", None))
            elif command == "get_voices":
                result_queue.put((request_id, "result", current.get_voices()))
            else:
                raise RuntimeError(f"Unknown {engine_id} worker command: {command}")
        except BaseException as exc:  # noqa: BLE001
            result_queue.put((request_id, "error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))
