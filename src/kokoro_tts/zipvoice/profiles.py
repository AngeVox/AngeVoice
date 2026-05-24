"""Saved ZipVoice reference voice profiles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

VOICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ZipVoiceProfileStore:
    def __init__(self, cfg):
        self.root = Path(getattr(cfg, "zipvoice_profiles_dir", "/app/prompts/zipvoice")).expanduser()

    @staticmethod
    def validate_voice_id(voice_id: str) -> str:
        value = str(voice_id or "").strip()
        if not VOICE_ID_RE.fullmatch(value):
            raise ValueError("voice_id 只能包含字母、数字、_ 或 -，长度 1-64")
        return value

    def _dir(self, voice_id: str) -> Path:
        return self.root / self.validate_voice_id(voice_id)

    def load(self, voice_id: str) -> dict[str, Any] | None:
        path = self._dir(voice_id) / "profile.json"
        audio = path.parent / "reference.wav"
        if not path.is_file() or not audio.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        data["reference_audio_path"] = str(audio)
        return data

    def list(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        profiles: list[dict[str, Any]] = []
        for item in sorted(self.root.iterdir()):
            if not item.is_dir():
                continue
            try:
                profile = self.load(item.name)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if profile:
                profile.pop("reference_audio_path", None)
                profiles.append(profile)
        return profiles

    def save(self, *, voice_id: str, prompt_text: str, audio_bytes: bytes, name: str = "", filename: str = "reference.wav", description: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        voice_id = self.validate_voice_id(voice_id)
        prompt_text = str(prompt_text or "").strip()
        if not prompt_text:
            raise ValueError("保存 ZipVoice 音色必须填写参考文本")
        if not audio_bytes:
            raise ValueError("参考音频不能为空")
        folder = self._dir(voice_id)
        folder.mkdir(parents=True, exist_ok=True)
        audio_digest = hashlib.sha256(audio_bytes).hexdigest()
        revision = hashlib.sha256((voice_id + "\n" + prompt_text + "\n" + audio_digest).encode("utf-8")).hexdigest()[:16]
        audio_tmp = folder / "reference.wav.tmp"
        audio_tmp.write_bytes(audio_bytes)
        os.replace(audio_tmp, folder / "reference.wav")
        payload = {
            "voice_id": voice_id,
            "name": str(name or voice_id).strip() or voice_id,
            "engine": "zipvoice",
            "prompt_text": prompt_text,
            "original_filename": str(filename or "reference.wav"),
            "description": str(description or "").strip(),
            "tags": [str(item).strip() for item in (tags or []) if str(item).strip()][:20],
            "reference_audio_sha256": audio_digest,
            "revision": revision,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        meta_tmp = folder / "profile.json.tmp"
        meta_tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(meta_tmp, folder / "profile.json")
        return payload

    def delete(self, voice_id: str) -> bool:
        folder = self._dir(voice_id)
        if not folder.exists():
            return False
        shutil.rmtree(folder)
        return True
    def update_metadata(self, voice_id: str, *, name: str | None = None, description: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        folder = self._dir(voice_id)
        path = folder / "profile.json"
        profile = self.load(voice_id)
        if not profile:
            raise FileNotFoundError(f"Voice profile not found: {voice_id}")
        profile.pop("reference_audio_path", None)
        if name is not None:
            profile["name"] = str(name or voice_id).strip() or voice_id
        if description is not None:
            profile["description"] = str(description or "").strip()
        if tags is not None:
            profile["tags"] = [str(item).strip() for item in tags if str(item).strip()][:20]
        profile["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
        return profile

    def verify(self, voice_id: str | None = None) -> dict[str, Any]:
        targets = [self._dir(voice_id)] if voice_id else sorted(self.root.iterdir()) if self.root.exists() else []
        results: list[dict[str, Any]] = []
        for folder in targets:
            if not folder.is_dir():
                continue
            item = {"voice_id": folder.name, "ready": False, "issues": []}
            try:
                profile = self.load(folder.name)
            except Exception as exc:
                profile = None
                item["issues"].append(f"profile.json unreadable: {exc}")
            audio_path = folder / "reference.wav"
            if profile is None:
                item["issues"].append("profile or reference audio missing")
            elif not audio_path.is_file():
                item["issues"].append("reference.wav missing")
            else:
                digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()
                if digest != str(profile.get("reference_audio_sha256", "")):
                    item["issues"].append("reference_audio_sha256 mismatch")
                if not str(profile.get("prompt_text", "")).strip():
                    item["issues"].append("prompt_text missing")
            item["ready"] = not item["issues"]
            results.append(item)
        return {"engine": "zipvoice", "root": str(self.root), "ready": all(item["ready"] for item in results), "profiles": results}
