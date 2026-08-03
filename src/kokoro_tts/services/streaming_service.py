"""统一的模型无关流式合成服务。"""

from __future__ import annotations

import inspect
import logging
from dataclasses import replace
from typing import Any, Callable, Iterator, TYPE_CHECKING

from fastapi import HTTPException

from ..contracts import CancellationContext, GenerationParameters, StreamingRequest, StreamingResult
from ..text.frontend import cfg_with_tn_engine
from ..validation import prepare_text_for_synthesis, validate_model_speed

if TYPE_CHECKING:
    from ..service_state import ServiceState

logger = logging.getLogger(__name__)


def _close_stream_iterator(iterator, *, request_id: str, model_id: str) -> None:
    close_iterator = getattr(iterator, "close", None)
    if not callable(close_iterator):
        return
    try:
        close_iterator()
    except Exception:
        logger.warning(
            "关闭流式引擎迭代器失败",
            exc_info=True,
            extra={"request_id": request_id, "model_id": model_id},
        )


class StreamingService:
    def __init__(self, state: "ServiceState"):
        self.state = state
        self.cfg = state.cfg

    def build_request(
        self,
        *,
        text: str,
        model_id: str | None,
        voice: str,
        speed: float,
        audio_format: str,
        binary: bool,
        prompt_audio_path: str | None = None,
        prompt_audio_id: str = "",
        prompt_text: str = "",
        engine_params: dict[str, Any] | None = None,
        parameter_source: Any | None = None,
        text_normalization: str | None = None,
        request_id: str = "",
    ) -> StreamingRequest:
        model = self.state.model_manager.normalize_model_id(model_id)
        try:
            text_cfg = cfg_with_tn_engine(self.cfg, text_normalization)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        condition = self.state.voice_profiles.resolve_condition(
            model,
            voice,
            prompt_audio_path=prompt_audio_path,
            prompt_audio_id=prompt_audio_id,
            prompt_text=prompt_text,
        )
        clean_text = prepare_text_for_synthesis(text, text_cfg, model_id=model, field_name="text", request_id=request_id)
        if model == "zipvoice" and condition.prompt_text:
            condition = replace(
                condition,
                prompt_text=prepare_text_for_synthesis(
                    condition.prompt_text, text_cfg, model_id=model, field_name="prompt_text", request_id=request_id
                ),
            )
        return StreamingRequest(
            text=clean_text,
            model_id=model,
            voice=str(voice or ""),
            speed=validate_model_speed(model, speed),
            audio_format=str(audio_format or self.cfg.stream_format),
            binary=bool(binary),
            condition=condition,
            generation=GenerationParameters(self.state.parameter_schema.parse(model, parameter_source, supplied=engine_params)),
            request_id=request_id,
        )

    @staticmethod
    def _supported_kwargs(method, candidates: dict[str, Any]) -> dict[str, Any]:
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            return {}
        accepts_any = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values())
        return {key: value for key, value in candidates.items() if accepts_any or key in parameters}

    def iter_frames(self, request: StreamingRequest, *, cancel_check: Callable[[], bool] | None = None) -> Iterator[dict[str, Any]]:
        cancellation = CancellationContext(request.request_id, cancel_check)
        with self.state.model_manager.borrow(request.model_id) as engine:
            candidates: dict[str, Any] = request.generation.as_dict()
            if request.condition.prompt_audio_path:
                candidates["prompt_audio_path"] = request.condition.prompt_audio_path
            if request.condition.prompt_text:
                candidates["prompt_text"] = request.condition.prompt_text
            if cancel_check is not None:
                candidates["cancel_check"] = cancellation.cancelled
            if request.model_id == "zipvoice":
                candidates["text_prepared"] = True
                if request.condition.prompt_text:
                    candidates["prompt_text_prepared"] = True
            kwargs = self._supported_kwargs(engine.synthesize_stream, candidates)
            saw_terminal_frame = False
            engine_iterator = iter(
                engine.synthesize_stream(request.text, request.voice, request.speed, request.audio_format, **kwargs)
            )
            try:
                for chunk in engine_iterator:
                    if cancellation.cancelled():
                        # 取消后关闭底层生成器，由进程隔离 worker 设置软取消标志；
                        # 新请求不需要等待旧长文本完整跑完。
                        break
                    if isinstance(chunk, dict):
                        event_type = str(chunk.get("type") or "")
                        if event_type in {"done", "cancelled", "error", "segment_error"}:
                            saw_terminal_frame = True
                        yield StreamingResult.from_frame(
                            chunk,
                            model_id=request.model_id,
                            request_id=request.request_id,
                        ).as_frame()
                    else:
                        yield chunk
            finally:
                _close_stream_iterator(
                    engine_iterator,
                    request_id=request.request_id,
                    model_id=request.model_id,
                )
            if not saw_terminal_frame and cancellation.cancelled():
                logger.info("流式合成在取消状态下结束，补发取消终止帧", extra={"request_id": request.request_id})
                yield StreamingResult.from_frame(
                    {"type": "cancelled"},
                    model_id=request.model_id,
                    request_id=request.request_id,
                ).as_frame()
            elif not saw_terminal_frame:
                yield StreamingResult.from_frame(
                    {
                        "type": "segment_error",
                        "message": "流式合成提前结束，未收到完成帧；本次部分音频已丢弃",
                    },
                    model_id=request.model_id,
                    request_id=request.request_id,
                ).as_frame()
