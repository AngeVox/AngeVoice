"""Transformers 5.3 manifest and downloader compatibility contract."""

from __future__ import annotations

import ast
import re
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
RUNTIME_CONSTRAINTS = {
    "transformers==5.3.0",
    "tokenizers==0.22.2",
    "huggingface_hub==1.23.0",
}


def _locked_packages() -> dict[str, set[str]]:
    packages: dict[str, set[str]] = {}
    for line in (REPO_ROOT / "requirements" / "test.lock").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([a-z0-9][a-z0-9_.-]*)==([^\s\\;]+)", line)
        if match:
            packages.setdefault(match.group(1), set()).add(match.group(2))
    return packages


def test_pyproject_uses_transformers_53_stable_line_without_rc_or_latest():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    gpu_dependencies = pyproject["project"]["optional-dependencies"]["gpu"]

    assert "transformers>=5.3.0,<5.4" in dependencies
    assert "transformers>=5.3.0,<5.4" in gpu_dependencies
    transformer_specs = [
        dependency.lower()
        for dependency in dependencies + gpu_dependencies
        if dependency.startswith("transformers")
    ]
    assert all("rc" not in spec and "latest" not in spec for spec in transformer_specs)


def test_transformers_runtime_constraints_are_synchronized():
    for path in CONSTRAINT_FILES:
        lines = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith(("transformers", "tokenizers", "huggingface_hub"))
        }
        assert lines == RUNTIME_CONSTRAINTS


def test_optional_model_download_extras_require_compatible_hub_line():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional = pyproject["project"]["optional-dependencies"]

    for extra in ("moss", "zipvoice", "moss-gpu"):
        assert "huggingface_hub>=1.3.0,<2" in optional[extra]


def test_transformers_upgrade_preserves_disallowed_runtime_pins():
    for path in CONSTRAINT_FILES:
        lines = path.read_text(encoding="utf-8").splitlines()
        source = "\n".join(lines).lower()
        manifest_lines = "\n".join(
            line for line in lines if line.startswith(("transformers", "tokenizers", "huggingface_hub"))
        ).lower()
        assert "torch==" not in source
        assert "kokoro==0.8.2" in source
        assert "misaki==0.8.2" in source
        assert "rc" not in manifest_lines
        assert "latest" not in manifest_lines


def test_lightweight_test_input_matches_kokoro_numpy_runtime():
    test_input = (REPO_ROOT / "requirements" / "test.in").read_text(encoding="utf-8")
    assert "numpy==1.26.4" in test_input.splitlines()


def test_lightweight_test_lock_matches_kokoro_numpy_runtime():
    numpy_versions = _locked_packages().get("numpy", set())
    assert numpy_versions == {"1.26.4"}


def test_hub_snapshot_download_call_does_not_pass_removed_symlink_option():
    source = (REPO_ROOT / "src" / "kokoro_tts" / "model_sources.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    functions = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_huggingface_snapshot_download"
    ]
    assert len(functions) == 1
    downloader = functions[0]

    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "snapshot_download"
        for node in ast.walk(downloader)
    )

    dict_keys = {
        key.value
        for node in ast.walk(downloader)
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    keyword_names = {
        node.arg
        for node in ast.walk(downloader)
        if isinstance(node, ast.keyword) and node.arg is not None
    }
    subscript_keys = {
        node.slice.value
        for node in ast.walk(downloader)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }

    retired_option = "local_dir_use_symlinks"
    assert retired_option not in dict_keys
    assert retired_option not in keyword_names
    assert retired_option not in subscript_keys
