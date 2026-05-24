#!/usr/bin/env python3
"""Build a deterministic UTF-8 source ZIP for AngeVoice releases.

When executed from a Git checkout, the archive contains tracked files plus
unignored new source files.  Including unignored additions matters when a user
applies the release patch before committing it.  A published source ZIP
intentionally has no ``.git`` directory; running this script from an extracted
release falls back to a conservative source walk that excludes generated, cache
and local-secret files.  This keeps release
artifacts reproducible and lets the extracted source package pass its own
release-contract tests.
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

_EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
}
_EXCLUDED_FILES = {
    ".coverage",
    "docker/angevoice.local.env",
}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
_EXCLUDED_PREFIXES = {
    "docs/delivery/",
    "docs/internal/",
    "docs/refactor/",
}
_EXCLUDED_PATTERNS = {
    "README_*_FOR_*.md",
}


def _git_source_files(root: Path, output: Path) -> list[Path] | None:
    """Return tracked and unignored added files, or ``None`` outside Git."""
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    names = [part.decode("utf-8") for part in out.split(b"\0") if part]
    result: list[Path] = []
    for name in sorted(names):
        path = root / name
        if not path.is_file() or path.resolve() == output:
            continue
        if (
            name in _EXCLUDED_FILES
            or any(fnmatch.fnmatch(name, pattern) for pattern in _EXCLUDED_PATTERNS)
            or any(name.startswith(prefix) for prefix in _EXCLUDED_PREFIXES)
            or path.suffix in _EXCLUDED_SUFFIXES
        ):
            continue
        result.append(path)
    return result


def _release_tree_files(root: Path, output: Path) -> list[Path]:
    """Safely enumerate files in an extracted source release without ``.git``."""
    result: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.resolve() == output:
            continue
        rel = path.relative_to(root)
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue
        rel_posix = rel.as_posix()
        if (
            rel_posix in _EXCLUDED_FILES
            or any(fnmatch.fnmatch(rel_posix, pattern) for pattern in _EXCLUDED_PATTERNS)
            or any(rel_posix.startswith(prefix) for prefix in _EXCLUDED_PREFIXES)
            or path.suffix in _EXCLUDED_SUFFIXES
        ):
            continue
        result.append(path)
    return sorted(result, key=lambda item: item.relative_to(root).as_posix())


def source_files(root: Path, output: Path) -> tuple[list[Path], str]:
    tracked = _git_source_files(root, output)
    if tracked is not None:
        return tracked, "git-tracked+unignored-new"
    return _release_tree_files(root, output), "extracted-release"


def version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, help="Output .zip path")
    parser.add_argument("--prefix", default="", help="Archive root prefix; defaults to AngeVoice-<version>/")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    prefix = args.prefix or f"AngeVoice-{version(root)}/"
    if not prefix.endswith("/"):
        prefix += "/"
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    files, mode = source_files(root, output)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            rel = path.relative_to(root).as_posix()
            info = ZipInfo(prefix + rel, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            info.flag_bits |= 0x800  # Mark UTF-8 names explicitly.
            archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    print(f"Built UTF-8 source archive: {output}")
    print(f"Source mode: {mode}; files: {len(files)}; prefix: {prefix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
