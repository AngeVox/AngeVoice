"""WebSocket TTS session orchestration."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from ..contracts import StreamingRequest
from ..prompt_audio import decode_prompt_audio_base64, save_prompt_audio_bytes, validate_reference_audio_duration
from ..security import _extract_bearer_token, verify_ws_key
from ..service_state import ServiceState
from ..validation import websocket_error_frame_from_http
from .cancel import CancelLifecycleMixin
from .errors import WebSocketPayloadInvalid, WebSocketPayloadTooLarge
from .messages import MessageParsingMixin
from .state import WsSessionState
from .streaming import StreamingLoopMixin

logger = logging.getLogger("kokoro_tts.routes.ws")


class TtsWebSocketSession(MessageParsingMixin, StreamingLoopMixin, CancelLifecycleMixin):
    """Single WebSocket TTS request session."""

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
        self.saw_stream_terminal = False
        self.stream_error_counted = False
        self.done_marker = object()
        self.queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=4)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.phase = WsSessionState.CREATED

    def _transition(self, phase: WsSessionState, **extra) -> None:
        self.phase = phase
        logger.debug("WS state -> %s", phase.value, extra={"request_id": self.request_id, "phase": phase.value, **extra})

    async def run(self) -> None:
        # 新客户端可以在握手期间通过 Authorization
        # 或 ?token= 进行身份验证，允许在接受前拒绝无效连接。
        # 首条消息 token 仍为现有 Studio 客户端支持。
        preauth_token = str(self.websocket.query_params.get("token", "") or "")
        auth_header = self.websocket.headers.get("authorization", "")
        bearer_token = _extract_bearer_token(auth_header)
        has_preauth = bool(preauth_token or bearer_token)

        # 查询字符串 token 被视为显式握手身份验证，
        # 无效时继续在 websocket 接受前硬失败。
        if preauth_token and not await verify_ws_key(self.cfg, self.websocket, token=preauth_token):
            with suppress(Exception):
                await self.websocket.close(code=1008, reason="authentication failed")
            return

        # Bearer 预认证保持机会主义，以便旧版首条消息 token
        # 认证在代理或过时 SDK 在重连或密钥轮换期间附加
        # 过期 Authorization 头时仍能正常工作。
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
            text_normalization = msg.get("text_normalization")
            if text_normalization in {None, ""}:
                text_normalization = msg.get("tn_engine")
            return self.state.streaming.build_request(
                text=msg.get("text", ""), model_id=model, voice=voice,
                speed=msg.get("speed", self.cfg.default_speed), audio_format=fmt, binary=binary,
                prompt_audio_path=self.prompt_audio_path, prompt_audio_id=self.prompt_audio_id,
                prompt_text=str(msg.get("prompt_text") or "").strip(),
                engine_params=supplied, parameter_source=msg, text_normalization=text_normalization,
                request_id=self.request_id,
            )
        except HTTPException as exc:
            await self.websocket.send_json(websocket_error_frame_from_http(exc, request_id=self.request_id))
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
            if self.state.is_cancelled(self.request_id):
                self.state.finish_request(self.request_id, "cancelled")
                return
            self._transition(WsSessionState.RUNNING, model=request.model_id)
            self.state.mark_request(self.request_id, "running")
            self.control_task = asyncio.create_task(self._control_listener())
            self.producer_task = asyncio.create_task(asyncio.to_thread(self._producer, request))
            try:
                await self._send_loop(binary=request.binary)
            finally:
                await self._cancel_background_tasks()

        self._finish(start)
