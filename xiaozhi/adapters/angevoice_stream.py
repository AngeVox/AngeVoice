"""AngeVoice WebSocket streaming adapter for xiaozhi-esp32-server.

Install into:
    /opt/xiaozhi-esp32-server/core/providers/tts/angevoice_stream.py

Supports:
- Kokoro streaming
- MOSS preset-voice streaming
- MOSS clone streaming when `prompt_audio_path` is configured

The clone prompt path is intentionally tolerant because NAS users often copy a
host path from the file manager into the manager UI.  The adapter accepts:

- container file path: /opt/xiaozhi-esp32-server/data/angevoice_prompts/reference.wav
- container directory: /opt/xiaozhi-esp32-server/data/angevoice_prompts/
- host-like path containing /data/angevoice_prompts, such as /vol*/.../data/angevoice_prompts/

If the prompt audio still cannot be found, the adapter falls back to normal MOSS
streaming instead of failing the whole xiaozhi TTS response.

AngeVoice models may return different PCM layouts.  Kokoro is usually mono, but
MOSS exposes the runtime sample rate/channels in the `started` event and can be
48 kHz stereo.  xiaozhi's Opus encoder expects the PCM bytes to match its own
sample_rate/channels.  This adapter therefore downmixes/resamples raw PCM chunks
before feeding them into the Opus encoder.

Important: resampling must be stateful across chunks.  Stateless per-chunk
interpolation creates discontinuities at chunk boundaries, which sounds like
clicks, clipping, stutter, or harsh explosions on small speakers.  We use
`audioop.ratecv` with persistent state for the actual real-time path.
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import json
import os
import queue
import threading
import traceback
import wave
from io import BytesIO

import aiohttp

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import ContentType, InterfaceType, SentenceType
from core.utils.tts import MarkdownCleaner

TAG = __name__
logger = setup_logging()

MAX_PROMPT_AUDIO_SIZE = 10 * 1024 * 1024  # 10 MB
PROMPT_CONTAINER_DIR = "/opt/xiaozhi-esp32-server/data/angevoice_prompts"


class _BackgroundLoop:
    """Persistent event loop running in a dedicated daemon thread."""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run_coro(self, coro, timeout: float = 180):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def close(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)


_bg_loop: _BackgroundLoop | None = None
_bg_lock = threading.Lock()


def _get_bg_loop() -> _BackgroundLoop:
    global _bg_loop
    if _bg_loop is None:
        with _bg_lock:
            if _bg_loop is None:
                _bg_loop = _BackgroundLoop()
    return _bg_loop


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
        # The real-time path consumes raw PCM, but xiaozhi's fallback base class
        # expects a self-describing audio container when it calls text_to_speak().
        # Return WAV bytes there to avoid pydub's raw PCM `sample_width` error.
        self.audio_file_type = "wav"
        self.timeout = int(config.get("tts_timeout", config.get("timeout", 180)))
        self.connect_timeout = int(config.get("connect_timeout", 15))
        self.prompt_audio_path = config.get("prompt_audio_path", "") or ""
        self.prompt_audio_filename = config.get("prompt_audio_filename") or os.path.basename(self.prompt_audio_path) or "reference.wav"
        speed = config.get("speed", "1.0")
        self.speed = float(speed) if speed not in (None, "") else 1.0
        self.output_file = config.get("output_dir", "tmp/")
        self._pcm_buffer = bytearray()
        self._source_pcm_buffer = bytearray()
        self._source_sample_rate = int(config.get("source_sample_rate") or 0)
        self._source_channels = int(config.get("source_channels") or 0)
        self._ratecv_state = None
        self._ratecv_key: tuple[int, int, int, int] | None = None
        self._last_meta_logged = ""
        self._apply_percentage_params(config)

    async def text_to_speak(self, text, output_file):
        """Collect a whole websocket response for non-stream fallback/testing paths.

        xiaozhi's base class may call this path for short prompt sentences, then
        pass the returned bytes to pydub.  Returning raw PCM with file_type=pcm
        triggers `sample_width` errors.  We therefore return WAV bytes here while
        keeping the real-time streaming path raw-PCM -> Opus.
        """
        pcm_chunks: list[bytes] = []
        self._reset_pcm_converter()
        async for item in self._iter_stream_events(str(text or "")):
            if item[0] == "meta":
                self._apply_stream_meta(item[1])
            elif item[0] == "audio":
                converted = self._normalize_pcm_for_opus(item[1])
                if converted:
                    pcm_chunks.append(converted)
        self._flush_source_pcm_buffer()
        pcm = b"".join(pcm_chunks)
        data = _pcm_to_wav_bytes(pcm, self._target_sample_rate(), self._target_channels())
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
                    self._source_pcm_buffer.clear()
                    self._reset_pcm_converter()
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
                    self._flush_source_pcm_buffer()
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
            bg = _get_bg_loop()
            bg.run_coro(self._stream_text(text, sentence_id=sentence_id), timeout=self.timeout + 10)
            logger.bind(tag=TAG).info(f"AngeVoice流式合成成功: {original_text}")
        except Exception as exc:
            logger.bind(tag=TAG).error(f"AngeVoice流式合成失败: {original_text}，错误: {exc}")

    async def _stream_text(self, text: str, sentence_id: str | None = None) -> None:
        self._reset_pcm_converter()
        async for typ, payload in self._iter_stream_events(text):
            if self.conn.stop_event.is_set() or self.conn.client_abort:
                break
            if typ == "meta":
                self._apply_stream_meta(payload)
            elif typ == "audio" and payload:
                self._push_audio_bytes(payload, sentence_id)
            elif typ == "done":
                break
            elif typ == "error":
                raise Exception(payload.decode("utf-8", errors="ignore") if isinstance(payload, bytes) else str(payload))
        self._flush_source_pcm_buffer()
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
                        if typ in {"started", "start"}:
                            yield "meta", data
                        elif typ in {"audio", "segment_audio"}:
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
        prompt_audio = _prepare_prompt_audio(self.prompt_audio_path, self.prompt_audio_filename)
        if prompt_audio:
            payload["prompt_audio"] = prompt_audio
        return payload

    def _apply_stream_meta(self, meta: dict) -> None:
        if not isinstance(meta, dict):
            return
        sample_rate = _safe_int(meta.get("sample_rate"), self._source_sample_rate or 0)
        channels = _safe_int(meta.get("channels"), self._source_channels or 0)
        if sample_rate > 0:
            self._source_sample_rate = sample_rate
        if channels > 0:
            self._source_channels = channels
        desc = f"src={self._source_sample_rate or '?'}Hz/{self._source_channels or '?'}ch -> opus={self._target_sample_rate()}Hz/{self._target_channels()}ch"
        if desc != self._last_meta_logged:
            self._last_meta_logged = desc
            logger.bind(tag=TAG).info(f"AngeVoice流式音频参数: {desc}")

    def _push_audio_bytes(self, audio: bytes, sentence_id: str | None) -> None:
        if not audio:
            return
        if self.stream_format.startswith("pcm"):
            normalized = self._normalize_pcm_for_opus(audio)
            if not normalized:
                return
            self._pcm_buffer.extend(normalized)
            self._drain_pcm_buffer(sentence_id=sentence_id, end_of_stream=False)
        else:
            self.tts_audio_queue.put((SentenceType.MIDDLE, audio, None, sentence_id or getattr(self, "current_sentence_id", None)))

    def _target_sample_rate(self) -> int:
        return int(getattr(self.opus_encoder, "sample_rate", 0) or getattr(self.conn, "sample_rate", 24000) or 24000)

    def _target_channels(self) -> int:
        return int(getattr(self.opus_encoder, "channels", 1) or 1)

    def _reset_pcm_converter(self) -> None:
        self._source_pcm_buffer.clear()
        self._ratecv_state = None
        self._ratecv_key = None

    def _normalize_pcm_for_opus(self, audio: bytes) -> bytes:
        """Convert AngeVoice raw PCM to the layout expected by xiaozhi's Opus encoder."""
        if not audio:
            return b""
        src_rate = int(self._source_sample_rate or self._target_sample_rate() or 24000)
        src_channels = int(self._source_channels or 1)
        src_channels = 1 if src_channels <= 0 else min(src_channels, 2)
        dst_rate = self._target_sample_rate()
        dst_channels = self._target_channels()
        dst_channels = 1 if dst_channels <= 0 else min(dst_channels, 2)

        sample_group_bytes = 2 * src_channels
        self._source_pcm_buffer.extend(audio)
        usable = len(self._source_pcm_buffer) // sample_group_bytes * sample_group_bytes
        if usable <= 0:
            return b""
        raw = bytes(self._source_pcm_buffer[:usable])
        del self._source_pcm_buffer[:usable]

        if src_rate == dst_rate and src_channels == dst_channels:
            return raw

        try:
            converted = raw
            if src_channels == 2 and dst_channels == 1:
                converted = audioop.tomono(converted, 2, 0.5, 0.5)
                rate_in_channels = 1
            elif src_channels == 1 and dst_channels == 2:
                # ratecv runs on the current channel count.  Upmix after ratecv.
                rate_in_channels = 1
            else:
                rate_in_channels = src_channels

            key = (src_rate, dst_rate, rate_in_channels, dst_channels)
            if self._ratecv_key != key:
                self._ratecv_state = None
                self._ratecv_key = key

            if src_rate != dst_rate:
                converted, self._ratecv_state = audioop.ratecv(
                    converted,
                    2,
                    rate_in_channels,
                    src_rate,
                    dst_rate,
                    self._ratecv_state,
                )

            if src_channels == 1 and dst_channels == 2:
                converted = audioop.tostereo(converted, 2, 1.0, 1.0)
            elif src_channels == 2 and dst_channels == 2:
                converted = converted
            elif dst_channels == 1:
                converted = converted
            return converted
        except Exception as exc:
            logger.bind(tag=TAG).warning(f"AngeVoice PCM转换失败，使用原始PCM，可能出现噪声: {exc}")
            return raw

    def _flush_source_pcm_buffer(self) -> None:
        if not self._source_pcm_buffer:
            return
        # Drop incomplete sample groups rather than feeding misaligned PCM into the Opus encoder.
        dropped = len(self._source_pcm_buffer)
        self._source_pcm_buffer.clear()
        logger.bind(tag=TAG).debug(f"AngeVoice丢弃不足一个PCM采样组的尾部字节: {dropped}")

    def _frame_bytes(self) -> int:
        return int(self._target_sample_rate() * self._target_channels() * self.opus_encoder.frame_size_ms / 1000 * 2)

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


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default or 0)


def _pcm_to_wav_bytes(pcm: bytes, sample_rate: int, channels: int) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(max(1, int(channels or 1)))
        wf.setsampwidth(2)
        wf.setframerate(max(8000, int(sample_rate or 24000)))
        wf.writeframes(pcm or b"")
    return buffer.getvalue()


def _prepare_prompt_audio(path: str, filename: str) -> dict | None:
    normalized = _normalize_prompt_audio_path(path, filename)
    if not normalized:
        return None
    if not os.path.exists(normalized):
        logger.bind(tag=TAG).warning(
            f"AngeVoice参考音频不存在，已跳过克隆并退回普通流式: raw={path!r}, normalized={normalized!r}"
        )
        return None
    if os.path.isdir(normalized):
        logger.bind(tag=TAG).warning(f"AngeVoice参考音频路径是目录，已跳过克隆并退回普通流式: {normalized}")
        return None
    return _load_prompt_audio(normalized, filename or os.path.basename(normalized))


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
            suffix = suffix + filename
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


def _load_prompt_audio(path: str, filename: str) -> dict:
    file_size = os.path.getsize(path)
    if file_size > MAX_PROMPT_AUDIO_SIZE:
        raise ValueError(f"prompt_audio 文件过大: {file_size / 1024 / 1024:.1f}MB > {MAX_PROMPT_AUDIO_SIZE / 1024 / 1024:.0f}MB 限制")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return {"filename": filename or os.path.basename(path), "data": data}


async def _send_cancel(ws) -> None:
    try:
        await ws.send_json({"type": "cancel"})
    except Exception:
        pass
