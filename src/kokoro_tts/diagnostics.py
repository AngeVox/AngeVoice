"""Redacted runtime diagnostics export for AngeVoice support."""

from __future__ import annotations

import io
import json
import platform
import sys
import time
import zipfile
from typing import Any

from .model_assets import ModelAssetService
from .routes.admin_runtime import config_snapshot, security_snapshot


def _dump(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")


def build_diagnostics_bundle(state) -> bytes:
    """Build a ZIP containing no plaintext API key or administrator password."""
    cfg = state.cfg
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    resources = state.resource_snapshot()
    assets = ModelAssetService(cfg).status(full_verify_zipvoice=False)
    profiles = {
        engine: {
            "profiles": state.voice_profiles.list(engine),
            "verification": state.voice_profiles.verify(engine),
        }
        for engine in state.voice_profiles.supported_engines()
    }
    security = security_snapshot(cfg, reveal=False)
    manifest = {
        "bundle_type": "angevoice_runtime_diagnostics",
        "deployment_profile": str(getattr(cfg, "deployment_profile", "source") or "source"),
        "generated_at": generated_at,
        "redaction": "No plaintext API key or administrator password is included.",
        "python": sys.version,
        "platform": platform.platform(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _dump(manifest))
        archive.writestr("runtime/resources.json", _dump(resources))
        archive.writestr("runtime/models.json", _dump(state.model_manager.list_models()))
        archive.writestr("runtime/config-redacted.json", _dump(config_snapshot(cfg)))
        archive.writestr("security/security-redacted.json", _dump(security))
        archive.writestr("assets/assets-status.json", _dump(assets))
        archive.writestr("profiles/voice-profiles.json", _dump(profiles))
    return buffer.getvalue()
