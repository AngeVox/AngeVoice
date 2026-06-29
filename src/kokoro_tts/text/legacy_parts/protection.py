"""Compatibility seam for legacy protected-span handling.

Span protection currently lives in the text frontend. The legacy normalizer keeps
this explicit step so future protection rules have a domain home instead of being
added back to the facade.
"""

from __future__ import annotations


def preserve_protected_spans(text: str) -> str:
    return text
