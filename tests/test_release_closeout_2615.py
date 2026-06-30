"""Release closeout contracts for AngeVoice 2.6.615."""

from __future__ import annotations

import ast
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.6.615"
IMAGE_TAG = f"v{VERSION}"


def _module_version() -> str:
    tree = ast.parse((ROOT / "src/kokoro_tts/__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    assert isinstance(node.value, ast.Constant)
                    return str(node.value.value)
    raise AssertionError("__version__ not found")


def test_project_and_package_versions_are_aligned_to_2615():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == VERSION
    assert _module_version() == VERSION

    manifest = (ROOT / "packaging/fnos/AngeVoice/manifest").read_text(encoding="utf-8")
    assert f"version               = {VERSION}" in manifest
    assert f"v{VERSION}" in manifest


def test_release_docker_and_fnos_templates_use_v_prefixed_2615_tags():
    compose_files = [
        ROOT / "docker/cpu/docker-compose.yml",
        ROOT / "docker/gpu/docker-compose.yml",
        ROOT / "docker/legacy-gpu/docker-compose.yml",
        ROOT / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml",
    ]
    image_pattern = re.compile(r"maxblack777/angevoice-(?:cpu|gpu|legacy-gpu):([^\s\"']+)")
    for path in compose_files:
        text = path.read_text(encoding="utf-8")
        tags = image_pattern.findall(text)
        assert tags, path
        assert all(tag == IMAGE_TAG for tag in tags), (path, tags)
        assert f":{VERSION}" not in text
        assert ":latest" not in text


def test_public_release_docs_do_not_contain_internal_coordination_terms():
    docs = [
        ROOT / "README.md",
        ROOT / "README_EN.md",
        ROOT / "CHANGELOG.md",
        ROOT / "docs/README.md",
        ROOT / "docs/RELEASE_NOTES_2.6.615.md",
        ROOT / "packaging/fnos/AngeVoice/manifest",
    ]
    disallowed = re.compile(
        r"GPT gate|Codex|Mimo|Batch [0-9]|审查 gate|internal recovery|ba3f525|feature branch",
        re.IGNORECASE,
    )
    for path in docs:
        assert not disallowed.search(path.read_text(encoding="utf-8")), path


def test_release_notes_are_copy_ready_and_scope_bounded():
    notes = (ROOT / "docs/RELEASE_NOTES_2.6.615.md").read_text(encoding="utf-8")
    for required in (
        "prompt-audio",
        "API key",
        "sentencepiece",
        "modelscope",
        "transformers",
        "piper_phonemize",
        "v2.6.615",
        "Python 3.10",
    ):
        assert required.lower() in notes.lower()
    assert "does not add user dictionary CRUD" in notes
    assert "does not change the public synthesis API" in notes
