"""Persistent, manifest-driven ZipVoice asset download and verification."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ZipVoiceAssetIntegrityError(RuntimeError):
    """Raised when a persisted ZipVoice asset does not match its expected digest."""


class ZipVoiceAssetManager:
    """Download ZipVoice and Vocos files outside the image and verify them.

    Large binary weights have upstream-pinned SHA256 values in the bundled
    manifest. Small metadata/text files are pinned by repo revision and their
    first verified download digest is persisted, then checked on each reuse.
    """

    def __init__(self, cfg, manifest_path: Path | None = None):
        self.cfg = cfg
        self.model_root = Path(getattr(cfg, "zipvoice_model_root", "/app/models/zipvoice")).expanduser()
        self.distill_dir = Path(getattr(cfg, "zipvoice_distill_dir", self.model_root / "zipvoice_distill")).expanduser()
        self.vocos_dir = Path(getattr(cfg, "zipvoice_vocos_dir", self.model_root / "vocos-mel-24khz")).expanduser()
        self.status_path = self.model_root / "assets_status.json"
        self.manifest_path = manifest_path or Path(__file__).with_name("assets_manifest.json")
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def _destination(self, item: dict[str, Any]) -> Path:
        root = self.model_root if item.get("install_root") == "model_root" else self.vocos_dir
        return root / str(item["destination"])

    @staticmethod
    def _recorded_digest(saved: dict[str, Any], asset_id: str) -> str | None:
        return (saved.get(asset_id, {}) or {}).get("sha256")

    @staticmethod
    def _requires_forced_download(existing: bool, declared: str | None, recorded: str | None) -> bool:
        return existing and declared is None and recorded is None

    @staticmethod
    def _download_asset(downloader, item: dict[str, Any], local_dir: Path, *, force_download: bool) -> Path:
        kwargs = {
            "repo_id": item["repo"],
            "filename": item["filename"],
            "revision": item["revision"],
            "local_dir": str(local_dir),
        }
        if force_download:
            kwargs["force_download"] = True
        return Path(downloader(**kwargs))

    def _read_status(self) -> dict[str, Any]:
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"files": {}}

    def _write_status(self, payload: dict[str, Any]) -> None:
        self.model_root.mkdir(parents=True, exist_ok=True)
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.status_path)

    def status(self, *, full_verify: bool = False) -> dict[str, Any]:
        saved = self._read_status().get("files", {})
        files: list[dict[str, Any]] = []
        all_ready = True
        for item in self.manifest["assets"]:
            destination = self._destination(item)
            exists = destination.is_file()
            saved_item = saved.get(item["id"], {}) or {}
            declared = item.get("sha256")
            expected = declared or saved_item.get("sha256")
            digest = file_sha256(destination) if exists and full_verify else saved_item.get("sha256")
            verified = bool(exists and expected and digest == expected and saved_item.get("verification_status") == "verified")
            if full_verify and exists and expected:
                verified = digest == expected
            all_ready = all_ready and verified
            if verified:
                status = "verified" if full_verify else "verified_from_last_ensure"
            elif not exists:
                status = "missing"
            else:
                status = "present_requires_ensure"
            files.append({
                **item,
                "path": str(destination),
                "exists": exists,
                "downloaded_sha256": digest,
                "verification_expected_sha256": expected,
                "verified": verified,
                "verification_status": status,
            })
        return {
            "schema_version": self.manifest.get("schema_version", 1),
            "engine": "zipvoice",
            "ready": all_ready,
            "verification_mode": "full_sha256" if full_verify else "last_ensure_record",
            "model_root": str(self.model_root),
            "distill_dir": str(self.distill_dir),
            "vocos_dir": str(self.vocos_dir),
            "status_file": str(self.status_path),
            "files": files,
        }

    def ensure(self) -> dict[str, Any]:
        self.model_root.mkdir(parents=True, exist_ok=True)
        self.distill_dir.mkdir(parents=True, exist_ok=True)
        self.vocos_dir.mkdir(parents=True, exist_ok=True)
        saved = self._read_status().get("files", {})
        download_enabled = bool(getattr(self.cfg, "zipvoice_download_enabled", True))
        if download_enabled:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise RuntimeError("ZipVoice 资产下载需要安装 huggingface_hub") from exc
        else:
            hf_hub_download = None

        updated: dict[str, Any] = {}
        for item in self.manifest["assets"]:
            destination = self._destination(item)
            declared = item.get("sha256")
            recorded = self._recorded_digest(saved, item["id"])
            expected = declared or recorded
            existing = destination.is_file()
            digest = file_sha256(destination) if existing else None
            if existing and expected and digest != expected:
                source = "declared" if declared else "recorded"
                raise ZipVoiceAssetIntegrityError(f"ZipVoice {source} asset SHA256 mismatch: {destination}")
            if not existing or not expected:
                if not download_enabled:
                    raise FileNotFoundError(f"ZipVoice asset unavailable or unverifiable with downloads disabled: {destination}")
                local_dir = self.model_root if item.get("install_root") == "model_root" else self.vocos_dir
                local_dir.mkdir(parents=True, exist_ok=True)
                downloaded = self._download_asset(
                    hf_hub_download,
                    item,
                    local_dir,
                    force_download=self._requires_forced_download(existing, declared, recorded),
                )
                if downloaded.resolve() != destination.resolve():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(downloaded, destination)
                digest = None
            if not destination.is_file():
                raise FileNotFoundError(f"Missing downloaded ZipVoice asset: {destination}")
            digest = digest or file_sha256(destination)
            locked = expected or digest
            if expected and digest != expected:
                source = "declared" if declared else "recorded"
                raise ZipVoiceAssetIntegrityError(f"ZipVoice {source} asset SHA256 mismatch: {destination}")
            updated[item["id"]] = {
                "path": str(destination),
                "repo": item["repo"],
                "revision": item["revision"],
                "license": item["license"],
                "sha256": locked,
                "verification_policy": item.get("verification_policy"),
                "verification_status": "verified",
                "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        self._write_status({
            "engine": "zipvoice",
            "runtime": self.manifest.get("runtime"),
            "manifest": str(self.manifest_path),
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "files": updated,
        })
        return self.status(full_verify=True)
