"""Kokoro TTS 核心引擎

支持 CPU/GPU 自动检测，可作为库直接调用或通过 server 模式运行。
重依赖 (numpy, torch, kokoro) 在 load() 时才导入。
"""

import logging
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
        """加载模型和 pipeline"""
        if self._loaded:
            return self

        import torch
        from kokoro import KModel, KPipeline

        self._device = self.config.resolve_device()
        model_path = self.config.model_path

        logger.info(f"加载模型: {model_path} -> {self._device}")

        # 注册本地模型路径
        KModel.MODEL_NAMES[model_path] = "kokoro-v1_1-zh.pth"

        # 设置线程数（CPU 模式）
        if self._device == "cpu":
            try:
                torch.set_num_threads(min(8, (os.cpu_count() or 4)))
            except Exception:
                pass

        # 加载模型
        self._model = KModel(repo_id=model_path).to(self._device).eval()

        # 英文 pipeline（仅用于音素转换，不加载模型）
        self._en_pipeline = KPipeline(lang_code="a", repo_id=model_path, model=False)

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
            lang_code="z", repo_id=model_path, model=self._model, en_callable=en_callable
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
        if not self._loaded:
            raise RuntimeError("引擎未加载，请先调用 load()")

        if not text or not text.strip():
            raise ValueError("文本不能为空")

        if len(text) > self.config.max_text_length:
            raise ValueError(f"文本过长 ({len(text)} 字符)，上限 {self.config.max_text_length}")

        # 清理文本
        text = self._clean_text(text)
        if not text:
            raise ValueError("清理后文本为空")

        # 合成
        wav = self._do_synthesize(text, voice, speed)

        # 转为 WAV 字节
        import soundfile as sf
        buffer = BytesIO()
        sf.write(buffer, wav, self.config.sample_rate, format="WAV")
        buffer.seek(0)
        return buffer.read()

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

    def _clean_text(self, text: str) -> str:
        """清理文本：移除不可打印字符，合并空白"""
        text = "".join(c if c.isprintable() or c.isspace() else " " for c in text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _detect_language(self, text: str) -> str:
        """检测文本主要语言"""
        english = len(re.findall(r"[a-zA-Z]", text))
        total = len(text)
        if total == 0:
            return "zh"
        return "en" if english / total > 0.6 else "zh"

    def _segment_text(self, text: str) -> list[str]:
        """按标点符号分段，每段不超过 segment_length"""
        max_len = self.config.segment_length
        punctuation = set("。！？.!?,，")
        segments = []
        current = ""

        for char in text:
            current += char
            if len(current) >= max_len and char in punctuation:
                segments.append(current)
                current = ""

        if current:
            segments.append(current)

        return segments or [text]

    def _make_speed_fn(self, speed: float):
        """创建语速函数"""
        return lambda len_ps: speed

    def _do_synthesize(self, text: str, voice: str, speed: float):
        """执行实际合成（需要已加载模型）"""
        import numpy as np
        import torch

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
                    all_wavs.append(wav_seg)
            except Exception as e:
                logger.warning(f"段落 {i+1} 合成失败: {e}，尝试 fallback")
                try:
                    wav_seg = self._synthesize_segment(pipeline, segment, voice, speed_fn)
                    if wav_seg is not None:
                        all_wavs.append(wav_seg)
                except Exception as e2:
                    logger.error(f"段落 {i+1} fallback 也失败: {e2}")

        if not all_wavs:
            raise RuntimeError("所有段落合成均失败，无有效音频数据")

        return np.concatenate(all_wavs)

    def _synthesize_segment(self, pipeline, segment: str, voice: str, speed_fn):
        """合成单个段落"""
        import torch
        import numpy as np

        generator = pipeline(segment, voice=voice, speed=speed_fn)
        result = next(generator)
        audio = result.audio

        if audio is None:
            return None

        # Tensor -> NumPy
        if isinstance(audio, torch.Tensor):
            audio = audio.cpu().numpy()

        if not isinstance(audio, np.ndarray):
            return None

        # 确保二维
        if audio.ndim == 1:
            audio = np.expand_dims(audio, axis=1)

        return audio
