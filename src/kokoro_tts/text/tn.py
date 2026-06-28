"""Optional text-normalization engines for AngeVoice."""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


class TextNormalizerUnavailable(RuntimeError):
    """Raised when a requested optional TN backend cannot run."""


@lru_cache(maxsize=1)
def _wetext_normalizer():
    try:
        from wetext import Normalizer
    except Exception as exc:  # pragma: no cover - exercised through fallback
        raise TextNormalizerUnavailable(str(exc)) from exc
    try:
        return Normalizer()
    except Exception as exc:  # pragma: no cover - backend-specific
        raise TextNormalizerUnavailable(str(exc)) from exc


def normalize_with_wetext(text: str) -> str:
    normalizer = _wetext_normalizer()
    try:
        return str(normalizer.normalize(text))
    except Exception as exc:
        raise TextNormalizerUnavailable(str(exc)) from exc


def reset_tn_caches() -> None:
    """Clear lazy backend caches for tests."""

    _wetext_normalizer.cache_clear()
