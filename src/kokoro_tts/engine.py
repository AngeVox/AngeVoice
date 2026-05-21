"""AngeVoice core TTS engine.

Built on Kokoro v1.1 Chinese model. Heavy dependencies such as numpy, torch and
kokoro are imported lazily when the model is loaded or audio is encoded.
"""

import base64
import concurrent.futures
import logging
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

from .audio import encode_audio_segment, normalize_audio_array, write_wav_bytes
from .config import TTSConfig, load_config
from .zh_rules import normalize_chinese_rules
from .text_segmenter import segment_text_natural
from .kokoro_assets import has_valid_kokoro_local_assets, is_valid_kokoro_voice_file
from .model_sources import ensure_kokoro_model_dir, resolve_model_source

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




def _read_month_day(month: int, day: int) -> str:
    return f"{_read_small_int(month)}月{_read_small_int(day)}日"


_DATE_CONTEXT_BEFORE = (
    "日期", "日子", "生日", "活动", "会议", "考试", "开会", "发布", "上线", "更新",
    "维护", "开服", "截止", "截至", "预约", "计划", "预计", "定在", "改到",
    "推迟到", "提前到", "报名", "放假", "假期", "档期", "排期", "工期", "节日",
)
_DATE_CONTEXT_AFTER = (
    "号", "日", "当天", "那天", "这天", "之前", "之后", "以前", "以后", "前", "后",
    "开始", "结束", "上线", "发布", "更新", "开服", "维护", "截止", "截至", "报名",
    "活动", "会议", "考试", "开会", "放假", "假期", "见", "再说",
)
_DATE_CONTEXT_WORDS = ("今天", "明天", "昨天", "后天", "前天", "今年", "明年", "去年", "本月", "下月", "上月")


def _looks_like_short_date_context(text: str, start: int, end: int) -> bool:
    """Heuristically decide whether M.D / M-D should be read as month-day.

    This intentionally avoids converting naked decimals and common software
    versions. A shorthand date needs an explicit date marker around it, e.g.
    ``4.20号``、``4.20更新``、``活动在4.20``.
    """

    before = text[max(0, start - 8):start]
    after = text[end:end + 8]
    if any(after.startswith(item) for item in _DATE_CONTEXT_AFTER):
        return True
    if any(item in before for item in _DATE_CONTEXT_BEFORE):
        return True
    if any(item in before or item in after for item in _DATE_CONTEXT_WORDS):
        return True
    if before.endswith(("在", "于", "到", "从", "至", "距", "等到")) and not after.startswith(("版", "版本", "元", "%")):
        return True
    return False


def _normalize_short_month_day(text: str) -> str:
    """Normalize context-backed M.D shorthand dates before decimal handling."""

    def repl(match: re.Match[str]) -> str:
        month = int(match.group("month"))
        day = int(match.group("day"))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return match.group(0)
        if not _looks_like_short_date_context(text, match.start(), match.end()):
            return match.group(0)
        return _read_month_day(month, day)

    return re.sub(
        r"(?<![\dA-Za-z])(?P<month>1[0-2]|0?[1-9])[./-](?P<day>3[01]|[12]\d|0?[1-9])(?![\dA-Za-z])",
        repl,
        text,
    )

def normalize_text_for_tts(text: str, model: str = "kokoro") -> str:
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

    # 中文语境下避免使用 \b。Python 正则中许多中文字符属于 word 字符，
    # 因此 \b 无法可靠匹配中文与数字之间的边界。
    text = re.sub(r"(?<!\d)(20\d{2}|19\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", repl_date, text)
    text = _normalize_short_month_day(text)

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
    text = normalize_chinese_rules(text, model=model)
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
            "stream_chunk_seconds": self.config.stream_chunk_seconds,
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
                try:
                    torch.cuda.ipc_collect()
                except Exception:
                    logger.debug("Kokoro CUDA IPC cleanup skipped", exc_info=True)
        except Exception:
            logger.debug("Kokoro CUDA cache cleanup skipped", exc_info=True)


    def _safe_kokoro_repo_id(self) -> str:
        """Return a valid repository id for Kokoro internals.

        Local model directories such as /app/models are passed separately via
        explicit config/model paths. They must not be used as repo_id because
        huggingface_hub validates repo_id even when files are local.
        """
        repo_id = str(getattr(self.config, "kokoro_hf_repo", self.HF_REPO) or self.HF_REPO).strip()
        if not repo_id or repo_id.startswith(('/', './', '../')):
            return self.HF_REPO
        return repo_id

    def _resolve_voice_for_pipeline(self, voice: str) -> str:
        """Resolve a voice name to a local .pt file when available.

        This keeps offline Docker/NAS deployments from asking Kokoro to fetch
        voices from Hugging Face when /app/models/voices already contains them.
        """
        raw = str(voice or "").strip()
        if not raw:
            return raw
        # 不允许任意路径穿越，但支持读取配置的 voices 目录下的文件。
        name = Path(raw).name
        if name.endswith(".pt"):
            candidates = [self.config.voices_dir / name]
        else:
            candidates = [self.config.voices_dir / f"{name}.pt"]
        for candidate in candidates:
            if is_valid_kokoro_voice_file(candidate, log=logger):
                return str(candidate)
        return raw

    def load(self) -> "TTSEngine":
        if self._loaded:
            return self

        import torch
        from kokoro import KModel, KPipeline

        self._device = self.config.resolve_device()
        local_model = self.config.model_file
        local_config = self.config.model_dir / "config.json"
        use_local = has_valid_kokoro_local_assets(self.config.model_dir, log=logger)
        if not use_local:
            resolved_dir = ensure_kokoro_model_dir(self.config, logger=logger)
            if resolved_dir is not None:
                self.config.model_dir = Path(resolved_dir)
                local_model = self.config.model_file
                local_config = self.config.model_dir / "config.json"
            use_local = has_valid_kokoro_local_assets(self.config.model_dir, log=logger)

        # Kokoro 的 repo_id 必须始终是合法的 Hugging Face 仓库名。
        # 即使使用 /app/models 这样的本地模型目录，也不能把绝对路径传给 repo_id，
        # 否则 huggingface_hub 会报：
        #   Repo id must be in the form 'repo_name' or 'namespace/repo_name': '/app/models'
        # 本地模型通过 config/model 显式路径加载；repo_id 只保留为合法标识，
        # 供 Kokoro 内部默认映射和 Pipeline 初始化使用。
        repo_id = self._safe_kokoro_repo_id()
        if use_local:
            logger.info("从本地加载模型: %s (repo_id=%s) -> %s", self.config.model_dir, repo_id, self._device)
            KModel.MODEL_NAMES[repo_id] = local_model.name
        else:
            source = resolve_model_source(self.config)
            logger.info("本地未找到模型，从 %s 下载: %s", "Hugging Face" if source == "huggingface" else source, repo_id)

        if self._device == "cpu":
            try:
                torch.set_num_threads(min(8, (os.cpu_count() or 4)))
            except Exception:
                pass

        try:
            if use_local:
                self._model = KModel(repo_id=repo_id, config=str(local_config), model=str(local_model)).to(self._device).eval()
            else:
                self._model = KModel(repo_id=repo_id).to(self._device).eval()
        except Exception as exc:
            message = str(exc)
            if "WeightsUnpickler" in message or "Unsupported operand 118" in message:
                raise RuntimeError(
                    "Kokoro 模型权重加载失败：检测到 Git LFS 指针、损坏权重或不兼容缓存。"
                    "请删除无效的 models/*.pth、models/voices/*.pt 或 Hugging Face 缓存后重试；"
                    "也可以执行 git lfs pull 下载真实模型文件。"
                ) from exc
            raise

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
        timeout = self.config.request_timeout_seconds

        def _run():
            return self._do_synthesize(text, voice, speed)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise RuntimeError(
                    f"Kokoro inference timed out ({timeout}s). "
                    "Synthesis may be stuck due to GPU memory or model issues."
                )

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
        return segment_text_natural(
            text,
            max_text_length=int(self.config.max_text_length),
            segment_length=max(20, int(self.config.segment_length)),
            single_newline_policy=str(getattr(self.config, "text_single_newline_policy", "auto")),
        )

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

        try:
            generator = pipeline(segment, voice=self._resolve_voice_for_pipeline(voice), speed=speed_fn)
            result = next(generator)
        except Exception as exc:
            message = str(exc)
            if "WeightsUnpickler" in message or "Unsupported operand 118" in message:
                raise RuntimeError(
                    "Kokoro 音色权重加载失败：本地 voice 可能是 Git LFS 指针或损坏文件。"
                    "请删除无效的 models/voices/*.pt，让服务从上游重新下载，或执行 git lfs pull。"
                ) from exc
            raise
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
            "recommended_prebuffer_seconds": float(getattr(self.config, "stream_prebuffer_seconds", 0.25)),
        }

        speed_fn = self._make_speed_fn(speed)
        audio_index = 0
        for i, segment in enumerate(segments):
            try:
                wav_seg = self._synthesize_segment(self._zh_pipeline, segment, voice, speed_fn)
                if wav_seg is not None:
                    wav_seg = self._postprocess_segment(wav_seg)
                    for stream_seg in self._split_stream_audio(wav_seg):
                        audio_bytes = self._encode_segment(stream_seg, fmt)
                        yield {
                            "type": "audio",
                            "index": audio_index,
                            "segment_index": i,
                            "data": base64.b64encode(audio_bytes).decode("ascii"),
                            "format": fmt,
                            "sample_rate": self.config.sample_rate,
                            "channels": 1,
                        }
                        audio_index += 1
            except Exception as e:
                logger.warning(f"段落 {i + 1} 合成失败: {e}")
                yield {"type": "segment_error", "index": i, "message": str(e)}

        yield {"type": "done", "total_segments": len(segments), "total_audio_chunks": audio_index}

    def _split_stream_audio(self, audio_array):
        import numpy as np

        audio = np.asarray(audio_array, dtype=np.float32)
        if audio.size == 0:
            return
        max_seconds = max(0.05, float(self.config.stream_chunk_seconds))
        max_samples = max(1, int(self.sample_rate * max_seconds))
        for start in range(0, int(audio.shape[0]), max_samples):
            yield np.ascontiguousarray(audio[start : start + max_samples])

    def _encode_segment(self, audio_array, format="pcm_s16le"):
        return encode_audio_segment(audio_array, format, self.sample_rate)
