"""Kokoro TTS 核心引擎

支持 CPU/GPU 自动检测，可作为库直接调用或通过 server 模式运行。
重依赖 (numpy, torch, kokoro) 在 load() 时才导入。
"""

import base64
import logging
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

from .config import TTSConfig, load_config

logger = logging.getLogger(__name__)


class TTSEngine:
    """Kokoro TTS 引擎

    用法:
        engine = TTSEngine()
        engine.load()
        audio_bytes = engine.synthesize("你好世界", voice="zm_010")
    """

    # HuggingFace 模型仓库 ID
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

    def load(self) -> "TTSEngine":
        """加载模型和 pipeline

        自动检测模型来源:
        1. 本地 models/ 目录有模型文件 → 直接使用
        2. 本地没有 → 从 HuggingFace Hub 自动下载
        """
        if self._loaded:
            return self

        import torch
        from kokoro import KModel, KPipeline

        self._device = self.config.resolve_device()

        # 检测模型来源：本地 or HuggingFace
        # Git LFS 指针文件只有约 134 字节，实际模型约 330MB
        local_model = self.config.model_file
        local_config = self.config.model_dir / "config.json"
        use_local = (
            local_model.exists()
            and local_config.exists()
            and local_model.stat().st_size > 1000  # 排除 LFS 指针
        )

        if use_local:
            repo_id = str(self.config.model_dir)
            logger.info(f"从本地加载模型: {repo_id} -> {self._device}")
            # 注册本地路径到 MODEL_NAMES
            KModel.MODEL_NAMES[repo_id] = local_model.name
        else:
            repo_id = self.HF_REPO
            logger.info(f"本地未找到模型，从 HuggingFace 下载: {repo_id}")

        # 设置线程数（CPU 模式）
        if self._device == "cpu":
            try:
                torch.set_num_threads(min(8, (os.cpu_count() or 4)))
            except Exception:
                pass

        # 加载模型（本地文件传入 config/model 参数跳过下载）
        if use_local:
            self._model = KModel(
                repo_id=repo_id,
                config=str(local_config),
                model=str(local_model),
            ).to(self._device).eval()
        else:
            self._model = KModel(repo_id=repo_id).to(self._device).eval()

        # 英文 pipeline（仅用于音素转换，不加载模型）
        self._en_pipeline = KPipeline(lang_code="a", repo_id=repo_id, model=False)

        # 英文音素回调
        def en_callable(text):
            if text == "Kokoro":
                return "kˈOkəɹO"
            elif text == "Sol":
                return "sˈOl"
            try:
                return next(self._en_pipeline(text)).phonemes
            except Exception:
                return text

        # 中文 pipeline（主 pipeline）
        self._zh_pipeline = KPipeline(
            lang_code="z", repo_id=repo_id, model=self._model, en_callable=en_callable
        )

        self._loaded = True
        logger.info(f"模型加载完成 (device={self._device})")
        return self

    def synthesize(
        self,
        text: str,
        voice: str = "zm_010",
        speed: float = 1.0,
    ) -> bytes:
        """合成语音，返回 WAV 字节流

        Args:
            text: 要合成的文本
            voice: 音色名称
            speed: 语速 (0.5-2.0)

        Returns:
            WAV 格式的音频字节
        """
        wav = self.synthesize_array(text=text, voice=voice, speed=speed)

        # 转为 WAV 字节
        import soundfile as sf

        buffer = BytesIO()
        sf.write(buffer, wav, self.config.sample_rate, format="WAV")
        buffer.seek(0)
        return buffer.read()

    def synthesize_array(
        self,
        text: str,
        voice: str = "zm_010",
        speed: float = 1.0,
    ):
        """合成语音，返回 float32 numpy array。"""
        self._validate_request(text=text, voice=voice, speed=speed)

        # 清理文本
        text = self._clean_text(text)
        if not text:
            raise ValueError("清理后文本为空")

        # 合成
        return self._do_synthesize(text, voice, speed)

    def synthesize_file(
        self,
        text: str,
        output_path: str,
        voice: str = "zm_010",
        speed: float = 1.0,
    ) -> str:
        """合成并保存到文件，返回文件路径"""
        audio_bytes = self.synthesize(text, voice, speed)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
        logger.info(f"音频已保存: {path} ({len(audio_bytes)} bytes)")
        return str(path)

    # ── 内部方法（不需要重依赖，可直接测试） ──

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
        """清理文本：移除不可打印字符，合并空白"""
        text = "".join(c if c.isprintable() or c.isspace() else " " for c in text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _detect_language(self, text: str) -> str:
        """检测文本主要语言。

        当前中文 pipeline 已通过 en_callable 支持中英混合，本方法仅用于日志和后续扩展。
        """
        english = len(re.findall(r"[a-zA-Z]", text))
        total = len(text)
        if total == 0:
            return "zh"
        return "en" if english / total > 0.6 else "zh"

    def _segment_text(self, text: str) -> list[str]:
        """按标点优先分段；没有合适标点时按长度硬切，避免超长单段。"""
        max_len = max(20, int(self.config.segment_length))
        punctuation = "。！？!?；;，,、.\n"
        segments: list[str] = []
        current = ""

        for char in text:
            current += char

            # 标点已接近目标长度，直接切
            if len(current) >= max_len and char in punctuation:
                if current.strip():
                    segments.append(current.strip())
                current = ""
                continue

            # 超过 1.5 倍长度时强制寻找最近标点，否则硬切
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
        """创建语速函数"""
        speed = float(speed)
        return lambda len_ps: speed

    def _do_synthesize(self, text: str, voice: str, speed: float):
        """执行实际合成（需要已加载模型）"""
        import numpy as np

        lang = self._detect_language(text)
        segments = self._segment_text(text)
        logger.info(f"合成: lang={lang}, segments={len(segments)}, voice={voice}, speed={speed}")

        all_wavs = []
        pipeline = self._zh_pipeline
        speed_fn = self._make_speed_fn(speed)

        for i, segment in enumerate(segments):
            try:
                wav_seg = self._synthesize_segment(pipeline, segment, voice, speed_fn)
                if wav_seg is not None:
                    all_wavs.append(self._postprocess_segment(wav_seg))
            except Exception as e:
                logger.warning(f"段落 {i + 1} 合成失败: {e}")

        if not all_wavs:
            raise RuntimeError("所有段落合成均失败，无有效音频数据")

        return np.concatenate(all_wavs)

    def _synthesize_segment(self, pipeline, segment: str, voice: str, speed_fn):
        """合成单个段落"""
        import numpy as np
        import torch

        generator = pipeline(segment, voice=voice, speed=speed_fn)
        result = next(generator)
        audio = result.audio

        if audio is None:
            return None

        # Tensor -> NumPy
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().numpy()

        if not isinstance(audio, np.ndarray):
            return None

        # 确保一维
        if audio.ndim > 1:
            audio = audio.reshape(-1)

        return audio.astype(np.float32, copy=False)

    def _postprocess_segment(self, audio_array):
        """清理音频并给段落边界增加轻量淡入淡出，减少 click/pop。"""
        import numpy as np

        audio_array = self._normalize_audio(audio_array)

        fade_len = int(self.config.sample_rate * 0.005)  # 5ms
        if audio_array.size > fade_len * 2 and fade_len > 0:
            fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
            fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
            audio_array[:fade_len] *= fade_in
            audio_array[-fade_len:] *= fade_out

        silence_len = int(self.config.sample_rate * 0.03)  # 30ms
        if silence_len > 0:
            silence = np.zeros(silence_len, dtype=np.float32)
            audio_array = np.concatenate([audio_array, silence])

        return audio_array

    def _normalize_audio(self, audio_array):
        """将音频限制在安全 float32 范围内，避免 int16 溢出爆音。"""
        import numpy as np

        audio_array = np.asarray(audio_array, dtype=np.float32).reshape(-1)
        audio_array = np.nan_to_num(audio_array, nan=0.0, posinf=0.0, neginf=0.0)
        return np.clip(audio_array, -1.0, 1.0)

    def synthesize_stream(self, text, voice="zm_010", speed=1.0, fmt="pcm_s16le"):
        """流式合成，逐段 yield 音频数据

        Args:
            text: 要合成的文本
            voice: 音色名称
            speed: 语速 (0.5-2.0)
            fmt: 输出格式 (pcm_s16le, wav)

        Yields:
            dict: 包含 type, index, data 等字段的 JSON 消息
        """
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
                wav_seg = self._synthesize_segment(
                    self._zh_pipeline, segment, voice, speed_fn
                )
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
        """将音频 numpy 数组编码为字节

        Args:
            audio_array: 一维 float32 numpy 数组 (范围 [-1, 1])
            format: pcm_s16le 或 wav

        Returns:
            bytes: 编码后的音频数据
        """
        import soundfile as sf

        audio_array = self._normalize_audio(audio_array)

        if format == "pcm_s16le":
            audio_int16 = (audio_array * 32767.0).astype("<i2")
            return audio_int16.tobytes()
        elif format == "wav":
            buffer = BytesIO()
            sf.write(buffer, audio_array, self.config.sample_rate, format="WAV")
            return buffer.getvalue()
        else:
            raise ValueError(f"Unsupported format: {format}")
