"""Audio helpers shared by AngeVoice engines."""

from __future__ import annotations

from io import BytesIO


def normalize_audio_array(audio_array):
    """Return clipped float32 audio while preserving mono/stereo layout."""
    import numpy as np

    audio = np.asarray(audio_array, dtype=np.float32)
    if audio.ndim == 0:
        audio = audio.reshape(1)
    elif audio.ndim > 2:
        audio = audio.reshape(-1, audio.shape[-1])
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    return np.clip(audio, -1.0, 1.0)


def encode_audio_segment(audio_array, fmt: str = "pcm_s16le", sample_rate: int = 24000) -> bytes:
    """Encode float audio as raw PCM or WAV."""
    audio = normalize_audio_array(audio_array)
    if fmt == "pcm_s16le":
        audio_int16 = (audio * 32767.0).astype("<i2")
        return audio_int16.tobytes()
    if fmt == "wav":
        import soundfile as sf

        buffer = BytesIO()
        sf.write(buffer, audio, sample_rate, format="WAV")
        return buffer.getvalue()
    raise ValueError(f"Unsupported format: {fmt}")


def write_wav_bytes(audio_array, sample_rate: int) -> bytes:
    return encode_audio_segment(audio_array, "wav", sample_rate)

