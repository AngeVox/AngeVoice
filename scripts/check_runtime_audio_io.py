"""Exercise the audio I/O used by model runtimes without downloading weights."""

from pathlib import Path
from tempfile import TemporaryDirectory

import torch
import torchaudio


def main() -> None:
    sample_rate = 24000
    waveform = torch.sin(torch.arange(2400, dtype=torch.float32) * 0.03).unsqueeze(0) * 0.2
    with TemporaryDirectory(prefix="angevoice-audio-io-") as directory:
        path = Path(directory) / "roundtrip.wav"
        torchaudio.save(str(path), waveform, sample_rate)
        restored, restored_rate = torchaudio.load(str(path))
        assert restored_rate == sample_rate
        assert restored.shape == waveform.shape
        assert torch.isfinite(restored).all()
        assert torch.max(torch.abs(restored - waveform)).item() < 0.001
        resampled = torchaudio.functional.resample(restored, sample_rate, 16000)
        assert resampled.shape == (1, 1600)
        assert torch.isfinite(resampled).all()
    print(f"Runtime WAV read/write/resample: OK (torch={torch.__version__}, torchaudio={torchaudio.__version__})")


if __name__ == "__main__":
    main()
