"""Transformers 4.53.x compatibility contract for 2.6.615.

This file intentionally keeps tests static. Import-level compatibility is
verified in a clean venv during the Batch 3B gate so the normal test suite does
not depend on whichever transformers version happens to be installed locally.
"""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
CONSTRAINT_FILES = [
    REPO_ROOT / "constraints.txt",
    REPO_ROOT / "docker" / "constraints-gpu.lock",
    REPO_ROOT / "docker" / "constraints-legacy-gpu.lock",
]


def test_pyproject_uses_transformers_453_stable_line_without_rc_or_latest():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    gpu_dependencies = pyproject["project"]["optional-dependencies"]["gpu"]

    assert "transformers>=4.53.0,<4.54" in dependencies
    assert "transformers>=4.53.0,<4.54" in gpu_dependencies
    combined = "\n".join(dependencies + gpu_dependencies)
    assert ("5.0.0" + "rc") not in combined
    assert "<5" not in combined
    assert "transformers>=" in combined


def test_transformers_runtime_constraints_are_synchronized():
    expected = {"transformers==4.53.3", "tokenizers==0.21.4", "huggingface_hub==0.36.2"}

    for path in CONSTRAINT_FILES:
        lines = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith(("transformers", "tokenizers", "huggingface_hub"))
        }
        assert lines == expected


def test_optional_model_download_extras_match_transformers_hub_floor():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional = pyproject["project"]["optional-dependencies"]

    for extra in ("moss", "zipvoice", "moss-gpu"):
        assert "huggingface_hub>=0.30.0" in optional[extra]


def test_transformers_batch_does_not_change_disallowed_core_runtime_pins():
    for path in CONSTRAINT_FILES:
        source = path.read_text(encoding="utf-8")
        assert "torch==" not in source
        assert "kokoro==0.8.2" in source
        assert "misaki==0.8.2" in source
        assert ("5.0.0" + "rc") not in source
