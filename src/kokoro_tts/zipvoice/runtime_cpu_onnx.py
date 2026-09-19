"""Lazy ZipVoice-Distill ONNX INT8 CPU runtime wrapper."""

from __future__ import annotations

import gc
import json
import logging
import os
import sys
import time
from pathlib import Path

from ..audio import normalize_wav_to_pcm16_bytes
from .assets import ZipVoiceAssetManager
from .runtime_common import generation_metrics, generation_settings, prepare_reference, temporary_output

logger = logging.getLogger(__name__)


class ZipVoiceOnnxCpuRuntime:
    def __init__(self, cfg):
        self.cfg = cfg
        self.assets = ZipVoiceAssetManager(cfg)
        self.model = None
        self.vocoder = None
        self.tokenizer = None
        self.feature_extractor = None
        self.generate_sentence = None
        self.torch = None
        self.sample_rate = 24000
        self.loaded = False
        self.last_metrics: dict[str, float] = {}

    def _upstream_path(self) -> Path:
        configured = getattr(self.cfg, "zipvoice_repo_path", None) or os.environ.get("ZIPVOICE_REPO_PATH")
        if configured:
            return Path(configured).expanduser()
        return Path(__file__).resolve().parents[3] / "vendor" / "ZipVoice"

    def load(self):
        if self.loaded:
            return self
        (
            self.model,
            self.vocoder,
            self.tokenizer,
            self.feature_extractor,
            self.generate_sentence,
            self.torch,
            self.sample_rate,
        ) = self._build_runtime()
        self.loaded = True
        return self

    def _build_runtime(self):
        """Build components locally; a failed attempt publishes no partial runtime."""
        asset_status = self.assets.ensure()
        upstream_path = self._upstream_path()
        if not (upstream_path / "zipvoice").is_dir():
            raise RuntimeError(f"ZipVoice upstream Python source not found: {upstream_path}")
        if str(upstream_path) not in sys.path:
            sys.path.insert(0, str(upstream_path))
        try:
            import torch
            from zipvoice.bin.infer_zipvoice import get_vocoder
            from zipvoice.bin.infer_zipvoice_onnx import OnnxModel, generate_sentence
            from zipvoice.tokenizer.tokenizer import EmiliaTokenizer
            from zipvoice.utils.feature import VocosFbank
        except ImportError as exc:
            raise RuntimeError("ZipVoice CPU runtime dependency missing; build/install the zipvoice optional dependencies") from exc
        threads = max(1, int(getattr(self.cfg, "zipvoice_cpu_threads", 4)))
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(threads)
        except RuntimeError:
            pass
        distill = Path(getattr(self.cfg, "zipvoice_distill_dir", asset_status["distill_dir"]))
        vocos = Path(getattr(self.cfg, "zipvoice_vocos_dir", asset_status["vocos_dir"]))
        model_config = json.loads((distill / "model.json").read_text(encoding="utf-8"))
        sample_rate = int(model_config["feature"]["sampling_rate"])
        tokenizer = EmiliaTokenizer(token_file=distill / "tokens.txt")
        model = OnnxModel(distill / "text_encoder_int8.onnx", distill / "fm_decoder_int8.onnx", num_thread=threads)
        vocoder = get_vocoder(str(vocos))
        vocoder.eval()
        feature_extractor = VocosFbank()
        return model, vocoder, tokenizer, feature_extractor, generate_sentence, torch, sample_rate

    def synthesize(self, *, text: str, prompt_audio_path: str, prompt_text: str, speed: float = 1.0, num_steps: int | None = None, remove_long_sil: bool | None = None) -> bytes:
        self.load()
        prompt_text, steps, remove_sil = prepare_reference(
            self.cfg, prompt_audio_path=prompt_audio_path, prompt_text=prompt_text,
            num_steps=num_steps, remove_long_sil=remove_long_sil,
        )
        with temporary_output(prefix="angevoice_zipvoice_") as output_path:
            start = time.perf_counter()
            with self.torch.inference_mode():
                metrics = self.generate_sentence(
                    save_path=str(output_path),
                    prompt_text=prompt_text,
                    prompt_wav=str(prompt_audio_path),
                    text=text,
                    model=self.model,
                    vocoder=self.vocoder,
                    tokenizer=self.tokenizer,
                    feature_extractor=self.feature_extractor,
                    num_step=steps,
                    **generation_settings(self.cfg, speed=speed),
                    sampling_rate=self.sample_rate,
                    remove_long_sil=remove_sil,
                )
            elapsed = time.perf_counter() - start
            self.last_metrics = generation_metrics(metrics, elapsed=elapsed, steps=steps)
            return normalize_wav_to_pcm16_bytes(output_path.read_bytes(), expected_sample_rate=self.sample_rate)

    def unload(self) -> None:
        # ONNX Runtime has no supported end_session() lifecycle API. Releasing
        # references and collecting Python objects is the testable CPU action.
        self.model = None
        self.vocoder = None
        self.tokenizer = None
        self.feature_extractor = None
        self.generate_sentence = None
        self.loaded = False
        gc.collect()
