"""Persistent, manifest-driven ZipVoice asset download and verification."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from filelock import FileLock

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
    def _verified_record(saved: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        """A learned digest belongs to a verified source revision, not just an ID."""
        record = saved.get(item["id"], {})
        if not isinstance(record, dict) or record.get("verification_status") != "verified":
            return {}
        if any(record.get(key) != item[key] for key in ("repo", "revision")):
            return {}
        digest = record.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
            return {}
        return {**record, "sha256": digest.lower()}

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
            payload = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"files": {}}
        # This file is a cache of verification records, not an authority on its
        # own. Invalid structure means no learned digests; manifest pins remain.
        if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
            return {"files": {}}
        return payload

    def _write_status(self, payload: dict[str, Any]) -> None:
        self.model_root.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.model_root,
                prefix=self.status_path.name + ".", suffix=".tmp", delete=False,
            ) as handle:
                temp = Path(handle.name)
                handle.write(serialized)
            # Close before replacement for Windows; same-directory replacement
            # publishes a whole snapshot. This does not serialize asset ensure.
            os.replace(temp, self.status_path)
        finally:
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("ZipVoice status temporary cleanup failed (%s)", type(exc).__name__)

    def status(self, *, full_verify: bool = False) -> dict[str, Any]:
        saved = self._read_status().get("files", {})
        files = [self._asset_status(item, saved, full_verify=full_verify) for item in self.manifest["assets"]]
        return {
            "schema_version": self.manifest.get("schema_version", 1),
            "engine": "zipvoice",
            "ready": all(item["verified"] for item in files),
            "verification_mode": "full_sha256" if full_verify else "last_ensure_record",
            "model_root": str(self.model_root),
            "distill_dir": str(self.distill_dir),
            "vocos_dir": str(self.vocos_dir),
            "status_file": str(self.status_path),
            "files": files,
        }

    def _asset_status(self, item: dict[str, Any], saved: dict[str, Any], *, full_verify: bool) -> dict[str, Any]:
        destination = self._destination(item)
        exists = destination.is_file()
        record = self._verified_record(saved, item)
        expected = item.get("sha256") or record.get("sha256")
        digest = file_sha256(destination) if exists and full_verify else record.get("sha256")
        verified = bool(exists and expected and digest == expected)
        if verified:
            status = "verified" if full_verify else "verified_from_last_ensure"
        elif not exists:
            status = "missing"
        else:
            status = "present_requires_ensure"
        return {
            **item,
            "path": str(destination),
            "exists": exists,
            "downloaded_sha256": digest,
            "verification_expected_sha256": expected,
            "verified": verified,
            "verification_status": status,
        }

    @staticmethod
    def _check_digest(destination: Path, digest: str, expected: str | None, *, declared: str | None) -> None:
        if expected and digest != expected:
            source = "declared" if declared else "recorded"
            raise ZipVoiceAssetIntegrityError(f"ZipVoice {source} asset SHA256 mismatch: {destination}")

    def _install_asset(self, item: dict[str, Any], destination: Path, downloader, *, force_download: bool, expected: str | None) -> None:
        if downloader is None:
            raise FileNotFoundError(f"ZipVoice asset unavailable or unverifiable with downloads disabled: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".angevoice-asset-", dir=destination.parent) as temporary:
            staging = Path(temporary)
            downloaded = self._download_asset(downloader, item, staging, force_download=force_download)
            if not downloaded.is_file():
                raise FileNotFoundError(f"Missing downloaded ZipVoice asset: {destination}")
            # Move our own staged file, but never consume a shared SDK cache
            # entry. Verify the bytes that will be published on this filesystem.
            candidate = downloaded.resolve() if downloaded.resolve().is_relative_to(staging.resolve()) else staging / ".verified-asset"
            if downloaded.resolve() != candidate.resolve():
                shutil.copy2(downloaded, candidate)
            self._check_digest(destination, file_sha256(candidate), expected, declared=item.get("sha256"))
            os.replace(candidate, destination)

    def _ensure_asset(self, item: dict[str, Any], saved: dict[str, Any], downloader) -> dict[str, Any]:
        destination = self._destination(item)
        declared = item.get("sha256")
        recorded = self._verified_record(saved, item).get("sha256")
        expected = declared or recorded
        existing = destination.is_file()
        digest = file_sha256(destination) if existing else None
        if existing:
            self._check_digest(destination, digest, expected, declared=declared)
        if not existing or not expected:
            self._install_asset(
                item, destination, downloader,
                force_download=self._requires_forced_download(existing, declared, recorded),
                expected=expected,
            )
            digest = None
        if not destination.is_file():
            raise FileNotFoundError(f"Missing downloaded ZipVoice asset: {destination}")
        digest = digest or file_sha256(destination)
        self._check_digest(destination, digest, expected, declared=declared)
        return {
            "path": str(destination),
            "repo": item["repo"],
            "revision": item["revision"],
            "license": item["license"],
            "sha256": expected or digest,
            "verification_policy": item.get("verification_policy"),
            "verification_status": "verified",
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def ensure(self) -> dict[str, Any]:
        self.model_root.mkdir(parents=True, exist_ok=True)
        self.distill_dir.mkdir(parents=True, exist_ok=True)
        self.vocos_dir.mkdir(parents=True, exist_ok=True)
        with self._asset_locks():
            return self._ensure_locked()

    @contextmanager
    def _asset_locks(self):
        # Per-target locks also cover independently configured roots sharing
        # Vocos assets. Canonical ordering avoids cross-manifest deadlocks.
        targets = {self.status_path.resolve()}
        targets.update(self._destination(item).resolve() for item in self.manifest["assets"])
        lock_paths = sorted({os.path.normcase(str(path) + ".angevoice.lock") for path in targets})
        timeout = max(0.0, float(getattr(self.cfg, "request_timeout_seconds", 120.0)))
        deadline = time.monotonic() + timeout
        with ExitStack() as stack:
            for lock_path in lock_paths:
                Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
                lock = FileLock(lock_path, timeout=max(0.0, deadline - time.monotonic()))
                stack.enter_context(lock)
            yield

    def _ensure_locked(self) -> dict[str, Any]:
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
            updated[item["id"]] = self._ensure_asset(item, saved, hf_hub_download)
        self._write_status({
            "engine": "zipvoice",
            "runtime": self.manifest.get("runtime"),
            "manifest": str(self.manifest_path),
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "files": updated,
        })
        return self.status(full_verify=True)
