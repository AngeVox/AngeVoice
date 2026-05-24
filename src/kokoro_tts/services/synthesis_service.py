"""Unified non-streaming synthesis orchestration."""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, TYPE_CHECKING

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from ..audio import encode_audio_segment
from ..contracts import GenerationParameters, SynthesisRequest, SynthesisResult
from ..validation import validate_model_speed, validate_tts_text

if TYPE_CHECKING:
    from ..service_state import ServiceState


class SynthesisService:
    def __init__(self, state: "ServiceState"):
        self.state = state
        self.cfg = state.cfg

    def build_request(
        self,
        *,
        text: str,
        voice: str,
        speed: float,
        response_format: str,
        model_id: str | None = None,
        response_encoding: str = "binary",
        prompt_audio_path: str | None = None,
        prompt_audio_id: str = "",
        prompt_text: str = "",
        engine_params: dict[str, Any] | None = None,
        parameter_source: Any | None = None,
        request_id: str = "",
    ) -> SynthesisRequest:
        resolved_model = self.state.model_manager.normalize_model_id(model_id)
        clean_text = validate_tts_text(text, self.cfg)
        clean_speed = validate_model_speed(resolved_model, speed)
        fmt = self.state.normalize_response_format(response_format)
        params = self.state.parameter_schema.parse(resolved_model, parameter_source, supplied=engine_params)
        condition = self.state.voice_profiles.resolve_condition(
            resolved_model,
            voice,
            prompt_audio_path=prompt_audio_path,
            prompt_audio_id=prompt_audio_id,
            prompt_text=prompt_text,
        )
        return SynthesisRequest(
            text=clean_text,
            model_id=resolved_model,
            voice=str(voice or ""),
            speed=clean_speed,
            response_format=fmt,
            response_encoding=response_encoding,
            condition=condition,
            generation=GenerationParameters(params),
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

    def _inference_kwargs(self, engine, request: SynthesisRequest, method_name: str) -> dict[str, Any]:
        candidates: dict[str, Any] = dict(request.engine_params or {})
        if request.condition.prompt_audio_path:
            candidates["prompt_audio_path"] = request.condition.prompt_audio_path
        if request.condition.prompt_text:
            candidates["prompt_text"] = request.condition.prompt_text
        return self._supported_kwargs(getattr(engine, method_name), candidates)

    def response_result(self, request: SynthesisRequest) -> SynthesisResult:
        prompt_key = self.state.prompt_audio_cache_id(request.model_id, request.condition.cache_audio_id)
        key = self.state.cache_key(
            request.model_id,
            request.text,
            request.voice,
            request.speed,
            request.response_format,
            prompt_key,
            request.condition.prompt_text,
            request.condition.revision,
            request.engine_params,
        )
        cached = self.state.cache_get(key)
        if cached is not None:
            return SynthesisResult(cached[0], cached[1], request.model_id, request.request_id, {"cache_hit": True})

        with self.state.model_manager.borrow(request.model_id) as engine:
            if request.condition.is_reference_conditioned and not self.state.engine_supports_voice_clone(engine):
                raise HTTPException(status_code=400, detail="当前模型不支持参考音频克隆")
            if request.response_format == "pcm":
                kwargs = self._inference_kwargs(engine, request, "synthesize_array")
                wav = engine.synthesize_array(text=request.text, voice=request.voice, speed=request.speed, **kwargs)
                sample_rate = int(getattr(engine, "sample_rate", self.cfg.sample_rate))
                result = (encode_audio_segment(wav, "pcm_s16le", sample_rate), "audio/pcm")
            elif request.response_format == "mp3":
                from ..service_extras import _wav_to_mp3
                kwargs = self._inference_kwargs(engine, request, "synthesize")
                wav_bytes = engine.synthesize(text=request.text, voice=request.voice, speed=request.speed, **kwargs)
                result = (_wav_to_mp3(wav_bytes, getattr(self.cfg, "mp3_bitrate", "192k")), "audio/mpeg")
            else:
                kwargs = self._inference_kwargs(engine, request, "synthesize")
                result = (engine.synthesize(text=request.text, voice=request.voice, speed=request.speed, **kwargs), "audio/wav")
        self.state.cache_set(key, result, text=request.text)
        return SynthesisResult(result[0], result[1], request.model_id, request.request_id, {"cache_hit": False})

    def response_bytes(self, request: SynthesisRequest) -> tuple[bytes, str]:
        return self.response_result(request).as_response_tuple()

    async def response_threaded(self, request: SynthesisRequest) -> tuple[bytes, str]:
        start = time.perf_counter()
        self.state.inc_stat("requests_total")
        self.state.inc_stat("characters_total", len(request.text or ""))
        self.state.mark_request(
            request.request_id,
            "queued",
            voice=request.voice,
            format=request.response_format,
            model=request.model_id,
            chars=len(request.text or ""),
            voice_clone=request.condition.is_reference_conditioned,
            voice_condition=request.condition.as_dict(),
        )
        try:
            async with self.state.tts_semaphore:
                if self.state.is_cancelled(request.request_id):
                    self.state.finish_request(request.request_id, "cancelled")
                    raise HTTPException(status_code=499, detail="请求已取消")
                self.state.mark_request(request.request_id, "running")
                result = await asyncio.wait_for(
                    run_in_threadpool(self.response_bytes, request),
                    timeout=self.cfg.request_timeout_seconds,
                )
            elapsed = time.perf_counter() - start
            self.state.inc_stat("requests_ok")
            self.state.inc_stat("audio_bytes_total", len(result[0]))
            self.state.inc_stat("synthesis_seconds_total", elapsed)
            self.state.latency_tracker.record(elapsed)
            saved_path = self.state.save_generated_output(
                request_id=request.request_id,
                audio_bytes=result[0],
                response_format=request.response_format,
                media_type=result[1],
                model_id=request.model_id,
                voice=request.voice,
            )
            done_extra = {"elapsed_seconds": round(elapsed, 3), "bytes": len(result[0])}
            if saved_path is not None:
                done_extra["output_path"] = str(saved_path)
            self.state.finish_request(request.request_id, "done", **done_extra)
            return result
        except HTTPException as exc:
            self.state.inc_stat("requests_error")
            status = "cancelled" if exc.status_code == 499 else "error"
            self.state.finish_request(request.request_id, status, error=str(exc.detail), status_code=exc.status_code)
            raise
        except Exception as exc:
            self.state.inc_stat("requests_error")
            status = "timeout" if isinstance(exc, asyncio.TimeoutError) else "error"
            self.state.finish_request(request.request_id, status, error=str(exc))
            raise
