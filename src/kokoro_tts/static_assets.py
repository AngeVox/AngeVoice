"""Content-addressed URLs and native ESM import maps for packaged assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping


class StaticAssetManifest:
    """Build one immutable version map for every packaged static asset.

    Frontend source keeps ordinary relative ESM imports so it remains directly
    importable by Node. Browsers receive an import map that resolves those
    unversioned paths to the same content-addressed URLs used by templates.
    """

    def __init__(self, root: Path, *, url_prefix: str = "/static") -> None:
        resolved_root = Path(root).resolve()
        if not resolved_root.is_dir():
            raise ValueError(f"Static asset root does not exist: {resolved_root}")
        self.root = resolved_root
        self.url_prefix = "/" + url_prefix.strip("/")
        versions = {
            path.relative_to(self.root).as_posix(): self.portable_hash(path)
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }
        self.versions: Mapping[str, str] = MappingProxyType(versions)

    @staticmethod
    def portable_hash(path: Path) -> str:
        """Return a cross-platform SHA-256 prefix for UTF-8 or binary content."""
        data = Path(path).read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            normalized = data
        else:
            normalized = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()[:12]

    def _relative_name(self, asset: str) -> str:
        raw = str(asset or "").replace("\\", "/")
        relative = PurePosixPath(raw)
        if not raw or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Invalid static asset path: {asset!r}")
        name = relative.as_posix()
        if name not in self.versions:
            raise KeyError(f"Unknown static asset: {name}")
        return name

    def url(self, asset: str) -> str:
        """Return the immutable public URL for one known asset."""
        name = self._relative_name(asset)
        return f"{self.url_prefix}/{name}?h={self.versions[name]}"

    def import_map(self) -> dict[str, dict[str, str]]:
        """Map every browser-resolved JavaScript path to its immutable URL."""
        imports = {
            f"{self.url_prefix}/{name}": self.url(name)
            for name in self.versions
            if name.endswith(".js")
        }
        return {"imports": imports}

    def import_map_json(self) -> str:
        return json.dumps(self.import_map(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
