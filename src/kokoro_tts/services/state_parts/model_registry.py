"""Model-adjacent ServiceState helpers and synthesis proxies."""

from __future__ import annotations


class ModelRegistryMixin:
    def _zipvoice_prompt_context(
        self,
        model_id: str,
        voice: str,
        prompt_audio_path: str | None,
        prompt_audio_id: str,
        prompt_text: str,
    ) -> tuple[str | None, str, str, str]:
        """兼容旧测试和旧版内部调用者的代理。"""
        condition = self.voice_profiles.resolve_condition(
            model_id, voice, prompt_audio_path=prompt_audio_path, prompt_audio_id=prompt_audio_id, prompt_text=prompt_text
        )
        return condition.prompt_audio_path, condition.prompt_audio_id, condition.prompt_text, condition.revision

    def synthesize_response_bytes(
        self,
        text: str,
        voice: str,
        speed: float,
        fmt: str,
        model_id: str | None = None,
        prompt_audio_path: str | None = None,
        prompt_audio_id: str = "",
        prompt_text: str = "",
        generation_params: dict | None = None,
    ) -> tuple[bytes, str]:
        request = self.synthesis.build_request(
            text=text,
            voice=voice,
            speed=speed,
            response_format=fmt,
            model_id=model_id,
            prompt_audio_path=prompt_audio_path,
            prompt_audio_id=prompt_audio_id,
            prompt_text=prompt_text,
            engine_params=generation_params,
        )
        return self.synthesis.response_bytes(request)

    async def synthesize_response_threaded(
        self,
        text: str,
        voice: str,
        speed: float,
        fmt: str,
        request_id: str,
        model_id: str | None = None,
        prompt_audio_path: str | None = None,
        prompt_audio_id: str = "",
        prompt_text: str = "",
        generation_params: dict | None = None,
    ):
        request = self.synthesis.build_request(
            text=text,
            voice=voice,
            speed=speed,
            response_format=fmt,
            model_id=model_id,
            prompt_audio_path=prompt_audio_path,
            prompt_audio_id=prompt_audio_id,
            prompt_text=prompt_text,
            engine_params=generation_params,
            request_id=request_id,
        )
        return await self.synthesis.response_threaded(request)

