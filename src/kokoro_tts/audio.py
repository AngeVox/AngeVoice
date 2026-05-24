"""AngeVoice 各语音引擎共用的音频处理工具。"""

from __future__ import annotations

from io import BytesIO


def normalize_audio_array(audio_array):
    """返回限幅后的 float32 音频，并保留单声道或立体声布局。"""
    import numpy as np

    audio = np.asarray(audio_array, dtype=np.float32)
    if audio.ndim == 0:
        audio = audio.reshape(1)
    elif audio.ndim > 2:
        audio = audio.reshape(-1, audio.shape[-1])
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    return np.clip(audio, -1.0, 1.0)


def encode_audio_segment(audio_array, fmt: str = "pcm_s16le", sample_rate: int = 24000) -> bytes:
    """将浮点音频编码为裸 PCM 或 WAV。"""
    audio = normalize_audio_array(audio_array)
    if fmt == "pcm_s16le":
        audio_int16 = (audio * 32767.0).astype("<i2")
        return audio_int16.tobytes()
    if fmt == "wav":
        import soundfile as sf

        buffer = BytesIO()
        # 对外 WAV 响应统一使用兼容性更好的 PCM16 契约，
        # 不让引擎默认格式（例如 FLOAT WAV）泄漏到 API 或缓存结果。
        sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
        return buffer.getvalue()
    raise ValueError(f"不支持的音频格式：{fmt}")


def write_wav_bytes(audio_array, sample_rate: int) -> bytes:
    return encode_audio_segment(audio_array, "wav", sample_rate)



def normalize_wav_to_pcm16_bytes(wav_bytes: bytes, expected_sample_rate: int | None = None) -> bytes:
    """解码 WAV 并返回符合公开契约的 PCM16 WAV。

    ZipVoice 上游默认可能写出 IEEE FLOAT WAV；AngeVoice 对外统一为
    PCM16，使浏览器播放、第三方客户端、缓存证据与 NAS 验证保持一致。
    """
    import soundfile as sf

    audio, sample_rate = sf.read(BytesIO(wav_bytes), dtype="float32", always_2d=False)
    if expected_sample_rate is not None and int(sample_rate) != int(expected_sample_rate):
        raise ValueError(f"WAV 采样率不符合预期：实际 {sample_rate}，预期 {expected_sample_rate}")
    return encode_audio_segment(audio, "wav", int(sample_rate))


def normalize_reference_wav_to_pcm16_bytes(wav_bytes: bytes) -> bytes:
    """将用户上传的 WAV 参考音频规范化为 PCM16 WAV。

    保存的音色仍保留原采样率和声道布局，避免改变参考内容；这里只统一
    WAV 子类型，避免推理链依赖 FLOAT 等特殊编码。
    """
    import soundfile as sf

    audio, sample_rate = sf.read(BytesIO(wav_bytes), dtype="float32", always_2d=False)
    return encode_audio_segment(audio, "wav", int(sample_rate))

def normalize_browser_preview_wav_to_pcm16_bytes(wav_bytes: bytes, target_sample_rate: int = 24000) -> bytes:
    """返回保守的浏览器试听契约：PCM16、单声道、24 kHz。

    Voice Profile 用于推理的参考录音保持原有规范化策略；仅 UI 试听响应
    转为与 ZipVoice 产品输出一致的紧凑格式，以减少浏览器解码差异。
    """
    import numpy as np
    import soundfile as sf

    audio, sample_rate = sf.read(BytesIO(wav_bytes), dtype="float32", always_2d=True)
    if audio.size == 0:
        raise ValueError("WAV 音频内容为空")
    mono = audio.mean(axis=1, dtype=np.float32)
    sample_rate = int(sample_rate)
    target_sample_rate = int(target_sample_rate)
    if sample_rate != target_sample_rate:
        new_frames = max(1, int(round(len(mono) * target_sample_rate / sample_rate)))
        old_axis = np.linspace(0.0, 1.0, num=len(mono), endpoint=False, dtype=np.float64)
        new_axis = np.linspace(0.0, 1.0, num=new_frames, endpoint=False, dtype=np.float64)
        mono = np.interp(new_axis, old_axis, mono).astype(np.float32)
    return encode_audio_segment(mono, "wav", target_sample_rate)

