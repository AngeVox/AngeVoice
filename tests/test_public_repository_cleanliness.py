"""Contracts for the public source archive and deployable templates."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = [ROOT / "README.md", ROOT / "README_EN.md", *(ROOT / "docs").glob("*.md")]


def test_public_repository_contains_only_public_documentation():
    assert not (ROOT / "docs" / "delivery").exists()
    assert not (ROOT / "docs" / "ROADMAP.md").exists()
    assert not list(ROOT.glob("README_*_FOR_*.md"))
    disallowed = re.compile(
        r"发布候选|release candidate|待验收|待审核|正式发布前|推送正式标签|"
        r"Architecture Closure|CPU RC|Final Candidate|DEFERRED|交接|审查|FOR_CC"
    )
    for path in PUBLIC_DOCS:
        assert not disallowed.search(path.read_text(encoding="utf-8")), path.name


def test_public_markdown_links_resolve_within_source_tree():
    pattern = re.compile(r"\[[^\]]+\]\(([^)#]+\.md)(?:#[^)]+)?\)")
    for path in PUBLIC_DOCS:
        text = path.read_text(encoding="utf-8")
        for target in pattern.findall(text):
            destination = (path.parent / target).resolve()
            if destination.is_relative_to(ROOT.resolve()):
                assert destination.exists(), f"{path.relative_to(ROOT)} -> {target}"


def test_runtime_templates_use_latest_images_and_fnos_uses_verified_profile_routing():
    image_files = [
        ROOT / "docker/cpu/docker-compose.yml",
        ROOT / "docker/gpu/docker-compose.yml",
        ROOT / "docker/legacy-gpu/docker-compose.yml",
        ROOT / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml",
    ]
    for path in image_files:
        text = path.read_text(encoding="utf-8")
        assert ":2.6.601" not in text
        for line in text.splitlines():
            if "angevoice-" in line and "ghcr.io/" in line:
                assert ":latest" in line, f"{path.relative_to(ROOT)}: {line}"
    compose = (ROOT / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml").read_text(encoding="utf-8")
    assert compose.count("profiles:") == 3
    assert "angevoice-cpu:latest" in compose and "angevoice-gpu:latest" in compose and "angevoice-legacy-gpu:latest" in compose
    install = (ROOT / "packaging/fnos/AngeVoice/wizard/install").read_text(encoding="utf-8")
    assert "COMPOSE_PROFILES" in install and "wizard_run_mode" not in install
    assert not (ROOT / "packaging/fnos/AngeVoice/app/docker/.env").exists()

