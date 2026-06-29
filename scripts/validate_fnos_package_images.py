#!/usr/bin/env python3
"""Validate fnOS package and Compose Docker image tags."""

from __future__ import annotations

import argparse
import io
import re
import sys
import tarfile
from pathlib import Path


IMAGE_LINE_RE = re.compile(r"^\s*image:\s*[\"']?([^\"'\s#]+)", re.MULTILINE)
ANGEVOICE_IMAGE_RE = re.compile(r"^maxblack777/(angevoice-(?:cpu|gpu|legacy-gpu)):(?P<tag>[^:@]+)$")
BARE_RELEASE_TAG_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-.].*)?$")


def image_tag_for_release(release_tag: str | None = None, package_version: str | None = None) -> str:
    """Return the Docker image tag used for release assets.

    Application/package versions remain bare (for example, 2.6.615), but Docker
    images published by the release workflow use the git release tag including v.
    """
    if release_tag and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-.].*)?", release_tag):
        return release_tag
    if package_version and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.].*)?", package_version):
        return f"v{package_version}"
    raise ValueError("release_tag or package_version must look like X.Y.Z")


def extract_image_references(compose_text: str) -> list[str]:
    return IMAGE_LINE_RE.findall(compose_text)


def _read_member_text(archive: tarfile.TarFile, member_name: str) -> str | None:
    try:
        member = archive.getmember(member_name)
    except KeyError:
        return None
    extracted = archive.extractfile(member)
    if extracted is None:
        return None
    return extracted.read().decode("utf-8")


def _read_compose_from_app_tgz(payload: bytes) -> str | None:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as app_archive:
        for name in ("docker/docker-compose.yaml", "./docker/docker-compose.yaml"):
            text = _read_member_text(app_archive, name)
            if text is not None:
                return text
    return None


def read_compose_text(path: Path) -> str:
    if path.is_dir():
        for candidate in (path / "app/docker/docker-compose.yaml", path / "docker-compose.yaml"):
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        raise FileNotFoundError(f"No docker-compose.yaml found under {path}")
    if path.suffix.lower() in {".yaml", ".yml"}:
        return path.read_text(encoding="utf-8")
    with tarfile.open(path, mode="r:*") as archive:
        for name in ("app/docker/docker-compose.yaml", "./app/docker/docker-compose.yaml"):
            text = _read_member_text(archive, name)
            if text is not None:
                return text
        for member in archive.getmembers():
            if member.name.rstrip("/") in {"app.tgz", "./app.tgz"}:
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                text = _read_compose_from_app_tgz(extracted.read())
                if text is not None:
                    return text
    raise FileNotFoundError(f"No fnOS docker-compose.yaml found in {path}")


def validate_images(images: list[str], *, allow_latest: bool = False) -> list[str]:
    errors: list[str] = []
    for image in images:
        match = ANGEVOICE_IMAGE_RE.match(image)
        if not match:
            continue
        tag = match.group("tag")
        if tag == "latest" and not allow_latest:
            errors.append(f"{image} uses latest; release packages must pin a version tag")
        if BARE_RELEASE_TAG_RE.match(tag):
            errors.append(f"{image} is missing the leading v in the release image tag")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="fnOS .fpk, package directory, or docker-compose.yaml path")
    parser.add_argument("--no-remote", action="store_true", help="Do not query registries; local format check only")
    parser.add_argument("--allow-latest", action="store_true", help="Allow :latest for explicit development builds")
    args = parser.parse_args(argv)

    compose_text = read_compose_text(args.path)
    images = extract_image_references(compose_text)
    for image in images:
        print(image)
    errors = validate_images(images, allow_latest=args.allow_latest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
