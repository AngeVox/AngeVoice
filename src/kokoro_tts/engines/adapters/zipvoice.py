"""ZipVoice native product adapter export.

``ZipVoiceEngine`` already implements the public EngineAdapter contract because
it was introduced after the unified engine boundary; unlike legacy runtimes it
does not require a second delegation wrapper.
"""

from ...zipvoice.engine import ZipVoiceEngine

__all__ = ["ZipVoiceEngine"]
