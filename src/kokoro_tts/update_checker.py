"""Small, non-blocking release notification service for the admin console.

This is intentionally a *notification* facility, not an auto-updater.  It reads
GitHub's public latest-release metadata only when the admin console asks for it,
keeps a short in-memory cache, and never mutates an installation.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.request import Request, urlopen

from . import __version__

_VERSION_RE = re.compile(r"(?:^|[^0-9])(\d+(?:\.\d+){1,3})(?:[^0-9]|$)")


def _version_tuple(value: str) -> tuple[int, ...]:
    match = _VERSION_RE.search(str(value or ""))
    if not match:
        return ()
    parts = tuple(int(item) for item in match.group(1).split("."))
    return parts + (0,) * (4 - len(parts))


@dataclass
class UpdateSnapshot:
    enabled: bool
    repository: str
    current_version: str
    checked: bool = False
    checked_at: float | None = None
    latest_version: str = ""
    update_available: bool = False
    release_url: str = ""
    release_name: str = ""
    release_notes: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "repository": self.repository,
            "current_version": self.current_version,
            "checked": self.checked,
            "checked_at": self.checked_at,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "release_url": self.release_url,
            "release_name": self.release_name,
            "release_notes": self.release_notes,
            "error": self.error,
            "auto_update": False,
        }


class UpdateChecker:
    """Fetch and cache public release metadata for a configured repository."""

    def __init__(self, cfg, *, opener: Callable[..., Any] | None = None):
        self.cfg = cfg
        self._opener = opener or urlopen
        self._snapshot = UpdateSnapshot(
            enabled=bool(getattr(cfg, "update_check_enabled", True)),
            repository=str(getattr(cfg, "update_repository", "ang77712829/AngeVoice") or "").strip(),
            current_version=__version__,
        )
        self._cache_seconds = float(getattr(cfg, "update_check_cache_seconds", 21600.0))

    def snapshot(self) -> dict[str, Any]:
        return self._snapshot.as_dict()

    def check(self, *, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not self._snapshot.enabled:
            return self._snapshot.as_dict()
        if not self._snapshot.repository or "/" not in self._snapshot.repository:
            self._snapshot.error = "未配置有效的更新仓库"
            self._snapshot.checked = True
            self._snapshot.checked_at = now
            return self._snapshot.as_dict()
        if not force and self._snapshot.checked_at and now - self._snapshot.checked_at < self._cache_seconds:
            return self._snapshot.as_dict()

        url = f"https://api.github.com/repos/{self._snapshot.repository}/releases/latest"
        req = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": f"AngeVoice/{__version__}"})
        try:
            response = self._opener(req, timeout=float(getattr(self.cfg, "update_check_timeout_seconds", 3.0)))
            raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            tag = str(payload.get("tag_name") or "")
            latest = tag.lstrip("vV")
            current_tuple = _version_tuple(__version__)
            latest_tuple = _version_tuple(latest)
            self._snapshot.latest_version = latest
            self._snapshot.release_url = str(payload.get("html_url") or "")
            self._snapshot.release_name = str(payload.get("name") or tag or latest)
            self._snapshot.release_notes = str(payload.get("body") or "").strip()[:1000]
            self._snapshot.update_available = bool(current_tuple and latest_tuple and latest_tuple > current_tuple)
            self._snapshot.error = ""
        except Exception as exc:  # network failure must not affect TTS/admin functionality
            self._snapshot.error = f"检查更新失败：{exc}"
            self._snapshot.update_available = False
        self._snapshot.checked = True
        self._snapshot.checked_at = now
        return self._snapshot.as_dict()
