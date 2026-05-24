"""ZipVoice PyTorch CUDA runtime with measurable CPU fallback boundary.

This runtime intentionally remains behind ``ZIPVOICE_EXECUTION_PROVIDER=cuda`` and
``ZIPVOICE_CUDA_ENABLED=true``. The validated ONNX INT8 CPU runtime remains the
fallback and the CPU release default until GPU evidence passes on target hardware.
"""

from __future__ import annotations

import gc
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from ..audio import normalize_wav_to_pcm16_bytes
from .assets import ZipVoiceAssetManager

logger = logging.getLogger(__name__)


class ZipVoiceTorchCudaRuntime:
    actual_provider = "cuda_pytorch"

    def __init__(self, cfg):
        self.cfg = cfg
        manifest = Path(__file__).with_name("assets_manifest_cuda.json")
        self.assets = ZipVoiceAssetManager(cfg, manifest_path=manifest)
        self.model = None
        self.vocoder = None
        self.tokenizer = None
        self.feature_extractor = None
        self.generate_sentence = None
        self.device = None
        self.torch = None
        self.sample_rate = 24000
        self.loaded = False
        self.last_metrics: dict[str, float | str] = {}

    def _upstream_path(self) -> Path:
        configured = getattr(self.cfg, "zipvoice_repo_path", None) or os.environ.get("ZIPVOICE_REPO_PATH")
        if configured:
            return Path(configured).expanduser()
        return Path(__file__).resolve().parents[3] / "vendor" / "ZipVoice"

    def load(self):
        if self.loaded:
            return self
        upstream_path = self._upstream_path()
        if not (upstream_path / "zipvoice").is_dir():
            raise RuntimeError(f"ZipVoice upstream Python source not found: {upstream_path}")
        if str(upstream_path) not in sys.path:
            sys.path.insert(0, str(upstream_path))
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("ZipVoice CUDA runtime dependency missing: torch") from exc
        if not torch.cuda.is_available():
            raise RuntimeError("ZipVoice CUDA requested but torch.cuda.is_available() is false")
        device_index = max(0, int(getattr(self.cfg, "zipvoice_cuda_device_index", 0) or 0))
        if device_index >= int(torch.cuda.device_count()):
            raise RuntimeError(f"ZipVoice CUDA device index unavailable: {device_index}")
        asset_status = self.assets.ensure()
        try:
            from zipvoice.bin.infer_zipvoice import get_vocoder, generate_sentence
            from zipvoice.models.zipvoice_distill import ZipVoiceDistill
            from zipvoice.tokenizer.tokenizer import EmiliaTokenizer
            from zipvoice.utils.checkpoint import load_checkpoint
            from zipvoice.utils.feature import VocosFbank
        except ImportError as exc:
            raise RuntimeError("ZipVoice CUDA runtime dependency missing; build/install the zipvoice GPU dependencies") from exc
        distill = Path(getattr(self.cfg, "zipvoice_distill_dir", asset_status["distill_dir"]))
        vocos = Path(getattr(self.cfg, "zipvoice_vocos_dir", asset_status["vocos_dir"]))
        model_config = json.loads((distill / "model.json").read_text(encoding="utf-8"))
        self.sample_rate = int(model_config["feature"]["sampling_rate"])
        self.tokenizer = EmiliaTokenizer(token_file=distill / "tokens.txt")
        tokenizer_config = {"vocab_size": self.tokenizer.vocab_size, "pad_id": self.tokenizer.pad_id}
        self.model = ZipVoiceDistill(**model_config["model"], **tokenizer_config)
        load_checkpoint(filename=distill / "model.pt", model=self.model, strict=True)
        self.device = torch.device("cuda", device_index)
        self.model = self.model.to(self.device).eval()
        self.vocoder = get_vocoder(str(vocos)).to(self.device).eval()
        self.feature_extractor = VocosFbank()
        self.generate_sentence = generate_sentence
        self.torch = torch
        self.loaded = True
        return self

    def synthesize(self, *, text: str, prompt_audio_path: str, prompt_text: str, speed: float = 1.0, num_steps: int | None = None, remove_long_sil: bool | None = None) -> bytes:
        self.load()
        if not prompt_audio_path or not Path(prompt_audio_path).is_file():
            raise ValueError("ZipVoice 需要可读取的参考音频")
        if not str(prompt_text or "").strip():
            raise ValueError("ZipVoice 需要参考音频对应文本 prompt_text")
        steps = min(32, max(1, int(num_steps or getattr(self.cfg, "zipvoice_num_steps", 8))))
        remove_sil = bool(getattr(self.cfg, "zipvoice_remove_long_sil", False) if remove_long_sil is None else remove_long_sil)
        with tempfile.NamedTemporaryFile(prefix="angevoice_zipvoice_cuda_", suffix=".wav", delete=False) as temp:
            output_path = Path(temp.name)
        start = time.perf_counter()
        try:
            with self.torch.inference_mode():
                metrics = self.generate_sentence(
                    save_path=str(output_path),
                    prompt_text=str(prompt_text).strip(),
                    prompt_wav=str(prompt_audio_path),
                    text=text,
                    model=self.model,
                    vocoder=self.vocoder,
                    tokenizer=self.tokenizer,
                    feature_extractor=self.feature_extractor,
                    device=self.device,
                    num_step=steps,
                    guidance_scale=float(getattr(self.cfg, "zipvoice_guidance_scale", 3.0)),
                    speed=float(speed),
                    t_shift=float(getattr(self.cfg, "zipvoice_t_shift", 0.5)),
                    target_rms=float(getattr(self.cfg, "zipvoice_target_rms", 0.1)),
                    feat_scale=float(getattr(self.cfg, "zipvoice_feat_scale", 0.1)),
                    sampling_rate=self.sample_rate,
                    max_duration=float(getattr(self.cfg, "zipvoice_cuda_max_duration", 36.0)),
                    remove_long_sil=remove_sil,
                )
            elapsed = time.perf_counter() - start
            self.last_metrics = {
                "last_generation_seconds": round(float(elapsed), 4),
                "last_audio_seconds": round(float(metrics.get("wav_seconds", 0.0)), 4),
                "last_rtf": round(float(metrics.get("rtf", elapsed / max(float(metrics.get("wav_seconds", 1.0)), 0.001))), 4),
                "zipvoice_num_steps": steps,
                "runtime_provider": self.actual_provider,
            }
            return normalize_wav_to_pcm16_bytes(output_path.read_bytes(), expected_sample_rate=self.sample_rate)
        finally:
            try:
                output_path.unlink()
            except OSError:
                pass

    def unload(self) -> None:
        self.model = None
        self.vocoder = None
        self.tokenizer = None
        self.feature_extractor = None
        self.generate_sentence = None
        self.loaded = False
        if self.torch is not None:
            try:
                self.torch.cuda.empty_cache()
            except Exception:
                logger.debug("ZipVoice CUDA cache release failed", exc_info=True)
        gc.collect()
