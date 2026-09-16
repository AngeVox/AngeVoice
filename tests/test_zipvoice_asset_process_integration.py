"""Real spawn competition for ZipVoice asset publication, with an offline SDK."""

import json
import multiprocessing
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoro_tts.zipvoice.assets import ZipVoiceAssetManager

pytestmark = pytest.mark.integration


def _asset_process(root, vocos, manifest, started, downloading, release, results, action="ensure", timeout=5):
    cfg = SimpleNamespace(
        zipvoice_model_root=Path(root), zipvoice_distill_dir=Path(root) / "distill",
        zipvoice_vocos_dir=Path(vocos), zipvoice_download_enabled=True,
        request_timeout_seconds=timeout,
    )
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        downloading.set()
        if release is not None and not release.wait(15):
            raise TimeoutError("test parent did not release downloader")
        output = Path(kwargs["local_dir"]) / kwargs["filename"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"synthetic-asset")
        return str(output)

    sys.modules["huggingface_hub"] = SimpleNamespace(hf_hub_download=download)
    manager = ZipVoiceAssetManager(cfg, manifest_path=Path(manifest))
    started.set()
    try:
        if action == "hold":
            with manager._asset_locks():
                downloading.set()
                if not release.wait(15):
                    raise TimeoutError("test parent did not release lock")
            results.put(("released", len(calls)))
        else:
            results.put(("ready" if manager.ensure()["ready"] else "not-ready", len(calls)))
    except Exception as exc:
        results.put((type(exc).__name__, len(calls)))


def _manifest(tmp_path, *, reverse=False):
    assets = [
        {"id": name, "repo": "test/repo", "revision": "pinned", "license": "test",
         "filename": name + ".bin", "destination": name + ".bin", "install_root": "vocos_dir", "sha256": None}
        for name in ("one", "two")
    ]
    path = tmp_path / ("reverse.json" if reverse else "forward.json")
    path.write_text(json.dumps({"assets": list(reversed(assets)) if reverse else assets}), encoding="utf-8")
    return path


def _finish(processes):
    for process in processes:
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert all(process.exitcode == 0 for process in processes)


@pytest.mark.parametrize("shared_root", [True, False])
def test_spawn_serializes_ensure_for_shared_assets_with_reversed_manifests(tmp_path, shared_root):
    context = multiprocessing.get_context("spawn")
    root = tmp_path / "first"
    second_root = root if shared_root else tmp_path / "second"
    vocos = tmp_path / "shared-vocos"
    release = context.Event()
    first_started, second_started = context.Event(), context.Event()
    first_download, second_download = context.Event(), context.Event()
    first_result, second_result = context.Queue(), context.Queue()
    first = context.Process(target=_asset_process, args=(root, vocos, _manifest(tmp_path), first_started, first_download, release, first_result))
    second = context.Process(target=_asset_process, args=(second_root, vocos, _manifest(tmp_path, reverse=True), second_started, second_download, None, second_result))
    processes = [first]
    first.start()
    try:
        assert first_download.wait(10)
        second.start()
        processes.append(second)
        assert second_started.wait(10)
        assert not second_download.wait(0.3)
        release.set()
        assert first_result.get(timeout=10) == ("ready", 2)
        assert second_result.get(timeout=10) == ("ready", 0 if shared_root else 2)
    finally:
        release.set()
        _finish(processes)
        first_result.close()
        second_result.close()
    assert not list(vocos.glob(".angevoice-asset-*"))
    for path in (root, second_root):
        saved = json.loads((path / "assets_status.json").read_text(encoding="utf-8"))
        assert set(saved["files"]) == {"one", "two"}


def test_spawn_lock_timeout_prevents_download_then_recovers_after_holder_exits(tmp_path):
    context = multiprocessing.get_context("spawn")
    root, vocos = tmp_path / "root", tmp_path / "vocos"
    manifest = _manifest(tmp_path)
    release, held, started = context.Event(), context.Event(), context.Event()
    queue = context.Queue()
    holder = context.Process(target=_asset_process, args=(root, vocos, manifest, started, held, release, queue, "hold"))
    holder.start()
    try:
        assert held.wait(10)
        cfg = SimpleNamespace(zipvoice_model_root=root, zipvoice_vocos_dir=vocos,
                              zipvoice_distill_dir=root / "distill", zipvoice_download_enabled=False,
                              request_timeout_seconds=0.1)
        manager = ZipVoiceAssetManager(cfg, manifest_path=manifest)
        from filelock import Timeout
        with pytest.raises(Timeout):
            manager.ensure()
        assert not manager.status_path.exists()
    finally:
        release.set()
        _finish([holder])
        queue.close()
    # All partially acquired locks must have been released on timeout.
    with manager._asset_locks():
        pass


def test_spawn_crash_releases_kernel_asset_locks(tmp_path):
    context = multiprocessing.get_context("spawn")
    root, vocos = tmp_path / "root", tmp_path / "vocos"
    manifest = _manifest(tmp_path)
    release, held, queue = context.Event(), context.Event(), context.Queue()
    started = context.Event()
    holder = context.Process(target=_asset_process, args=(root, vocos, manifest, started, held, release, queue, "hold"))
    holder.start()
    try:
        assert held.wait(10)
        holder.terminate()
        holder.join(5)
        assert not holder.is_alive()
        cfg = SimpleNamespace(zipvoice_model_root=root, zipvoice_vocos_dir=vocos, request_timeout_seconds=1)
        manager = ZipVoiceAssetManager(cfg, manifest_path=manifest)
        with manager._asset_locks():
            pass
    finally:
        if holder.is_alive():
            holder.terminate()
            holder.join(5)
        queue.close()
