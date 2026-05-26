"""AngeVoice — lightweight Chinese TTS service built on Kokoro v1.1.

The import package intentionally remains ``kokoro_tts`` for backward
compatibility with earlier releases. The distribution name and recommended CLI
are now ``angevoice``; the historical ``kokoro-tts`` command is kept as an alias.

Usage:
    from kokoro_tts import TTSEngine
    engine = TTSEngine()
    engine.load()
    wav_bytes = engine.synthesize("你好世界")

    angevoice serve
    angevoice synth "你好" -o out.wav
    angevoice voices
"""

__version__ = "2.6.602"


def __getattr__(name):
    """Lazy imports so importing the package does not load torch/numpy."""
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
