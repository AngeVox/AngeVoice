"""Adapters for mature engines retained during the incremental refactor."""

from .kokoro import KokoroAdapter
from .moss import MossAdapter
from .zipvoice import ZipVoiceEngine

__all__ = ["KokoroAdapter", "MossAdapter", "ZipVoiceEngine"]
