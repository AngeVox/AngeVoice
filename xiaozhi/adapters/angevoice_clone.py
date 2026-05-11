"""AngeVoice MOSS clone adapter for xiaozhi-esp32-server.

Install into:
    /opt/xiaozhi-esp32-server/core/providers/tts/angevoice_clone.py

This adapter uses AngeVoice's multipart `/api/tts` endpoint with a fixed
reference audio file. For streaming clone, use `angevoice_stream.py` and set
`prompt_audio_path` in the config.
"""

from __future__ import annotations

import os

import httpx

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase

TAG = __name__
logger = setup_logging()

MAX_PROMPT_AUDIO_SIZE = 10 * 1024 * 1024  # 10 MB


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
        self.timeout = int(config.get("tts_timeout", config.get("timeout", 180)))
        self.output_file = config.get("output_dir", "tmp/")

    async def text_to_speak(self, text, output_file):
        if not self.prompt_audio_path:
            raise Exception("AngeVoice MOSS克隆需要配置 prompt_audio_path")
        if not os.path.exists(self.prompt_audio_path):
            raise Exception(f"AngeVoice MOSS克隆参考音频不存在: {self.prompt_audio_path}")

        file_size = os.path.getsize(self.prompt_audio_path)
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
            with open(self.prompt_audio_path, "rb") as audio_file:
                files = {"prompt_audio": (os.path.basename(self.prompt_audio_path), audio_file)}
                response = await client.post(self.api_url, data=data, files=files, headers=headers)

            if response.status_code != 200:
                raise Exception(f"AngeVoice MOSS克隆请求失败: {response.status_code} - {response.text[:500]}")

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
