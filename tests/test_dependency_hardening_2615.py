"""Dependency hardening smoke tests for 2.6.615.

These tests avoid real model downloads and synthesis. Optional dependency import
smokes run when the dependency is installed in the current environment; wrapper
and fallback behavior is covered with fakes so CI can still protect the code
without network access.
"""

from __future__ import annotations

import importlib
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kokoro_tts.config import TTSConfig

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPER_WHEEL_BASE = "https://github.com/csukuangfj/piper-phonemize/releases/download/2025.06.23/"
PIPER_VERSION = "1.3.0"
PIPER_CONSTRAINT_FILES = [
    REPO_ROOT / "constraints.txt",
    REPO_ROOT / "docker" / "constraints-gpu.lock",
    REPO_ROOT / "docker" / "constraints-legacy-gpu.lock",
]


def _piper_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("piper_phonemize")]


def test_sentencepiece_import_smoke_when_installed():
    sentencepiece = pytest.importorskip("sentencepiece")
    assert isinstance(sentencepiece.__version__, str)
    assert sentencepiece.__version__


def test_modelscope_snapshot_download_import_smoke_when_installed():
    module = pytest.importorskip("modelscope.hub.snapshot_download")
    assert callable(module.snapshot_download)


def test_modelscope_missing_package_diagnostic_matches_dependency_floor():
    source = (REPO_ROOT / "src" / "kokoro_tts" / "model_sources.py").read_text(encoding="utf-8")

    assert "modelscope>=1.27.0" in source
    assert ("modelscope>=1." + "20.0") not in source


def test_zipvoice_extra_uses_public_piper_phonemize_wheel_references():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["optional-dependencies"]["zipvoice"]
    piper_dependencies = [item for item in dependencies if item.startswith("piper_phonemize")]

    assert piper_dependencies
    assert all(PIPER_WHEEL_BASE in item for item in piper_dependencies)
    assert all(f"piper_phonemize-{PIPER_VERSION}-" in item for item in piper_dependencies)
    assert not any(">=1.1.0" in item or "==1.1.0" in item for item in piper_dependencies)
    assert {marker for marker in ("Windows", "Linux", "Darwin") if any(marker in item for item in piper_dependencies)} == {
        "Windows",
        "Linux",
        "Darwin",
    }
    for version in ("3.10", "3.11", "3.12"):
        assert any(f"python_version == '{version}'" in item for item in piper_dependencies)


def test_piper_phonemize_constraints_are_synchronized_for_zipvoice_installs():
    first = _piper_lines(PIPER_CONSTRAINT_FILES[0])

    assert first
    assert all(PIPER_WHEEL_BASE in line for line in first)
    assert all(f"piper_phonemize-{PIPER_VERSION}-" in line for line in first)
    assert not any("==1.1.0" in line or ">=1.1.0" in line for line in first)
    for path in PIPER_CONSTRAINT_FILES[1:]:
        assert _piper_lines(path) == first


def test_modelscope_snapshot_download_wrapper_can_use_imported_function(monkeypatch, tmp_path):
    from kokoro_tts import model_sources

    calls: list[tuple[str, str]] = []

    def fake_snapshot_download(repo_id: str, local_dir: str) -> str:
        calls.append((repo_id, local_dir))
        return local_dir

    fake_modelscope = types.ModuleType("modelscope")
    fake_hub = types.ModuleType("modelscope.hub")
    fake_snapshot_module = types.ModuleType("modelscope.hub.snapshot_download")
    fake_snapshot_module.snapshot_download = fake_snapshot_download
    monkeypatch.setitem(sys.modules, "modelscope", fake_modelscope)
    monkeypatch.setitem(sys.modules, "modelscope.hub", fake_hub)
    monkeypatch.setitem(sys.modules, "modelscope.hub.snapshot_download", fake_snapshot_module)

    target = tmp_path / "download-target"
    resolved = model_sources._modelscope_snapshot_download("owner/model", target, logger=logging.getLogger("test"))

    assert resolved == target
    assert calls == [("owner/model", str(target))]
    assert target.exists()


def test_modelscope_unavailable_keeps_huggingface_fallback(monkeypatch, tmp_path):
    from kokoro_tts import model_sources

    target = tmp_path / "MOSS-TTS-Nano-100M-ONNX"
    cfg = TTSConfig(moss_model_dir=target, model_source="modelscope", moss_hf_repo="openmoss/MOSS-TTS-Nano-100M-ONNX")
    calls: list[tuple[str, str]] = []

    def missing_modelscope(repo_id, target_dir, *, logger):
        calls.append(("modelscope", repo_id))
        return None

    def fake_huggingface(repo_id, target_dir, *, logger, allow_patterns=None):
        calls.append(("huggingface", repo_id))
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "browser_poc_manifest.json").write_text("{}", encoding="utf-8")
        with (target_dir / "moss_tts_global_shared.data").open("wb") as handle:
            handle.seek(1024 * 1024)
            handle.write(b"\0")
        return target_dir

    monkeypatch.setattr(model_sources, "resolve_model_source", lambda _cfg: "modelscope")
    monkeypatch.setattr(model_sources, "_modelscope_snapshot_download", missing_modelscope)
    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", fake_huggingface)

    resolved = model_sources.ensure_moss_model_dir(cfg, logger=MagicMock())

    assert resolved == target
    assert calls == [("modelscope", cfg.moss_modelscope_repo), ("huggingface", cfg.moss_hf_repo)]
    assert model_sources.has_valid_moss_model_assets(target)


def test_zipvoice_tokenizer_import_smoke_without_model_load(monkeypatch, tmp_path):
    vendor_root = Path(__file__).resolve().parents[1] / "vendor" / "ZipVoice"
    monkeypatch.syspath_prepend(str(vendor_root))

    fake_lhotse = types.ModuleType("lhotse")
    fake_lhotse.CutSet = object
    fake_jieba = types.ModuleType("jieba")
    fake_jieba.default_logger = logging.getLogger("fake-jieba")
    fake_pypinyin = types.ModuleType("pypinyin")
    fake_pypinyin.Style = object()
    fake_pypinyin.lazy_pinyin = lambda text, *args, **kwargs: list(text)
    fake_tone_convert = types.ModuleType("pypinyin.contrib.tone_convert")
    fake_tone_convert.to_finals_tone3 = lambda text: text
    fake_tone_convert.to_initials = lambda text: text
    fake_normalizer = types.ModuleType("zipvoice.tokenizer.normalizer")
    fake_normalizer.ChineseTextNormalizer = object
    fake_normalizer.EnglishTextNormalizer = object
    fake_piper = types.ModuleType("piper_phonemize")
    fake_piper.phonemize_espeak = lambda text, _lang: list(text)
    monkeypatch.setitem(sys.modules, "lhotse", fake_lhotse)
    monkeypatch.setitem(sys.modules, "jieba", fake_jieba)
    monkeypatch.setitem(sys.modules, "pypinyin", fake_pypinyin)
    monkeypatch.setitem(sys.modules, "pypinyin.contrib", types.ModuleType("pypinyin.contrib"))
    monkeypatch.setitem(sys.modules, "pypinyin.contrib.tone_convert", fake_tone_convert)
    monkeypatch.setitem(sys.modules, "zipvoice.tokenizer.normalizer", fake_normalizer)
    monkeypatch.setitem(sys.modules, "piper_phonemize", fake_piper)

    module = importlib.import_module("zipvoice.tokenizer.tokenizer")
    token_file = tmp_path / "tokens.txt"
    token_file.write_text("_\t0\n你\t1\n好\t2\n", encoding="utf-8")
    tokenizer = module.SimpleTokenizer(str(token_file))

    assert tokenizer.vocab_size == 3
    assert tokenizer.tokens_to_token_ids([["你", "好"]]) == [[1, 2]]
