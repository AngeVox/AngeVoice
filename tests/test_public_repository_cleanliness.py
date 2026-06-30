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


def test_runtime_templates_use_versioned_images_and_fnos_uses_verified_profile_routing():
    image_files = [
        ROOT / "docker/cpu/docker-compose.yml",
        ROOT / "docker/gpu/docker-compose.yml",
        ROOT / "docker/legacy-gpu/docker-compose.yml",
        ROOT / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml",
    ]
    for path in image_files:
        text = path.read_text(encoding="utf-8")
        assert ":2.6.602" not in text
        assert "ghcr.io/maxblack777/angevoice-" not in text
        assert "maxblack777/angevoice-" in text
        for line in text.splitlines():
            if "image:" in line and "maxblack777/angevoice-" in line:
                assert ":v2.6.615" in line, f"{path.relative_to(ROOT)}: {line}"
    compose = (ROOT / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml").read_text(encoding="utf-8")
    assert compose.count("profiles:") == 3
    assert "angevoice-cpu:v2.6.615" in compose and "angevoice-gpu:v2.6.615" in compose and "angevoice-legacy-gpu:v2.6.615" in compose
    install = (ROOT / "packaging/fnos/AngeVoice/wizard/install").read_text(encoding="utf-8")
    assert "COMPOSE_PROFILES" in install and "wizard_run_mode" not in install
    assert not (ROOT / "packaging/fnos/AngeVoice/app/docker/.env").exists()


def test_update_repository_stays_on_github_project_while_images_use_dockerhub_namespace():
    env_files = [
        ROOT / "docker/angevoice.env",
        ROOT / "packaging/fnos/AngeVoice/app/docker/angevoice.env",
    ]
    for path in env_files:
        text = path.read_text(encoding="utf-8")
        assert "ANGEVOICE_UPDATE_REPOSITORY=ang77712829/AngeVoice" in text
        assert "ANGEVOICE_UPDATE_REPOSITORY=maxblack777/AngeVoice" not in text


def test_fnos_upgrade_cleans_only_legacy_routing_files():
    cleanup_files = [
        "${TRIM_PKGVAR}/docker-compose.yaml",
        "${TRIM_PKGVAR}/docker-compose.yml",
        "${TRIM_PKGVAR}/docker/.env",
        "${TRIM_PKGVAR}/app/docker/.env",
        "${TRIM_PKGVAR}/cmd/_mode_env.sh",
    ]
    for rel in ["cmd/install_callback", "cmd/upgrade_callback"]:
        text = (ROOT / "packaging/fnos/AngeVoice" / rel).read_text(encoding="utf-8")
        for item in cleanup_files:
            assert item in text
        assert "${TRIM_PKGVAR}/models" in text
        assert "${TRIM_PKGVAR}/credentials" in text
        assert "rm -rf" not in text


def test_xiaozhi_release_assets_include_zipvoice_clone_presets():
    script = (ROOT / "xiaozhi/scripts/install-xiaozhi-adapter.sh").read_text(encoding="utf-8")
    manager = (ROOT / "xiaozhi/manager/presets.yaml").read_text(encoding="utf-8")
    clone_adapter = (ROOT / "xiaozhi/adapters/angevoice_clone.py").read_text(encoding="utf-8")
    stream_adapter = (ROOT / "xiaozhi/adapters/angevoice_stream.py").read_text(encoding="utf-8")
    examples = [
        ROOT / "xiaozhi/examples/config-zipvoice-clone.yaml",
        ROOT / "xiaozhi/examples/config-zipvoice-stream.yaml",
    ]
    assert "zipvoice|zipvoice-stream|zipvoice-clone|zipvoice-clone-stream" in script
    assert "TTS_AngeVoiceZipVoiceClone" in script
    assert "TTS_AngeVoiceZipVoiceCloneStream" in script
    assert "prompt_text" in script and "PROMPT_TEXT" in script
    assert "AngeVoice ZipVoice 克隆非流式" in manager
    assert "AngeVoice ZipVoice 克隆流式" in manager
    assert "model: zipvoice" in manager
    assert "prompt_text" in clone_adapter and "prompt_text" in stream_adapter
    for path in examples:
        text = path.read_text(encoding="utf-8")
        assert "model: zipvoice" in text
        assert "prompt_audio_path" in text
        assert "prompt_text" in text


def test_reader_adapter_docs_use_public_model_ids_and_zipvoice_prompt_text():
    text = (ROOT / "docs/ANGE_READER_BACKEND_ADAPTER.md").read_text(encoding="utf-8")
    assert "model=moss-nano" not in text
    assert "`kokoro`、`moss`" in text
    assert "ZipVoice 临时克隆" in text
    assert "`prompt_text`" in text
