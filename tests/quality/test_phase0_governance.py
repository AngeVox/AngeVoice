"""Governance checks that keep Phase 0 infrastructure enforceable."""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.quality


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _yaml_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _workflow_jobs(workflow: str) -> dict[str, dict[str, object]]:
    """Parse only the CI shape owned by this test, without a YAML dependency."""
    lines = workflow.splitlines()
    try:
        jobs_index = next(index for index, line in enumerate(lines) if line == "jobs:")
    except StopIteration as error:
        raise AssertionError("workflow must have a top-level jobs mapping") from error

    job_starts = [
        (line.strip()[:-1], index)
        for index, line in enumerate(lines[jobs_index + 1 :], start=jobs_index + 1)
        if re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", line)
    ]
    jobs: dict[str, dict[str, object]] = {}
    for position, (job_id, start) in enumerate(job_starts):
        end = job_starts[position + 1][1] if position + 1 < len(job_starts) else len(lines)
        block = lines[start + 1 : end]
        job: dict[str, object] = {"steps": []}
        for line in block:
            match = re.fullmatch(r"    (name|needs):\s*(.+)", line)
            if match:
                job[match.group(1)] = _yaml_value(match.group(2))

        matrix_match = next(
            (
                re.fullmatch(r"        python-version:\s*(\[.+\])", line)
                for line in block
                if re.fullmatch(r"        python-version:\s*(\[.+\])", line)
            ),
            None,
        )
        if matrix_match:
            job["python_versions"] = [
                _yaml_value(item.strip()) for item in matrix_match.group(1).strip("[]").split(",")
            ]

        steps: list[dict[str, object]] = []
        step_starts = [
            index for index, line in enumerate(block) if re.fullmatch(r"      - name:\s*.+", line)
        ]
        for position, step_start in enumerate(step_starts):
            step_end = step_starts[position + 1] if position + 1 < len(step_starts) else len(block)
            step_lines = block[step_start:step_end]
            step: dict[str, object] = {"name": _yaml_value(step_lines[0].split(":", 1)[1])}
            for line_index, line in enumerate(step_lines[1:], start=1):
                match = re.fullmatch(r"        (uses|run):\s*(.*)", line)
                if not match:
                    continue
                key, value = match.groups()
                if key == "uses":
                    step[key] = _yaml_value(value)
                elif value == "|":
                    commands: list[str] = []
                    for command_line in step_lines[line_index + 1 :]:
                        if command_line and _indent(command_line) <= 8:
                            break
                        if command_line:
                            commands.append(command_line.strip())
                    step[key] = commands
                else:
                    step[key] = [_yaml_value(value)]
            steps.append(step)
        job["steps"] = steps
        jobs[job_id] = job
    return jobs


def _step(job: dict[str, object], name: str) -> dict[str, object]:
    return next(step for step in job["steps"] if step["name"] == name)  # type: ignore[index]


def _commands(step: dict[str, object]) -> list[list[str]]:
    return [
        shlex.split(line, comments=True, posix=True)
        for line in step.get("run", [])  # type: ignore[union-attr]
        if line and not line.lstrip().startswith("#")
    ]


def _installs_lock(commands: list[list[str]], lock_path: str) -> bool:
    return any(
        command[:4] == ["python", "-m", "pip", "install"]
        and "--require-hashes" in command
        and "-r" in command
        and command[command.index("-r") + 1] == lock_path
        for command in commands
    )


def _is_pip_check(command: list[str]) -> bool:
    return command == ["python", "-m", "pip", "check"]


def _is_editable_install(command: list[str]) -> bool:
    return command[:6] == ["python", "-m", "pip", "install", "-e", "."] and "--no-deps" in command


def test_ci_uses_locked_dependencies_quality_job_and_coverage_floor() -> None:
    jobs = _workflow_jobs((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert {"quality", "test"} <= set(jobs)

    quality = jobs["quality"]
    assert quality["name"] == "Architecture and i18n quality gates"
    assert _step(quality, "Checkout")["uses"] == "actions/checkout@v6"
    assert _step(quality, "Set up Python")["uses"] == "actions/setup-python@v6"
    quality_install = _commands(_step(quality, "Install locked lightweight test dependencies"))
    assert _installs_lock(quality_install, "requirements/test.lock")
    assert any(_is_pip_check(command) for command in quality_install)
    assert any(_is_editable_install(command) for command in quality_install)
    assert next(index for index, command in enumerate(quality_install) if _is_pip_check(command)) < next(
        index for index, command in enumerate(quality_install) if _is_editable_install(command)
    )
    assert _commands(_step(quality, "Run quality gates")) == [["pytest", "-q", "tests/quality"]]

    tests = jobs["test"]
    assert tests["name"] == "Python tests (${{ matrix.python-version }})"
    assert tests["needs"] == "quality"
    assert tests["python_versions"] == ["3.10", "3.11", "3.12"]
    test_install = _commands(_step(tests, "Install lightweight test dependencies"))
    assert _installs_lock(test_install, "requirements/test.lock")
    assert _installs_lock(test_install, "requirements/test-torch-cpu.lock")
    assert any(_is_pip_check(command) for command in test_install)
    assert any(_is_editable_install(command) for command in test_install)
    assert next(index for index, command in enumerate(test_install) if _is_pip_check(command)) < next(
        index for index, command in enumerate(test_install) if _is_editable_install(command)
    )
    assert ["pytest", "-q", "--cov=kokoro_tts", "--cov-report=term-missing", "--cov-fail-under=70"] in _commands(
        _step(tests, "Run tests")
    )

    torch_lock_lines = (ROOT / "requirements" / "test-torch-cpu.lock").read_text(encoding="utf-8").splitlines()
    meaningful_torch_lock_lines = [
        line.strip() for line in torch_lock_lines if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "--index-url https://download.pytorch.org/whl/cpu" in meaningful_torch_lock_lines
    assert any(re.match(r"torch==2\.5\.1(?:\s|$)", line) for line in meaningful_torch_lock_lines)
    assert any(re.match(r"torch==2\.5\.1\+cpu(?:\s|$)", line) for line in meaningful_torch_lock_lines)


def test_dependency_lock_inputs_and_generated_locks_are_committed_as_pairs() -> None:
    for stem in ("test", "test-torch-cpu"):
        source = ROOT / "requirements" / f"{stem}.in"
        lock = ROOT / "requirements" / f"{stem}.lock"
        assert source.exists()
        assert lock.exists()
        lock_text = lock.read_text(encoding="utf-8")
        assert "autogenerated by uv" in lock_text
        assert f"requirements/{stem}.in" in lock_text


def test_source_deprecation_warnings_are_registered_in_compatibility_ledger() -> None:
    ledger = (ROOT / "docs" / "COMPATIBILITY_LEDGER.md").read_text(encoding="utf-8")

    class WarningCallCollector(ast.NodeVisitor):
        def __init__(self) -> None:
            self.has_deprecation_warning = False

        def visit_Call(self, node: ast.Call) -> None:
            is_warnings_warn = (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "warnings"
                and node.func.attr == "warn"
            )
            warning_category = node.args[1] if len(node.args) > 1 else next(
                (keyword.value for keyword in node.keywords if keyword.arg == "category"), None
            )
            if is_warnings_warn and isinstance(warning_category, ast.Name) and warning_category.id == "DeprecationWarning":
                self.has_deprecation_warning = True
            self.generic_visit(node)

    warning_files: set[str] = set()
    for path in (ROOT / "src" / "kokoro_tts").rglob("*.py"):
        collector = WarningCallCollector()
        collector.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        if collector.has_deprecation_warning:
            warning_files.add(path.relative_to(ROOT).as_posix())
    assert warning_files
    missing = {path for path in warning_files if path not in ledger}
    assert not missing, f"Register new deprecation seams before merging: {sorted(missing)}"


def test_real_model_smoke_harness_names_all_product_models() -> None:
    def strip_shell_comment(line: str) -> str:
        quote: str | None = None
        escaped = False
        for index, character in enumerate(line):
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif quote:
                if character == quote:
                    quote = None
            elif character in {"'", '"'}:
                quote = character
            elif character == "#":
                return line[:index]
        return line

    calls: set[str] = set()
    call_pattern = re.compile(r"(?:^|[\s$(])speech_request\s+(['\"])([A-Za-z0-9_-]+)\1")
    for raw_line in (ROOT / "scripts" / "e2e_loop_test.sh").read_text(encoding="utf-8").splitlines():
        command_line = strip_shell_comment(raw_line)
        stripped = command_line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = call_pattern.search(command_line)
        if match:
            calls.add(match.group(2))
    assert calls >= {"kokoro", "moss", "zipvoice"}
