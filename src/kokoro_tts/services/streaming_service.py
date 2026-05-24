"""Unified model-neutral streaming synthesis service."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Iterator, TYPE_CHECKING

from ..contracts import CancellationContext, GenerationParameters, StreamingRequest, StreamingResult
from ..validation import validate_model_speed, validate_tts_text

if TYPE_CHECKING:
    from ..service_state import ServiceState


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
        request_id: str = "",
    ) -> StreamingRequest:
        model = self.state.model_manager.normalize_model_id(model_id)
        condition = self.state.voice_profiles.resolve_condition(
            model,
            voice,
            prompt_audio_path=prompt_audio_path,
            prompt_audio_id=prompt_audio_id,
            prompt_text=prompt_text,
        )
        return StreamingRequest(
            text=validate_tts_text(text, self.cfg),
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
            kwargs = self._supported_kwargs(engine.synthesize_stream, candidates)
            for chunk in engine.synthesize_stream(request.text, request.voice, request.speed, request.audio_format, **kwargs):
                if cancellation.cancelled():
                    break
                if isinstance(chunk, dict):
                    yield StreamingResult.from_frame(chunk, model_id=request.model_id, request_id=request.request_id).as_frame()
                else:
                    yield chunk
