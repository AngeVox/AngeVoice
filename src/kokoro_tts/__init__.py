"""Kokoro TTS — 轻量级中文语音合成

用法:
    # 作为库
    from kokoro_tts import TTSEngine
    engine = TTSEngine()
    engine.load()
    wav_bytes = engine.synthesize("你好世界")

    # 命令行
    kokoro-tts serve              # 启动 HTTP 服务
    kokoro-tts synth "你好" -o out.wav  # 直接合成
    kokoro-tts voices             # 列出音色
"""

__version__ = "2.0.0"

# Lazy imports — don't force numpy/torch at package import time
def __getattr__(name):
    if name == "TTSEngine":
        from .engine import TTSEngine
        return TTSEngine
    if name == "TTSConfig":
        from .config import TTSConfig
        return TTSConfig
    if name == "load_config":
        from .config import load_config
        return load_config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["TTSEngine", "TTSConfig", "load_config"]
