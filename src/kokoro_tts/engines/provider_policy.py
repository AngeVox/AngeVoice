"""Provider policy separated from product model identity."""

from __future__ import annotations

from typing import Iterable, Any

from .base import ProviderStatus


class ProviderPolicy:
    """Select implementation providers without creating new public models."""

    def __init__(self, resolver):
        self._resolver = resolver

    def requested_provider(self, model_id: str, cfg, enabled_models: Iterable[str], *, provider_hint: str | None = None) -> str:
        if model_id == "zipvoice":
            requested = str(getattr(cfg, "zipvoice_execution_provider", "cpu") or "cpu").strip().lower()
            if requested == "cuda" and bool(getattr(cfg, "zipvoice_cuda_enabled", False)):
                return "cuda"
            return "cpu"
        if model_id != "moss":
            return str(getattr(cfg, "device", "cpu") or "cpu")
        if provider_hint:
            return "cuda" if str(provider_hint).lower() == "cuda" else "cpu"
        entries = [self._resolver(item, default_id="kokoro") for item in enabled_models]
        has_cpu_alias = any(item.canonical_id == "moss" and item.provider_hint == "cpu" for item in entries)
        has_cuda_alias = any(item.canonical_id == "moss" and item.provider_hint == "cuda" for item in entries)
        configured = str(getattr(cfg, "moss_execution_provider", "cpu") or "cpu").strip().lower()
        cuda_enabled = bool(getattr(cfg, "moss_cuda_enabled", True))
        if configured == "cuda" and cuda_enabled:
            return "cuda"
        if has_cuda_alias and not has_cpu_alias and cuda_enabled:
            return "cuda"
        return "cpu"

    def status_from_snapshot(self, requested: str, runtime: dict[str, Any] | None, *, loaded: bool) -> ProviderStatus:
        runtime = runtime or {}
        actual = runtime.get("actual_provider")
        if actual is None and loaded:
            actual = requested
        fallback = bool(runtime.get("fallback", False))
        reason = str(runtime.get("fallback_reason") or "")
        if fallback and not reason:
            reason = f"{requested} unavailable; using {actual}"
        return ProviderStatus(requested, str(actual) if actual is not None else None, fallback, reason, assume_requested_if_unknown=loaded)

    def as_dict(self, model_id: str, requested: str) -> dict[str, Any]:
        return {
            "model": model_id,
            "public_model_stable": True,
            "requested_provider": requested,
            "fallback_allowed": model_id == "moss" or (model_id == "zipvoice" and requested == "cuda"),
            "cpu_release_default": model_id in {"moss", "zipvoice"},
        }
