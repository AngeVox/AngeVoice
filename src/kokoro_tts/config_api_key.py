"""API key generation and persistence helpers."""

from __future__ import annotations

import logging
import os
import secrets
import tempfile
import threading
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # pragma: no cover - Docker/fnOS runtime is POSIX.
    fcntl = None
from pathlib import Path

logger = logging.getLogger(__name__)

AUTO_API_KEY_SENTINELS = {"auto", "generate", "generated", "random"}
_API_KEY_FILE_LOCK = threading.RLock()


def generate_api_key() -> str:
    """Generate a URL-safe API key suitable for Bearer auth."""
    return "av_" + secrets.token_urlsafe(32)


@contextmanager
def _credential_lock(path: Path):
    """Serialize rotations across threads and POSIX worker processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _API_KEY_FILE_LOCK:
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _write_secret_unlocked(path: Path, value: str) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            pass
        os.replace(temp_name, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def _atomic_write_secret(path: Path, value: str) -> None:
    with _credential_lock(path):
        _write_secret_unlocked(path, value)


def read_persisted_api_key(config) -> str:
    """Return a durable rotated/generated key when available.

    The credential file is authoritative once present so all worker processes see
    an administrator key rotation without leaking the secret through os.environ.
    """
    key_file = Path(getattr(config, "api_key_file", "") or "/app/credentials/.angevoice-api-key").expanduser()
    try:
        with _API_KEY_FILE_LOCK:
            return key_file.read_text(encoding="utf-8").strip() if key_file.exists() else ""
    except OSError:
        logger.warning("Unable to read persisted API key file: %s", key_file, exc_info=True)
        return ""


def effective_api_key(config) -> str:
    """Resolve the currently accepted key without exposing it via process env."""
    return read_persisted_api_key(config) or str(getattr(config, "api_key", "") or "")


def persist_api_key(config, value: str) -> str:
    key_file = Path(getattr(config, "api_key_file", "") or "/app/credentials/.angevoice-api-key").expanduser()
    config.api_key_file = key_file
    _atomic_write_secret(key_file, value)
    return value


def rotate_api_key(config) -> str:
    """Generate and atomically persist a new key for all application workers."""
    key_file = Path(getattr(config, "api_key_file", "") or "/app/credentials/.angevoice-api-key").expanduser()
    config.api_key_file = key_file
    with _credential_lock(key_file):
        key = generate_api_key()
        _write_secret_unlocked(key_file, key)
        config.api_key = key
        config.api_key_auto_generated = True
        return key


def load_or_generate_api_key(config) -> str:
    """Load a persistent auto-generated API key, migrating the legacy outputs path."""
    key_file = Path(getattr(config, "api_key_file", "") or "/app/credentials/.angevoice-api-key").expanduser()
    config.api_key_file = key_file
    legacy_file = Path(getattr(config, "output_dir", "/app/outputs")) / ".angevoice-api-key"
    try:
        existing = read_persisted_api_key(config)
        if existing:
            logger.info("Using persisted API key from %s", key_file)
            return existing
        if legacy_file != key_file and legacy_file.exists():
            existing = legacy_file.read_text(encoding="utf-8").strip()
            if existing:
                _atomic_write_secret(key_file, existing)
                logger.info("Migrated generated API key from %s to %s", legacy_file, key_file)
                return existing
        generated = generate_api_key()
        _atomic_write_secret(key_file, generated)
        logger.warning("Generated AngeVoice API key at %s. Copy it into Studio/API clients or rotate it in /admin.", key_file)
        return generated
    except Exception:
        logger.exception("Unable to load or generate API key file: %s", key_file)
        generated = generate_api_key()
        logger.warning(
            "Generated in-memory AngeVoice API key because key file is unavailable; "
            "set ANGEVOICE_API_KEY_FILE to a writable persistent path."
        )
        return generated
