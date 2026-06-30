"""fnOS and Compose image tag contracts for the 2.6.616 packaging fix."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_fnos_package_images.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_fnos_package_images", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_tag_keeps_v_for_docker_image_tags():
    validator = _load_validator()
    assert validator.image_tag_for_release(release_tag="v2.6.616", package_version="2.6.616") == "v2.6.616"
    assert validator.image_tag_for_release(package_version="2.6.616") == "v2.6.616"


def test_validator_rejects_bare_release_tags_and_latest_by_default():
    validator = _load_validator()
    errors = validator.validate_images([
        "maxblack777/angevoice-gpu:2.6.616",
        "maxblack777/angevoice-cpu:latest",
        "maxblack777/angevoice-legacy-gpu:v2.6.616",
    ])
    assert any("missing the leading v" in error for error in errors)
    assert any("uses latest" in error for error in errors)


def test_current_compose_files_use_v_prefixed_release_image_tags():
    validator = _load_validator()
    compose_files = [
        ROOT / "docker/cpu/docker-compose.yml",
        ROOT / "docker/gpu/docker-compose.yml",
        ROOT / "docker/legacy-gpu/docker-compose.yml",
        ROOT / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml",
    ]
    for path in compose_files:
        images = validator.extract_image_references(path.read_text(encoding="utf-8"))
        assert images
        assert not validator.validate_images(images), path
        assert all(":v2.6.616" in image for image in images if "maxblack777/angevoice-" in image)
        assert all(":2.6.616" not in image for image in images)


def test_validate_script_cli_reports_current_fnos_images():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(ROOT / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml"), "--no-remote"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "maxblack777/angevoice-cpu:v2.6.616" in result.stdout
    assert "maxblack777/angevoice-gpu:v2.6.616" in result.stdout
    assert "maxblack777/angevoice-legacy-gpu:v2.6.616" in result.stdout


def test_validate_script_reads_nested_fpk_app_tgz(tmp_path):
    validator = _load_validator()
    compose = (
        "services:\n"
        "  angevoice-gpu:\n"
        "    image: maxblack777/angevoice-gpu:v2.6.616\n"
    )
    app_tgz = tmp_path / "app.tgz"
    compose_file = tmp_path / "docker-compose.yaml"
    compose_file.write_text(compose, encoding="utf-8")
    with tarfile.open(app_tgz, "w:gz") as app_archive:
        app_archive.add(compose_file, arcname="docker/docker-compose.yaml")
    fpk = tmp_path / "AngeVoice_v2.6.616.fpk"
    with tarfile.open(fpk, "w:gz") as fpk_archive:
        fpk_archive.add(app_tgz, arcname="app.tgz")

    text = validator.read_compose_text(fpk)
    assert validator.extract_image_references(text) == ["maxblack777/angevoice-gpu:v2.6.616"]
