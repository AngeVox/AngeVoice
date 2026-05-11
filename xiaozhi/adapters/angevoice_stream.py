"""AngeVoice WebSocket streaming adapter for xiaozhi-esp32-server.

Install into:
    /opt/xiaozhi-esp32-server/core/providers/tts/angevoice_stream.py

Supports:
- Kokoro streaming
- MOSS preset-voice streaming
- MOSS clone streaming when `prompt_audio_path` is configured
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import queue
import traceback

import aiohttp

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import ContentType, InterfaceType, SentenceType
from core.utils.tts import MarkdownCleaner

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    """Stream AngeVoice PCM chunks into xiaozhi Opus playback."""

    TTS_PARAM_CONFIG = [("ttsRate", "speed", 0.25, 4.0, 1.0, lambda v: round(float(v), 2))]

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.interface_type = InterfaceType.SINGLE_STREAM
        self.api_key = config.get("api_key", "") or ""
        self.ws_url = _resolve_ws_url(
            config.get("api_url") or config.get("ws_url") or "ws://host.docker.internal:8101/ws/v1/tts"
        )
        self.model = config.get("model", "kokoro")
        self.voice = config.get("private_voice") or config.get("voice", "zm_010")
        self.stream_format = config.get("stream_format") or config.get("format", "pcm_s16le")
        self.audio_file_type = "pcm" if self.stream_format.startswith("pcm") else "wav"
        self.timeout = int(config.get("tts_timeout", config.get("timeout", 180)))
        self.connect_timeout = int(config.get("connect_timeout", 15))
        self.prompt_audio_path = config.get("prompt_audio_path", "") or ""
        self.prompt_audio_filename = config.get("prompt_audio_filename") or os.path.basename(self.prompt_audio_path) or "reference.wav"
        speed = config.get("speed", "1.0")
        self.speed = float(speed) if speed not in (None, "") else 1.0
        self.output_file = config.get("output_dir", "tmp/")
        self._pcm_buffer = bytearray()
        self._apply_percentage_params(config)

    async def text_to_speak(self, text, output_file):
        """Abstract-method fallback.

        xiaozhi instantiates providers through the abstract base class. The real
        streaming path is `tts_text_priority_thread()`. This method collects a
        whole WebSocket response only for non-stream fallback/testing paths.
        """
        chunks: list[bytes] = []
        async for item in self._iter_stream_events(str(text or "")):
            if item[0] == "audio":
                chunks.append(item[1])
        data = b"".join(chunks)
        if output_file:
            with open(output_file, "wb") as f:
                f.write(data)
            return None
        return data

    def tts_text_priority_thread(self):
        while not self.conn.stop_event.is_set():
            try:
                message = self.tts_text_queue.get(timeout=1)
                if self.conn.client_abort:
                    continue
                if message.sentence_id != self.conn.sentence_id:
                    continue
                if message.sentence_type == SentenceType.FIRST:
                    self.current_sentence_id = message.sentence_id
                    self.tts_stop_request = False
                    self.processed_chars = 0
                    self.tts_text_buff = []
                    self.is_first_sentence = True
                    self.tts_audio_first_sentence = True
                    self._pcm_buffer.clear()
                elif ContentType.TEXT == message.content_type:
                    self.tts_text_buff.append(message.content_detail)
                    segment_text = self._get_segment_text()
                    if segment_text:
                        self.to_tts_single_stream(segment_text, message.sentence_id)
                elif ContentType.FILE == message.content_type:
                    self._process_remaining_text_stream(opus_handler=self.handle_opus)
                    if message.content_file and os.path.exists(message.content_file):
                        self._process_audio_file_stream(message.content_file, callback=self.handle_opus)
                if message.sentence_type == SentenceType.LAST:
                    self._process_remaining_text_stream(opus_handler=self.handle_opus)
                    self._flush_pcm_buffer(end_of_stream=True)
                    self.tts_audio_queue.put((SentenceType.LAST, [], message.content_detail, message.sentence_id))
            except queue.Empty:
                continue
            except Exception as exc:
                logger.bind(tag=TAG).error(f"AngeVoice流式TTS处理失败: {exc}, 堆栈: {traceback.format_exc()}")

    def _process_remaining_text_stream(self, opus_handler=None):
        full_text = "".join(self.tts_text_buff)
        remaining_text = full_text[self.processed_chars :]
        if not remaining_text:
            return False
        segment_text = remaining_text.strip()
        if not segment_text:
            return False
        self.to_tts_single_stream(segment_text, getattr(self, "current_sentence_id", None))
        self.processed_chars = len(full_text)
        return True

    def to_tts_single_stream(self, text: str, sentence_id: str | None = None) -> None:
        original_text = text
        text = MarkdownCleaner.clean_markdown(text)
        if self._correct_words_pattern:
            text = self._correct_words_pattern.sub(lambda m: self.correct_words[m.group(0)], text)
        if not text:
            return
        try:
            self.tts_audio_queue.put((SentenceType.FIRST, [], original_text, sentence_id or getattr(self, "current_sentence_id", None)))
            asyncio.run(self._stream_text(text, sentence_id=sentence_id))
            logger.bind(tag=TAG).info(f"AngeVoice流式合成成功: {original_text}")
        except Exception as exc:
            logger.bind(tag=TAG).error(f"AngeVoice流式合成失败: {original_text}，错误: {exc}")

    async def _stream_text(self, text: str, sentence_id: str | None = None) -> None:
        async for typ, payload in self._iter_stream_events(text):
            if self.conn.stop_event.is_set() or self.conn.client_abort:
                break
            if typ == "audio" and payload:
                self._push_audio_bytes(payload, sentence_id)
            elif typ == "done":
                break
            elif typ == "error":
                raise Exception(payload.decode("utf-8", errors="ignore") if isinstance(payload, bytes) else str(payload))
        self._flush_pcm_buffer(end_of_stream=False)

    async def _iter_stream_events(self, text: str):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.connect_timeout, sock_read=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(self.ws_url, headers=headers, heartbeat=20) as ws:
                await ws.send_json(self._build_payload(text))
                async for msg in ws:
                    if hasattr(self, "conn") and self.conn is not None and (self.conn.stop_event.is_set() or self.conn.client_abort):
                        await _send_cancel(ws)
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = _loads(msg.data)
                        if not data:
                            continue
                        typ = data.get("type") or data.get("event")
                        if typ in {"audio", "segment_audio"}:
                            yield "audio", _audio_bytes(data)
                        elif typ in {"done", "cancelled"}:
                            yield "done", b""
                            break
                        elif typ in {"error", "segment_error"}:
                            yield "error", (data.get("message") or data.get("error") or "AngeVoice stream error")
                            break
                    elif msg.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED}:
                        break

    def _build_payload(self, text: str) -> dict:
        payload = {
            "model": self.model,
            "text": text,
            "voice": self.voice,
            "format": self.stream_format,
            "speed": self.speed,
            "binary": False,
        }
        if self.api_key:
            payload["token"] = self.api_key
        if self.prompt_audio_path:
            payload["prompt_audio"] = _load_prompt_audio(self.prompt_audio_path, self.prompt_audio_filename)
        return payload

    def _push_audio_bytes(self, audio: bytes, sentence_id: str | None) -> None:
        if not audio:
            return
        if self.stream_format.startswith("pcm"):
            self._pcm_buffer.extend(audio)
            self._drain_pcm_buffer(sentence_id=sentence_id, end_of_stream=False)
        else:
            self.tts_audio_queue.put((SentenceType.MIDDLE, audio, None, sentence_id or getattr(self, "current_sentence_id", None)))

    def _frame_bytes(self) -> int:
        return int(
            self.opus_encoder.sample_rate
            * self.opus_encoder.channels
            * self.opus_encoder.frame_size_ms
            / 1000
            * 2
        )

    def _drain_pcm_buffer(self, sentence_id: str | None, end_of_stream: bool) -> None:
        frame_bytes = self._frame_bytes()
        while len(self._pcm_buffer) >= frame_bytes:
            frame = bytes(self._pcm_buffer[:frame_bytes])
            del self._pcm_buffer[:frame_bytes]
            self.opus_encoder.encode_pcm_to_opus_stream(frame, end_of_stream=False, callback=self.handle_opus)
        if end_of_stream:
            self._flush_pcm_buffer(end_of_stream=True)

    def _flush_pcm_buffer(self, end_of_stream: bool = True) -> None:
        if not self._pcm_buffer:
            return
        frame_bytes = self._frame_bytes()
        frame = bytes(self._pcm_buffer)
        self._pcm_buffer.clear()
        if len(frame) < frame_bytes:
            frame += b"\x00" * (frame_bytes - len(frame))
        self.opus_encoder.encode_pcm_to_opus_stream(frame, end_of_stream=end_of_stream, callback=self.handle_opus)


def _resolve_ws_url(url: str) -> str:
    url = str(url or "").strip()
    if url.startswith("http://"):
        url = "ws://" + url[len("http://") :]
    elif url.startswith("https://"):
        url = "wss://" + url[len("https://") :]
    url = url.rstrip("/")
    if not url.endswith("/ws/v1/tts"):
        url += "/ws/v1/tts"
    return url


def _loads(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        return {}


def _audio_bytes(data: dict) -> bytes:
    raw = data.get("audio") or data.get("data") or ""
    if not raw:
        return b""
    if isinstance(raw, str) and raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw)
    except Exception:
        return b""


def _load_prompt_audio(path: str, filename: str) -> dict:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return {"filename": filename or os.path.basename(path), "data": data}


async def _send_cancel(ws) -> None:
    try:
        await ws.send_json({"type": "cancel"})
    except Exception:
        pass
