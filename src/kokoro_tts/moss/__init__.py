"""MOSS 推理辅助模块。

旧的 ``kokoro_tts.moss_engine.MossNanoEngine`` 对外路径保持不变；本包承载
可单测、可复用的 MOSS 运行时、文本、流式、prompt 和音频后处理逻辑。
"""

from .postprocess import (
    MossAudioQuality,
    analyze_silence,
    clamp_pause_seconds,
    compress_long_silence,
    concat_waveforms,
    normalize_waveform,
    silence_array,
    split_waveform_for_stream,
    trim_silence_edges,
)
from .prompt import (
    prepare_prompt_audio,
    prompt_audio_cache_key,
    resolve_prompt_audio_codes_cached,
)
from .runtime import (
    analyze_waveform,
    create_runtime,
    ensure_import_path,
    temp_output_path,
)
from .process_worker import MossProcessClient, MossProcessTimeoutError
from .streaming import (
    StreamBudgetThresholds,
    merge_codec_audio,
    resolve_stream_decode_frame_budget,
    runtime_supports_frame_streaming,
)
from .text import clean_text, segment_text
from .vram import VramSnapshot, get_cuda_vram_snapshot, is_memory_allocation_error

__all__ = [
    "MossAudioQuality",
    "trim_silence_edges",
    "compress_long_silence",
    "clamp_pause_seconds",
    "analyze_silence",
    "MossProcessClient",
    "MossProcessTimeoutError",
    "VramSnapshot",
    "StreamBudgetThresholds",
    "analyze_waveform",
    "clean_text",
    "concat_waveforms",
    "create_runtime",
    "ensure_import_path",
    "get_cuda_vram_snapshot",
    "is_memory_allocation_error",
    "merge_codec_audio",
    "normalize_waveform",
    "prepare_prompt_audio",
    "prompt_audio_cache_key",
    "resolve_prompt_audio_codes_cached",
    "resolve_stream_decode_frame_budget",
    "runtime_supports_frame_streaming",
    "segment_text",
    "silence_array",
    "split_waveform_for_stream",
    "temp_output_path",
]
