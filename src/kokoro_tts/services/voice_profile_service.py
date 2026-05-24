"""Unified saved-voice profile ownership and voice-condition resolution."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..contracts import VoiceCondition, VoiceConditionKind
from ..zipvoice.profiles import ZipVoiceProfileStore


class VoiceProfileService:
    """Own all persisted reference profiles exposed by product engines.

    ZipVoice is the first profile-backed adapter.  The mapping is deliberately
    service-owned so another adapter can register a store without adding route
    branches or a second copy of profile-resolution rules.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self._stores: dict[str, Any] = {}
        self._requires_reference: set[str] = set()
        self._recommended_prompts: dict[str, tuple[str, ...]] = {}
        self.register_store("zipvoice", ZipVoiceProfileStore(cfg), requires_reference=True)

    def register_store(self, engine_id: str, store: Any, *, requires_reference: bool = False) -> None:
        """Register a profile-capable adapter without adding public-route branches."""
        engine = str(engine_id or "").strip().lower()
        if not engine:
            raise ValueError("engine_id is required")
        self._stores[engine] = store
        if requires_reference:
            self._requires_reference.add(engine)
        else:
            self._requires_reference.discard(engine)

    def register_recommended_prompts(self, engine_id: str, prompts: list[str] | tuple[str, ...]) -> None:
        """Register optional UI recording prompts for a profile-capable adapter."""
        engine = str(engine_id or "").strip().lower()
        if not self.supports_profiles(engine):
            raise ValueError(f"Engine does not support saved voice profiles: {engine_id}")
        self._recommended_prompts[engine] = tuple(str(item).strip() for item in prompts if str(item).strip())

    def recommended_prompts(self, engine_id: str) -> list[str]:
        engine = str(engine_id or "").strip().lower()
        self.store_for(engine)
        return list(self._recommended_prompts.get(engine, ()))

    def supported_engines(self) -> tuple[str, ...]:
        return tuple(self._stores)

    def supports_profiles(self, engine_id: str) -> bool:
        return str(engine_id or "").strip().lower() in self._stores

    def store_for(self, engine_id: str):
        store = self._stores.get(str(engine_id or "").strip().lower())
        if store is None:
            raise ValueError(f"Engine does not support saved voice profiles: {engine_id}")
        return store

    def list(self, engine_id: str) -> list[dict[str, Any]]:
        return self.store_for(engine_id).list()

    def load(self, engine_id: str, voice_id: str) -> dict[str, Any] | None:
        return self.store_for(engine_id).load(voice_id)

    def save(self, engine_id: str, **kwargs) -> dict[str, Any]:
        return self.store_for(engine_id).save(**kwargs)

    def delete(self, engine_id: str, voice_id: str) -> bool:
        return self.store_for(engine_id).delete(voice_id)

    def update_metadata(self, engine_id: str, voice_id: str, **kwargs) -> dict[str, Any]:
        return self.store_for(engine_id).update_metadata(voice_id, **kwargs)

    def verify(self, engine_id: str, voice_id: str | None = None) -> dict[str, Any]:
        return self.store_for(engine_id).verify(voice_id)

    def upload_limit_bytes(self, engine_id: str) -> int:
        name = f"{str(engine_id or '').strip().lower()}_prompt_upload_max_bytes"
        return int(getattr(self.cfg, name, getattr(self.cfg, "voice_upload_max_bytes", 10 * 1024 * 1024)))

    def reference_max_seconds(self, engine_id: str) -> float:
        name = f"{str(engine_id or '').strip().lower()}_prompt_audio_max_seconds"
        return float(getattr(self.cfg, name, 8.0))

    def resolve_condition(
        self,
        engine_id: str,
        voice_id: str = "",
        *,
        prompt_audio_path: str | None = None,
        prompt_audio_id: str = "",
        prompt_text: str = "",
    ) -> VoiceCondition:
        engine_id = str(engine_id or "").strip().lower()
        voice_id = str(voice_id or "").strip()
        prompt_text = str(prompt_text or "").strip()

        if self.supports_profiles(engine_id) and voice_id:
            profile = self.load(engine_id, voice_id)
            if not profile:
                raise HTTPException(status_code=400, detail="所选保存音色不存在，请重新选择或改用临时参考音频")
            return VoiceCondition(
                kind=VoiceConditionKind.SAVED_PROFILE,
                engine_id=engine_id,
                voice_id=voice_id,
                prompt_audio_path=str(profile["reference_audio_path"]),
                prompt_audio_id=f"profile:{voice_id}:{profile.get('reference_audio_sha256', '')}",
                prompt_text=str(profile.get("prompt_text", "")),
                revision=str(profile.get("revision", "")),
            )

        if prompt_audio_path:
            if engine_id in self._requires_reference and not prompt_text:
                raise HTTPException(status_code=400, detail="当前模型的临时克隆需要填写参考文本")
            return VoiceCondition(
                kind=VoiceConditionKind.UPLOADED_REFERENCE,
                engine_id=engine_id,
                voice_id=voice_id,
                prompt_audio_path=prompt_audio_path,
                prompt_audio_id=str(prompt_audio_id or ""),
                prompt_text=prompt_text,
            )

        if engine_id in self._requires_reference:
            raise HTTPException(status_code=400, detail="当前模型需要上传参考音频并填写参考文本，或选择已保存音色")
        return VoiceCondition(kind=VoiceConditionKind.PRESET, engine_id=engine_id, voice_id=voice_id)
