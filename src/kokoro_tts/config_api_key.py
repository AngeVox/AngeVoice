"""API key generation and persistence helpers."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

AUTO_API_KEY_SENTINELS = {"auto", "generate", "generated", "random"}


def generate_api_key() -> str:
    """Generate a URL-safe API key suitable for Bearer auth."""
    return "av_" + secrets.token_urlsafe(32)


def load_or_generate_api_key(config) -> str:
    """Load a persistent auto-generated API key, creating it on first run."""
    key_file = Path(getattr(config, "api_key_file", "") or config.output_dir / ".angevoice-api-key").expanduser()
    config.api_key_file = key_file
    try:
        if key_file.exists():
            existing = key_file.read_text(encoding="utf-8").strip()
            if existing:
                logger.info("Using auto-generated API key from %s", key_file)
                return existing
        key_file.parent.mkdir(parents=True, exist_ok=True)
        generated = generate_api_key()
        key_file.write_text(generated + "\n", encoding="utf-8")
        try:
            key_file.chmod(0o600)
        except OSError:
            logger.debug("Unable to chmod generated API key file: %s", key_file, exc_info=True)
        logger.warning("Generated AngeVoice API key at %s. Copy it into Studio/API clients or rotate it in /admin.", key_file)
        return generated
    except Exception:
        logger.exception("Unable to load or generate API key file: %s", key_file)
        generated = generate_api_key()
        logger.warning(
            "Generated in-memory AngeVoice API key because key file is unavailable; "
            "set ANGEVOICE_API_KEY_FILE to a writable path."
        )
        return generated
