"""AngeVoice MOSS clone adapter for xiaozhi-esp32-server.

Install into:
    /opt/xiaozhi-esp32-server/core/providers/tts/angevoice_clone.py

This adapter uses AngeVoice's multipart `/api/tts` endpoint with a fixed
reference audio file. For streaming clone, use `angevoice_stream.py` and set
`prompt_audio_path` in the config.

The clone prompt path is tolerant of common NAS mistakes.  If a user enters a
host path such as `/vol*/.../data/angevoice_prompts/` in the manager UI, this
adapter maps it to the container path under
`/opt/xiaozhi-esp32-server/data/angevoice_prompts`.  If the reference audio is
still unavailable, it falls back to a normal MOSS request instead of failing the
whole TTS response.
"""

from __future__ import annotations

import os

import httpx

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase

TAG = __name__
logger = setup_logging()

MAX_PROMPT_AUDIO_SIZE = 10 * 1024 * 1024  # 10 MB
PROMPT_CONTAINER_DIR = "/opt/xiaozhi-esp32-server/data/angevoice_prompts"


class TTSProvider(TTSProviderBase):
    """Non-streaming MOSS voice clone adapter for AngeVoice."""

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.api_key = config.get("api_key", "") or ""
        self.api_url = _resolve_clone_url(config.get("api_url") or config.get("base_url") or "http://host.docker.internal:8101")
        self.model = config.get("model", "moss-nano-cpu")
        self.voice = config.get("private_voice") or config.get("voice", "Junhao")
        self.audio_file_type = config.get("response_format") or config.get("format", "wav")
        self.prompt_audio_path = config.get("prompt_audio_path", "") or ""
        self.prompt_audio_filename = config.get("prompt_audio_filename") or os.path.basename(self.prompt_audio_path) or "reference.wav"
        self.timeout = int(config.get("tts_timeout", config.get("timeout", 180)))
        self.output_file = config.get("output_dir", "tmp/")

    async def text_to_speak(self, text, output_file):
        prompt_audio_path = _normalize_prompt_audio_path(self.prompt_audio_path, self.prompt_audio_filename)
        if not prompt_audio_path or not os.path.exists(prompt_audio_path) or os.path.isdir(prompt_audio_path):
            logger.bind(tag=TAG).warning(
                f"AngeVoice MOSS克隆参考音频不可用，已退回普通请求: raw={self.prompt_audio_path!r}, normalized={prompt_audio_path!r}"
            )
            return await self._text_to_speak_without_prompt(text, output_file)

        file_size = os.path.getsize(prompt_audio_path)
        if file_size > MAX_PROMPT_AUDIO_SIZE:
            raise Exception(f"AngeVoice MOSS克隆参考音频过大: {file_size / 1024 / 1024:.1f}MB > {MAX_PROMPT_AUDIO_SIZE / 1024 / 1024:.0f}MB 限制")

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = {
            "model": self.model,
            "text": text,
            "voice": self.voice,
            "response_format": self.audio_file_type,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            with open(prompt_audio_path, "rb") as audio_file:
                files = {"prompt_audio": (os.path.basename(prompt_audio_path), audio_file)}
                response = await client.post(self.api_url, data=data, files=files, headers=headers)

            if response.status_code != 200:
                raise Exception(f"AngeVoice MOSS克隆请求失败: {response.status_code} - {response.text[:500]}")

            if output_file:
                with open(output_file, "wb") as out:
                    out.write(response.content)
                return None
            return response.content

    async def _text_to_speak_without_prompt(self, text, output_file):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = {
            "model": self.model,
            "text": text,
            "voice": self.voice,
            "response_format": self.audio_file_type,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.api_url, data=data, headers=headers)
        if response.status_code != 200:
            raise Exception(f"AngeVoice MOSS请求失败: {response.status_code} - {response.text[:500]}")
        if output_file:
            with open(output_file, "wb") as out:
                out.write(response.content)
            return None
        return response.content


def _resolve_clone_url(url: str) -> str:
    url = str(url or "").strip().rstrip("/")
    if not url:
        url = "http://host.docker.internal:8101"
    if url.endswith("/api/tts"):
        return url
    return f"{url}/api/tts"


def _normalize_prompt_audio_path(path: str, filename: str) -> str:
    raw = str(path or "").strip()
    filename = str(filename or "reference.wav").strip() or "reference.wav"
    if not raw:
        return ""

    candidates: list[str] = []

    def add(candidate: str) -> None:
        candidate = str(candidate or "").strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    add(raw)
    if raw.endswith("/"):
        add(os.path.join(raw, filename))

    marker = "/data/angevoice_prompts"
    if marker in raw:
        suffix = raw.split(marker, 1)[1].lstrip("/")
        if not suffix:
            suffix = filename
        elif suffix.endswith("/"):
            suffix += filename
        add(os.path.join(PROMPT_CONTAINER_DIR, suffix))

    if os.path.isdir(raw):
        add(os.path.join(raw, filename))

    for candidate in candidates:
        if os.path.isdir(candidate):
            candidate_file = os.path.join(candidate, filename)
            if os.path.exists(candidate_file):
                return candidate_file
        if os.path.exists(candidate):
            return candidate

    for candidate in candidates:
        if candidate.startswith(PROMPT_CONTAINER_DIR):
            return candidate
    return candidates[-1] if candidates else ""
