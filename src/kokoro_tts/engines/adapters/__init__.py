"""Legacy adapter exports and lazy compatibility shims.

Native product engines such as ZipVoice are imported only when explicitly
requested.  Keeping them out of module initialization avoids circular imports
and lets future engines register runtime factories without loading heavy
implementations while listing models or health status.
"""

from .kokoro import KokoroAdapter
from .moss import MossAdapter


def __getattr__(name: str):
    """Preserve the historical adapter export without eager runtime imports."""

    if name == "ZipVoiceEngine":
        from ...zipvoice.engine import ZipVoiceEngine

        return ZipVoiceEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["KokoroAdapter", "MossAdapter", "ZipVoiceEngine"]
