"""AngeVoice 核心 TTS 引擎。

基于 Kokoro v1.1 中文模型构建。numpy、torch 和 kokoro 等重依赖
在加载模型或编码音频时按需导入。
"""

from __future__ import annotations

import base64
import concurrent.futures
import logging
import os
import re
import threading
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Optional

from .audio import encode_audio_segment, normalize_audio_array, write_wav_bytes
from .config import TTSConfig, load_config
from .text.legacy import normalize_text_for_tts
from .text_segmenter import segment_text_natural
from .kokoro_assets import has_valid_kokoro_local_assets, is_valid_kokoro_voice_file, kokoro_voice_dir_candidates
from .model_sources import ensure_kokoro_model_dir, resolve_model_source

logger = logging.getLogger(__name__)


@contextmanager
def _single_layer_rnn_dropout_compat():
    """把上游单层 RNN 的无效 dropout 参数修正为 0。

    PyTorch 对 ``num_layers=1`` 且 ``dropout>0`` 的 RNN/LSTM/GRU 会告警，
    因为这个 dropout 实际不会生效。Kokoro 上游部分版本会这样构建模型。
    这里不是过滤 warning，而是在加载 Kokoro 期间把无效参数改为等价的 0，
    避免未来 PyTorch 收紧行为时把无效配置变成硬错误。
    """

    try:
        import torch.nn as nn
    except Exception:  # pragma: no cover - torch import failure belongs to model load path
        yield
        return

    patches = (
        (nn.LSTM, 5),
        (nn.GRU, 5),
        (nn.RNN, 6),
    )
    originals = []

    def _needs_fix(args, kwargs, dropout_index: int) -> bool:
        num_layers = kwargs.get("num_layers", args[2] if len(args) > 2 else 1)
        dropout = kwargs.get("dropout", args[dropout_index] if len(args) > dropout_index else 0.0)
        try:
            return int(num_layers) == 1 and float(dropout) > 0.0
        except (TypeError, ValueError):
            return False

    try:
        for cls, dropout_index in patches:
            original = cls.__init__
            originals.append((cls, original))

            def patched_init(self, *args, _original=original, _dropout_index=dropout_index, **kwargs):
                if _needs_fix(args, kwargs, _dropout_index):
                    if "dropout" in kwargs:
                        kwargs = dict(kwargs)
                        kwargs["dropout"] = 0.0
                    elif len(args) > _dropout_index:
                        mutable_args = list(args)
                        mutable_args[_dropout_index] = 0.0
                        args = tuple(mutable_args)
                    else:
                        kwargs = dict(kwargs)
                        kwargs["dropout"] = 0.0
                return _original(self, *args, **kwargs)

            cls.__init__ = patched_init
        yield
    finally:
        for cls, original in originals:
            cls.__init__ = original


class TTSEngine:
    """基于 Kokoro v1.1 的 TTS 引擎。"""

    engine_id = "kokoro"
    display_name = "Kokoro v1.1 Chinese"
    HF_REPO = "hexgrad/Kokoro-82M-v1.1-zh"
    SUPPORTED_STREAM_FORMATS = {"pcm_s16le", "wav"}

    def __init__(self, config: Optional[TTSConfig] = None):
        self.config = config or load_config()
        self._model = None
        self._en_pipeline = None
        self._zh_pipeline = None
        self._runtime_lock = threading.RLock()
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
        with self._runtime_lock:
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
        """返回可交给 Kokoro 上游内部使用的仓库 ID。

        本地模型目录会通过显式 config/model 参数传入，不能被误当成
        repo_id，否则 huggingface_hub 会在校验阶段报错。
        """
        repo_id = str(getattr(self.config, "kokoro_hf_repo", self.HF_REPO) or self.HF_REPO).strip()
        if not repo_id or repo_id.startswith(("/", "./", "../")):
            return self.HF_REPO
        return repo_id

    def _resolve_voice_for_pipeline(self, voice: str) -> str:
        """优先把音色名解析成本地 ``.pt`` 文件。

        兼容统一模型目录、旧 ``models/voices`` 目录，以及 Hugging Face
        缓存快照目录。若本地文件无效，则把音色名交给上游 Kokoro 处理。
        """
        raw = str(voice or "").strip()
        if not raw:
            return raw
        name = Path(raw).name
        filename = name if name.endswith(".pt") else f"{name}.pt"
        for voice_dir in kokoro_voice_dir_candidates(self.config.model_dir):
            candidate = voice_dir / filename
            if is_valid_kokoro_voice_file(candidate, log=logger):
                return str(candidate)
        return raw

    def load(self) -> "TTSEngine":
        with self._runtime_lock:
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
            # 否则 huggingface_hub 会报错：
            #   仓库名格式必须为 'repo_name' 或 'namespace/repo_name'：'/app/models'
            # 本地模型通过 config/model 显式路径加载；repo_id 只保留为合法标识，
            # 供 Kokoro 内部默认映射和 Pipeline 初始化使用。
            repo_id = self._safe_kokoro_repo_id()
            if use_local:
                logger.info("从本地加载模型: %s (repo_id=%s) -> %s", self.config.model_dir, repo_id, self._device)
                KModel.MODEL_NAMES[repo_id] = local_model.name
            else:
                source = resolve_model_source(self.config)
                if source == "offline":
                    raise RuntimeError(
                        "ANGEVOICE_MODEL_SOURCE=offline，但本地 Kokoro 模型不完整。"
                        f"请把 config.json、权重和 voices/*.pt 预先放入：{self.config.model_dir}"
                    )
                logger.info("本地未找到模型，从 %s 下载: %s", "Hugging Face" if source == "huggingface" else source, repo_id)

            if self._device == "cpu":
                try:
                    torch.set_num_threads(min(8, (os.cpu_count() or 4)))
                except Exception:
                    pass

            try:
                with _single_layer_rnn_dropout_compat():
                    if use_local:
                        self._model = KModel(repo_id=repo_id, config=str(local_config), model=str(local_model)).to(self._device).eval()
                    else:
                        self._model = KModel(repo_id=repo_id).to(self._device).eval()
            except Exception as exc:
                message = str(exc)
                if "WeightsUnpickler" in message or "Unsupported operand 118" in message:
                    raise RuntimeError(
                        "Kokoro 模型权重加载失败：检测到 Git LFS 指针、损坏权重或不兼容缓存。"
                        "请删除无效的 models/models--hexgrad--Kokoro-82M-v1.1-zh/*.pth、voices/*.pt 或 Hugging Face 缓存后重试；"
                        "也可以执行 git lfs pull 下载真实模型文件。"
                    ) from exc
                raise

            def en_callable(text):
                return self._english_phonemes(text, repo_id=repo_id)

            self._zh_pipeline = KPipeline(lang_code="z", repo_id=repo_id, model=self._model, en_callable=en_callable)
            self._loaded = True
            logger.info("模型加载完成 (device=%s)", self._device)
            return self

    def _english_phonemes(self, text, *, repo_id):
        if text == "Kokoro":
            return "kˈOkəɹO"
        elif text == "Sol":
            return "sˈOl"
        with self._runtime_lock:
            if self._en_pipeline is None:
                from kokoro import KPipeline

                self._en_pipeline = KPipeline(lang_code="a", repo_id=repo_id, model=False)
            try:
                return next(self._en_pipeline(text)).phonemes
            except Exception:
                return text

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
            with self._runtime_lock:
                return self._do_synthesize(text, voice, speed)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise RuntimeError(
                    f"Kokoro 推理超时（{timeout}s）。"
                    "合成可能因 GPU 显存或模型状态异常而卡住。"
                )

    def synthesize_file(self, text: str, output_path: str, voice: str = "zm_010", speed: float = 1.0) -> str:
        audio_bytes = self.synthesize(text, voice, speed)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
        logger.info("音频已保存: %s (%d bytes)", path, len(audio_bytes))
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

    def _segment_text(self, text: str, *, flush_sentence_boundaries: bool = False) -> list[str]:
        return segment_text_natural(
            text,
            max_text_length=int(self.config.max_text_length),
            segment_length=max(20, int(self.config.segment_length)),
            single_newline_policy=str(getattr(self.config, "text_single_newline_policy", "auto")),
            flush_sentence_boundaries=flush_sentence_boundaries,
        )

    def _make_speed_fn(self, speed: float):
        speed = float(speed)
        return lambda len_ps: speed

    def _do_synthesize(self, text: str, voice: str, speed: float) -> "np.ndarray":
        import numpy as np

        lang = self._detect_language(text)
        segments = self._segment_text(text)
        logger.info("合成: lang=%s, segments=%d, voice=%s, speed=%s", lang, len(segments), voice, speed)

        all_wavs = []
        speed_fn = self._make_speed_fn(speed)
        for i, segment in enumerate(segments):
            try:
                with self._runtime_lock:
                    wav_seg = self._synthesize_segment(self._zh_pipeline, segment, voice, speed_fn)
                if wav_seg is not None:
                    all_wavs.append(self._postprocess_segment(wav_seg))
            except Exception as e:
                logger.warning("段落 %d 合成失败: %s", i + 1, e)

        if not all_wavs:
            raise RuntimeError("所有段落合成均失败，无有效音频数据")
        return np.concatenate(all_wavs)

    def _synthesize_segment(self, pipeline, segment: str, voice: str, speed_fn):
        import numpy as np

        try:
            import torch
        except ImportError:  # 单元测试和轻量 CI 不需要 torch。
            torch = None

        try:
            generator = pipeline(segment, voice=self._resolve_voice_for_pipeline(voice), speed=speed_fn)
            result = next(generator)
        except Exception as exc:
            message = str(exc)
            if "WeightsUnpickler" in message or "Unsupported operand 118" in message:
                raise RuntimeError(
                    "Kokoro 音色权重加载失败：本地 voice 可能是 Git LFS 指针或损坏文件。"
                    "请删除无效的 models/models--hexgrad--Kokoro-82M-v1.1-zh/voices/*.pt，让服务从上游重新下载，或执行 git lfs pull。"
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

    def synthesize_stream(self, text, voice="zm_010", speed=1.0, fmt="pcm_s16le", *, cancel_check=None):
        if fmt not in self.SUPPORTED_STREAM_FORMATS:
            yield {"type": "error", "message": f"不支持的流式格式：{fmt}"}
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

        segments = self._segment_text(text, flush_sentence_boundaries=True)
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
            if cancel_check is not None and bool(cancel_check()):
                break
            try:
                with self._runtime_lock:
                    wav_seg = self._synthesize_segment(self._zh_pipeline, segment, voice, speed_fn)
                if wav_seg is not None:
                    wav_seg = self._postprocess_segment(wav_seg)
                    cancelled = False
                    for stream_seg in self._split_stream_audio(wav_seg):
                        if cancel_check is not None and bool(cancel_check()):
                            cancelled = True
                            break
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
                    if cancelled:
                        break
            except Exception as e:
                logger.warning("段落 %d 合成失败: %s", i + 1, e)
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
