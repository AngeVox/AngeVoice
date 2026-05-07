"""AngeVoice core TTS engine.

Built on Kokoro v1.1 Chinese model. Heavy dependencies such as numpy, torch and
kokoro are imported lazily when the model is loaded or audio is encoded.
"""

import base64
import logging
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

from .audio import encode_audio_segment, normalize_audio_array, write_wav_bytes
from .config import TTSConfig, load_config
from .zh_rules import normalize_chinese_rules

logger = logging.getLogger(__name__)

_DIGITS_ZH = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}
_DIGITS_ZH_READING = {**_DIGITS_ZH, "1": "幺"}


def _spell_digits(text: str, use_yao: bool = False) -> str:
    """Read a digit sequence one digit at a time.

    Do not insert spaces here. Spaces can make Chinese TTS sound choppy and can
    also leak into normalized dates/IDs.
    """
    table = _DIGITS_ZH_READING if use_yao else _DIGITS_ZH
    return "".join(table.get(ch, ch) for ch in text)


def _read_under_10000(value: int) -> str:
    if value == 0:
        return "零"
    units = ["", "十", "百", "千"]
    parts: list[str] = []
    zero_pending = False
    pos = 0
    n = value

    while n > 0:
        digit = n % 10
        if digit == 0:
            if parts:
                zero_pending = True
        else:
            part = _DIGITS_ZH[str(digit)] + units[pos]
            if zero_pending:
                parts.append("零")
                zero_pending = False
            parts.append(part)
        n //= 10
        pos += 1

    spoken = "".join(reversed(parts)).rstrip("零")
    if spoken.startswith("一十"):
        spoken = spoken[1:]
    return spoken or "零"


def _read_small_int(value: int) -> str:
    """Read common Chinese integers used by TN rules.

    The previous implementation fell back to spelling digits for values >=1000,
    which made amounts such as 1000元 sound like IDs. This helper keeps natural
    Chinese readings up to the ten-thousands range used by money/date rules.
    """
    if value < 0:
        return "负" + _read_small_int(-value)
    if value < 10000:
        return _read_under_10000(value)
    high, low = divmod(value, 10000)
    spoken = _read_under_10000(high) + "万"
    if low:
        if low < 1000:
            spoken += "零"
        spoken += _read_under_10000(low)
    return spoken


def _read_time_hour(value: int) -> str:
    if value == 2:
        return "两"
    return _read_small_int(value)


def _read_clock_time(hour: int, minute: int) -> str:
    spoken = _read_time_hour(hour) + "点"
    if minute == 0:
        return spoken + "整"
    if minute < 10:
        return spoken + "零" + _DIGITS_ZH[str(minute)] + "分"
    return spoken + _read_small_int(minute) + "分"


def normalize_text_for_tts(text: str) -> str:
    """Normalize common Chinese TTS patterns before synthesis.

    This intentionally stays conservative. It handles common phone numbers,
    dates, money, percentages and long numeric IDs without trying to become a
    full Chinese TN engine.
    """
    if not text:
        return text

    def repl_date(match):
        year, month, day = match.groups()
        return f"{_spell_digits(year)}年{_read_small_int(int(month))}月{_read_small_int(int(day))}日"

    # Avoid \b for Chinese context. In Python regex, many Chinese characters are
    # word characters, so \b does not reliably match between Chinese and digits.
    text = re.sub(r"(?<!\d)(20\d{2}|19\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", repl_date, text)

    def repl_time(match):
        hour = int(match.group(1))
        minute = int(match.group(2))
        return _read_clock_time(hour, minute)

    text = re.sub(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)", repl_time, text)

    def repl_money(match):
        prefix, amount, suffix = match.groups()
        if not prefix and not suffix:
            return match.group(0)
        integer, dot, frac = amount.partition(".")
        spoken = _read_small_int(int(integer)) + "元"
        if dot and frac:
            frac = (frac + "00")[:2]
            if frac[0] != "0":
                spoken += _DIGITS_ZH[frac[0]] + "角"
            if frac[1] != "0":
                spoken += _DIGITS_ZH[frac[1]] + "分"
        return spoken

    text = re.sub(r"(?<![\dA-Za-z])(¥|￥)?(\d{1,9}(?:\.\d{1,2})?)(元)?(?![\dA-Za-z])", repl_money, text)

    def repl_percent(match):
        value = match.group(1)
        return "百分之" + _spell_digits(value.replace(".", "点"))

    text = re.sub(r"(?<!\d)(\d+(?:\.\d+)?)%(?!\d)", repl_percent, text)

    def repl_mobile(match):
        number = match.group(0)
        return "，".join([
            _spell_digits(number[:3], use_yao=True),
            _spell_digits(number[3:7], use_yao=True),
            _spell_digits(number[7:], use_yao=True),
        ])

    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", repl_mobile, text)

    def repl_long_number(match):
        number = match.group(0)
        grouped = [number[i : i + 4] for i in range(0, len(number), 4)]
        return "，".join(_spell_digits(group, use_yao=True) for group in grouped)

    text = re.sub(r"(?<!\d)\d{6,}(?!\d)", repl_long_number, text)
    text = normalize_chinese_rules(text)
    return text


class TTSEngine:
    """Kokoro v1.1 backed TTS engine."""

    engine_id = "kokoro"
    display_name = "Kokoro v1.1 Chinese"
    HF_REPO = "hexgrad/Kokoro-82M-v1.1-zh"
    SUPPORTED_STREAM_FORMATS = {"pcm_s16le", "wav"}

    def __init__(self, config: Optional[TTSConfig] = None):
        self.config = config or load_config()
        self._model = None
        self._en_pipeline = None
        self._zh_pipeline = None
        self._device = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def sample_rate(self) -> int:
        return int(self.config.sample_rate)

    @property
    def channels(self) -> int:
        return 1

    @property
    def device(self) -> str:
        return self._device or self.config.device

    @property
    def default_voice(self) -> str:
        return self.config.default_voice

    def get_voices(self) -> list[str]:
        return self.config.get_voices()

    def metadata(self) -> dict:
        return {
            "id": self.engine_id,
            "name": self.display_name,
            "backend": "kokoro",
            "loaded": self.is_loaded,
            "device": self.device,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "voices": self.get_voices(),
            "default_voice": self.default_voice,
            "streaming": True,
            "speed_supported": True,
        }

    def unload(self) -> None:
        self._model = None
        self._en_pipeline = None
        self._zh_pipeline = None
        self._loaded = False
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            logger.debug("Kokoro CUDA cache cleanup skipped", exc_info=True)

    def load(self) -> "TTSEngine":
        if self._loaded:
            return self

        import torch
        from kokoro import KModel, KPipeline

        self._device = self.config.resolve_device()
        local_model = self.config.model_file
        local_config = self.config.model_dir / "config.json"
        use_local = local_model.exists() and local_config.exists() and local_model.stat().st_size > 1000

        if use_local:
            repo_id = str(self.config.model_dir)
            logger.info(f"从本地加载模型: {repo_id} -> {self._device}")
            KModel.MODEL_NAMES[repo_id] = local_model.name
        else:
            repo_id = self.HF_REPO
            logger.info(f"本地未找到模型，从 HuggingFace 下载: {repo_id}")

        if self._device == "cpu":
            try:
                torch.set_num_threads(min(8, (os.cpu_count() or 4)))
            except Exception:
                pass

        if use_local:
            self._model = KModel(repo_id=repo_id, config=str(local_config), model=str(local_model)).to(self._device).eval()
        else:
            self._model = KModel(repo_id=repo_id).to(self._device).eval()

        self._en_pipeline = KPipeline(lang_code="a", repo_id=repo_id, model=False)

        def en_callable(text):
            if text == "Kokoro":
                return "kˈOkəɹO"
            elif text == "Sol":
                return "sˈOl"
            try:
                return next(self._en_pipeline(text)).phonemes
            except Exception:
                return text

        self._zh_pipeline = KPipeline(lang_code="z", repo_id=repo_id, model=self._model, en_callable=en_callable)
        self._loaded = True
        logger.info(f"模型加载完成 (device={self._device})")
        return self

    def synthesize(self, text: str, voice: str = "zm_010", speed: float = 1.0) -> bytes:
        wav = self.synthesize_array(text=text, voice=voice, speed=speed)
        return write_wav_bytes(wav, self.sample_rate)

    def synthesize_array(self, text: str, voice: str = "zm_010", speed: float = 1.0):
        self._validate_request(text=text, voice=voice, speed=speed)
        text = self._clean_text(text)
        if not text:
            raise ValueError("清理后文本为空")
        return self._do_synthesize(text, voice, speed)

    def synthesize_file(self, text: str, output_path: str, voice: str = "zm_010", speed: float = 1.0) -> str:
        audio_bytes = self.synthesize(text, voice, speed)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
        logger.info(f"音频已保存: {path} ({len(audio_bytes)} bytes)")
        return str(path)

    def _validate_request(self, text: str, voice: str, speed: float) -> None:
        if not self._loaded:
            raise RuntimeError("引擎未加载，请先调用 load()")
        if not text or not text.strip():
            raise ValueError("文本不能为空")
        if len(text) > self.config.max_text_length:
            raise ValueError(f"文本过长 ({len(text)} 字符)，上限 {self.config.max_text_length}")
        try:
            speed_value = float(speed)
        except (TypeError, ValueError):
            raise ValueError("speed 必须是数字") from None
        if not (0.5 <= speed_value <= 2.0):
            raise ValueError("speed 必须在 0.5 到 2.0 之间")
        if not voice or not str(voice).strip():
            raise ValueError("voice 不能为空")

    def _clean_text(self, text: str) -> str:
        text = "".join(c if c.isprintable() or c.isspace() else " " for c in text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text).strip()
        text = normalize_text_for_tts(text)
        return re.sub(r"\s+", " ", text).strip()

    def _detect_language(self, text: str) -> str:
        english = len(re.findall(r"[a-zA-Z]", text))
        total = len(text)
        if total == 0:
            return "zh"
        return "en" if english / total > 0.6 else "zh"

    def _segment_text(self, text: str) -> list[str]:
        max_len = max(20, int(self.config.segment_length))
        punctuation = "。！？!?；;，,、.：:\n"
        segments: list[str] = []
        current = ""

        for char in text:
            current += char
            if len(current) >= max_len and char in punctuation:
                if current.strip():
                    segments.append(current.strip())
                current = ""
                continue
            if len(current) >= int(max_len * 1.5):
                cut_pos = max(current.rfind(p) for p in punctuation)
                if cut_pos >= max_len // 2:
                    head = current[: cut_pos + 1].strip()
                    tail = current[cut_pos + 1 :].strip()
                    if head:
                        segments.append(head)
                    current = tail
                else:
                    if current.strip():
                        segments.append(current.strip())
                    current = ""

        if current.strip():
            segments.append(current.strip())
        return segments or [text]

    def _make_speed_fn(self, speed: float):
        speed = float(speed)
        return lambda len_ps: speed

    def _do_synthesize(self, text: str, voice: str, speed: float):
        import numpy as np

        lang = self._detect_language(text)
        segments = self._segment_text(text)
        logger.info(f"合成: lang={lang}, segments={len(segments)}, voice={voice}, speed={speed}")

        all_wavs = []
        speed_fn = self._make_speed_fn(speed)
        for i, segment in enumerate(segments):
            try:
                wav_seg = self._synthesize_segment(self._zh_pipeline, segment, voice, speed_fn)
                if wav_seg is not None:
                    all_wavs.append(self._postprocess_segment(wav_seg))
            except Exception as e:
                logger.warning(f"段落 {i + 1} 合成失败: {e}")

        if not all_wavs:
            raise RuntimeError("所有段落合成均失败，无有效音频数据")
        return np.concatenate(all_wavs)

    def _synthesize_segment(self, pipeline, segment: str, voice: str, speed_fn):
        import numpy as np

        try:
            import torch
        except ImportError:  # Unit tests and lightweight CI do not need torch.
            torch = None

        generator = pipeline(segment, voice=voice, speed=speed_fn)
        result = next(generator)
        audio = result.audio
        if audio is None:
            return None
        if torch is not None and isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().numpy()
        if not isinstance(audio, np.ndarray):
            return None
        if audio.ndim > 1:
            audio = audio.reshape(-1)
        return audio.astype(np.float32, copy=False)

    def _postprocess_segment(self, audio_array):
        import numpy as np

        audio_array = self._normalize_audio(audio_array)
        fade_len = int(self.config.sample_rate * 0.005)
        if audio_array.size > fade_len * 2 and fade_len > 0:
            fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
            fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
            audio_array[:fade_len] *= fade_in
            audio_array[-fade_len:] *= fade_out
        silence_len = int(self.config.sample_rate * 0.03)
        if silence_len > 0:
            silence = np.zeros(silence_len, dtype=np.float32)
            audio_array = np.concatenate([audio_array, silence])
        return audio_array

    def _normalize_audio(self, audio_array):
        return normalize_audio_array(audio_array).reshape(-1)

    def synthesize_stream(self, text, voice="zm_010", speed=1.0, fmt="pcm_s16le"):
        if fmt not in self.SUPPORTED_STREAM_FORMATS:
            yield {"type": "error", "message": f"Unsupported format: {fmt}"}
            return
        try:
            self._validate_request(text=text, voice=voice, speed=speed)
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return

        text = self._clean_text(text)
        if not text:
            yield {"type": "error", "message": "清理后文本为空"}
            return

        segments = self._segment_text(text)
        yield {
            "type": "started",
            "segments": len(segments),
            "sample_rate": self.config.sample_rate,
            "channels": 1,
            "format": fmt,
            "dtype": "s16le" if fmt == "pcm_s16le" else "wav",
        }

        speed_fn = self._make_speed_fn(speed)
        for i, segment in enumerate(segments):
            try:
                wav_seg = self._synthesize_segment(self._zh_pipeline, segment, voice, speed_fn)
                if wav_seg is not None:
                    wav_seg = self._postprocess_segment(wav_seg)
                    audio_bytes = self._encode_segment(wav_seg, fmt)
                    yield {
                        "type": "audio",
                        "index": i,
                        "data": base64.b64encode(audio_bytes).decode("ascii"),
                        "format": fmt,
                        "sample_rate": self.config.sample_rate,
                        "channels": 1,
                    }
            except Exception as e:
                logger.warning(f"段落 {i + 1} 合成失败: {e}")
                yield {"type": "segment_error", "index": i, "message": str(e)}

        yield {"type": "done", "total_segments": len(segments)}

    def _encode_segment(self, audio_array, format="pcm_s16le"):
        return encode_audio_segment(audio_array, format, self.sample_rate)
