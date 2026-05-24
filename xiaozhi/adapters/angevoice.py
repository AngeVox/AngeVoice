"""AngeVoice non-streaming TTS adapter for xiaozhi-esp32-server.

Install into:
    /opt/xiaozhi-esp32-server/core/providers/tts/angevoice.py

This adapter calls AngeVoice's OpenAI-compatible `/v1/audio/speech` endpoint.
It is the safest first integration mode for Kokoro and MOSS preset voices.
"""

from __future__ import annotations

import httpx

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.utils.util import check_model_key

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    """AngeVoice OpenAI-compatible HTTP adapter."""

    TTS_PARAM_CONFIG = [
        ("ttsRate", "speed", 0.25, 4.0, 1.0, lambda v: round(float(v), 2)),
    ]

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.api_key = config.get("api_key", "") or ""
        self.api_url = _resolve_speech_url(
            config.get("api_url") or config.get("base_url") or "http://host.docker.internal:8101"
        )
        self.model = config.get("model", "kokoro")
        self.voice = config.get("private_voice") or config.get("voice", "zm_010")
        self.audio_file_type = config.get("response_format") or config.get("format", "wav")
        self.timeout = int(config.get("tts_timeout", config.get("timeout", 120)))
        speed = config.get("speed", "1.0")
        self.speed = float(speed) if speed not in (None, "") else 1.0
        self.output_file = config.get("output_dir", "tmp/")
        self._apply_percentage_params(config)

        if self.api_key:
            model_key_msg = check_model_key("TTS", self.api_key)
            if model_key_msg:
                logger.bind(tag=TAG).warning(model_key_msg)

    async def text_to_speak(self, text, output_file):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": self.audio_file_type,
            "speed": self.speed,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.api_url, json=payload, headers=headers)
            if response.status_code != 200:
                raise Exception(f"AngeVoice TTS请求失败: {response.status_code} - {response.text[:500]}")

            if output_file:
                with open(output_file, "wb") as audio_file:
                    audio_file.write(response.content)
                return None
            return response.content


def _resolve_speech_url(url: str) -> str:
    url = str(url or "").strip().rstrip("/")
    if not url:
        url = "http://host.docker.internal:8101"
    if url.endswith("/v1/audio/speech"):
        return url
    return f"{url}/v1/audio/speech"
