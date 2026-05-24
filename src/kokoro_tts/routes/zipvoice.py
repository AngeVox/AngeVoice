"""ZipVoice 音色档案与持久化资产管理路由。"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from ..audio import normalize_browser_preview_wav_to_pcm16_bytes, normalize_reference_wav_to_pcm16_bytes
from ..service_state import ServiceState
from ..zipvoice.assets import ZipVoiceAssetManager


def _recommendations() -> list[str]:
    path = Path(__file__).resolve().parents[1] / "static" / "zipvoice_recommended_prompts.json"
    return json.loads(path.read_text(encoding="utf-8"))


class VoiceProfileMetadataPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = None


def _duration_seconds(content: bytes) -> float | None:
    try:
        import soundfile as sf
        info = sf.info(BytesIO(content))
        return float(info.frames / info.samplerate) if info.samplerate else None
    except Exception:
        return None


def create_zipvoice_router(state: ServiceState, verify_api_key) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg
    assets = ZipVoiceAssetManager(cfg)
    # Register ZipVoice-specific reference prompts behind the generic profile service seam.
    # Future adapters register their own prompts without changing Studio or public routes.
    state.voice_profiles.register_recommended_prompts("zipvoice", _recommendations())

    def require_profile_engine(engine: str) -> str:
        model = str(engine or "").strip().lower()
        if not state.voice_profiles.supports_profiles(model):
            raise HTTPException(status_code=400, detail=f"模型不支持保存音色: {model}")
        return model

    async def save_profile_for_engine(engine: str, request: Request) -> dict:
        model = require_profile_engine(engine)
        form = await request.form()
        upload = form.get("reference_audio") or form.get("prompt_audio")
        if not upload or not getattr(upload, "filename", ""):
            raise HTTPException(status_code=400, detail="请上传 WAV 参考音频")
        if not str(upload.filename).lower().endswith(".wav"):
            raise HTTPException(status_code=400, detail="保存音色暂仅支持 WAV 参考音频")
        max_bytes = state.voice_profiles.upload_limit_bytes(model)
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"{model} 参考音频超过大小限制")
        duration = _duration_seconds(content)
        if duration is None:
            raise HTTPException(status_code=400, detail="无法读取参考音频，请上传有效 WAV 文件")
        max_seconds = state.voice_profiles.reference_max_seconds(model)
        if duration > max_seconds:
            raise HTTPException(status_code=400, detail=f"参考录音最长支持 {max_seconds:g} 秒，当前 {duration:.2f} 秒。ZipVoice 官方建议单人参考音频少于 3 秒，请裁剪后重试。")
        try:
            normalized_content = normalize_reference_wav_to_pcm16_bytes(content)
            profile = state.voice_profiles.save(
                model, voice_id=str(form.get("voice_id") or ""), name=str(form.get("name") or ""),
                prompt_text=str(form.get("prompt_text") or ""), audio_bytes=normalized_content, filename=str(upload.filename),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state.cache_clear()
        return {"ok": True, "engine": model, "profile": profile, "duration_seconds": round(duration, 3), "duration_warning": "ZipVoice 官方建议单人参考音频少于 3 秒；较长音频可能降低速度或音质。" if duration > 3 else ""}

    async def preview_reference_for_engine(engine: str, request: Request) -> Response:
        model = require_profile_engine(engine)
        form = await request.form()
        upload = form.get("reference_audio") or form.get("prompt_audio")
        if not upload or not getattr(upload, "filename", ""):
            raise HTTPException(status_code=400, detail="请上传 WAV 参考音频")
        if not str(upload.filename).lower().endswith(".wav"):
            raise HTTPException(status_code=400, detail="参考音频试听暂仅支持 WAV 文件")
        max_bytes = state.voice_profiles.upload_limit_bytes(model)
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"{model} 参考音频超过大小限制")
        duration = _duration_seconds(content)
        if duration is None:
            raise HTTPException(status_code=400, detail="无法读取参考音频，请上传有效 WAV 文件")
        max_seconds = state.voice_profiles.reference_max_seconds(model)
        if duration > max_seconds:
            raise HTTPException(status_code=400, detail=f"参考录音最长支持 {max_seconds:g} 秒，当前 {duration:.2f} 秒。ZipVoice 官方建议单人参考音频少于 3 秒，请裁剪后重试。")
        try:
            normalized = normalize_browser_preview_wav_to_pcm16_bytes(content)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="参考音频无法转换为可试听 WAV") from exc
        headers = {
            "X-AngeVoice-Audio-Contract": "PCM16_MONO_24000", "X-AngeVoice-Duration-Seconds": f"{duration:.3f}",
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        }
        if duration > 3:
            headers["X-AngeVoice-Reference-Warning"] = "exceeds-recommended-duration"
        return Response(content=normalized, media_type="audio/wav", headers=headers)

    async def reference_audio_for_profile(engine: str, voice_id: str) -> Response:
        model = require_profile_engine(engine)
        try:
            profile = state.voice_profiles.load(model, voice_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not profile:
            raise HTTPException(status_code=404, detail="未找到指定音色档案")
        try:
            normalized = normalize_browser_preview_wav_to_pcm16_bytes(Path(profile["reference_audio_path"]).read_bytes())
        except Exception as exc:
            raise HTTPException(status_code=500, detail="保存音色的参考音频无法读取") from exc
        return Response(content=normalized, media_type="audio/wav", headers={
            "X-AngeVoice-Audio-Contract": "PCM16_MONO_24000", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    @router.get("/v1/reference-audio/{engine}/recommended-prompts")
    async def engine_recommended_prompts(engine: str, _=Depends(verify_api_key)):
        model = require_profile_engine(engine)
        return {"engine": model, "recommended_duration_seconds": "<3", "maximum_duration_seconds": state.voice_profiles.reference_max_seconds(model), "items": state.voice_profiles.recommended_prompts(model)}

    @router.get("/v1/zipvoice/recommended-prompts")
    async def recommended_prompts():
        # legacy compatibility endpoint. New UI uses /v1/reference-audio/{engine}/recommended-prompts.
        return {"engine": "zipvoice", "recommended_duration_seconds": "<3", "maximum_duration_seconds": state.voice_profiles.reference_max_seconds("zipvoice"), "items": state.voice_profiles.recommended_prompts("zipvoice")}

    @router.get("/v1/voice-profiles")
    async def list_voice_profiles(engine: str = "zipvoice", _=Depends(verify_api_key)):
        model = require_profile_engine(engine)
        return {"engine": model, "profiles": state.voice_profiles.list(model)}

    @router.get("/v1/voice-profiles/verify")
    async def verify_voice_profiles(engine: str = "zipvoice", voice_id: str | None = None, _=Depends(verify_api_key)):
        model = require_profile_engine(engine)
        return state.voice_profiles.verify(model, voice_id)

    @router.patch("/v1/voice-profiles/{engine}/{voice_id}")
    async def update_voice_profile(engine: str, voice_id: str, req: VoiceProfileMetadataPatch, _=Depends(verify_api_key)):
        model = require_profile_engine(engine)
        try:
            profile = state.voice_profiles.update_metadata(model, voice_id, **req.model_dump())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "engine": model, "profile": profile}

    @router.post("/v1/voice-profiles/{engine}")
    async def save_voice_profile(engine: str, request: Request, _=Depends(verify_api_key)):
        return await save_profile_for_engine(engine, request)

    @router.delete("/v1/voice-profiles/{engine}/{voice_id}")
    async def delete_voice_profile(engine: str, voice_id: str, _=Depends(verify_api_key)):
        model = require_profile_engine(engine)
        try:
            deleted = state.voice_profiles.delete(model, voice_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if deleted:
            state.cache_clear()
        return {"ok": True, "engine": model, "voice_id": voice_id, "deleted": deleted}

    @router.post("/v1/reference-audio/{engine}/preview")
    async def preview_engine_reference(engine: str, request: Request, _=Depends(verify_api_key)):
        return await preview_reference_for_engine(engine, request)

    @router.get("/v1/voice-profiles/{engine}/{voice_id}/reference.wav")
    async def get_profile_reference(engine: str, voice_id: str, _=Depends(verify_api_key)):
        return await reference_audio_for_profile(engine, voice_id)

    @router.get("/v1/zipvoice/profiles")
    async def list_profiles(_=Depends(verify_api_key)):
        return {"engine": "zipvoice", "profiles": state.voice_profiles.list("zipvoice")}

    @router.post("/v1/zipvoice/profiles")
    async def save_profile(request: Request, _=Depends(verify_api_key)):
        return await save_profile_for_engine("zipvoice", request)

    @router.delete("/v1/zipvoice/profiles/{voice_id}")
    async def delete_profile(voice_id: str, _=Depends(verify_api_key)):
        model = "zipvoice"
        deleted = state.voice_profiles.delete(model, voice_id)
        if deleted:
            state.cache_clear()
        return {"ok": True, "engine": model, "voice_id": voice_id, "deleted": deleted}

    @router.post("/v1/zipvoice/reference-preview")
    async def preview_reference(request: Request, _=Depends(verify_api_key)):
        return await preview_reference_for_engine("zipvoice", request)

    @router.get("/v1/zipvoice/profiles/{voice_id}/reference.wav")
    async def get_reference(voice_id: str, _=Depends(verify_api_key)):
        return await reference_audio_for_profile("zipvoice", voice_id)

    @router.get("/v1/zipvoice/assets")
    async def asset_status(_=Depends(verify_api_key)):
        return assets.status()

    @router.post("/v1/zipvoice/assets/ensure")
    async def ensure_assets(_=Depends(verify_api_key)):
        try:
            return await run_in_threadpool(assets.ensure)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
