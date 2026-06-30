"""Import-boundary checks for MOSS runtime helper de-duplication."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_import_probe(module_names: list[str]) -> set[str]:
    script = (
        "import importlib, json, sys\n"
        f"mods = {module_names!r}\n"
        "for name in mods:\n"
        "    importlib.import_module(name)\n"
        "print(json.dumps(sorted(name for name in sys.modules if name.startswith('kokoro_tts.'))))\n"
    )
    env = os.environ.copy()
    src_path = str(ROOT / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return set(json.loads(result.stdout))


def test_moss_runtime_helpers_do_not_import_legacy_moss_or_heavy_boundaries():
    loaded = _run_import_probe([
        "kokoro_tts.moss_runtime.audio",
        "kokoro_tts.moss_runtime.prompt",
        "kokoro_tts.moss_runtime.streaming",
    ])

    forbidden = {
        "kokoro_tts.moss",
        "kokoro_tts.moss.runtime",
        "kokoro_tts.moss.process_worker",
        "kokoro_tts.model_sources",
        "kokoro_tts.admin_config_schema",
        "kokoro_tts.routes.ws",
        "kokoro_tts.routes.status",
        "kokoro_tts.service_state",
    }
    assert not (loaded & forbidden)


def test_legacy_moss_pure_helpers_remain_import_compatible():
    loaded = _run_import_probe([
        "kokoro_tts.moss.postprocess",
        "kokoro_tts.moss.prompt",
        "kokoro_tts.moss.streaming",
    ])

    assert "kokoro_tts.moss_runtime.audio" in loaded
    assert "kokoro_tts.moss_runtime.prompt" in loaded
    assert "kokoro_tts.moss_runtime.streaming" in loaded
