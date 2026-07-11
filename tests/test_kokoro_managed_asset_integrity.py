"""Hermetic contracts for managed Kokoro artifact identity boundaries."""

from __future__ import annotations

import hashlib
import json
import socket
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoro_tts import engine, kokoro_assets, model_sources


HF_REPO = "hexgrad/Kokoro-82M-v1.1-zh"
MS_REPO = "AI-ModelScope/Kokoro-82M-v1.1-zh"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _config(root: Path, *, model_source: str = "offline", hf_repo: str = HF_REPO, ms_repo: str = MS_REPO):
    model_dir = root / "models--hexgrad--Kokoro-82M-v1.1-zh"
    return SimpleNamespace(
        model_dir=model_dir,
        model_file=model_dir / "kokoro-v1_1-zh.pth",
        kokoro_hf_repo=hf_repo,
        kokoro_modelscope_repo=ms_repo,
        model_source=model_source,
        kokoro_prefetch_voices=False,
        resolve_device=lambda: "cpu",
        sample_rate=24000,
        default_voice="af_maple",
        stream_chunk_seconds=1.0,
        device="cpu",
    )


def _install_fake_torch(monkeypatch):
    class Rnn:
        def __init__(self, *_args, **_kwargs):
            pass

    torch = types.ModuleType("torch")
    nn = types.ModuleType("torch.nn")
    nn.LSTM = Rnn
    nn.GRU = Rnn
    nn.RNN = Rnn
    torch.nn = nn
    torch.set_num_threads = lambda _threads: None
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "torch.nn", nn)


@pytest.fixture
def managed(tmp_path, monkeypatch):
    root = tmp_path / "models"
    monkeypatch.setenv("ANGEVOICE_MODELS_ROOT", str(root))
    config_bytes = b'{"model": "fake"}'
    model_bytes = b"PK\x03\x04" + b"m" * (10 * 1024 * 1024)
    voice_bytes = b"PK\x03\x04voice"
    manifest = {
        "schema_version": 1,
        "providers": {
            "huggingface": {"repo": HF_REPO, "revision": "a" * 40},
            "modelscope": {"repo": MS_REPO, "revision": "b" * 40},
        },
        "assets": {
            "config.json": _digest(config_bytes),
            "kokoro-v1_1-zh.pth": _digest(model_bytes),
            "voices/af_maple.pt": _digest(voice_bytes),
        },
    }
    monkeypatch.setattr(kokoro_assets, "managed_kokoro_manifest", lambda: manifest)
    cfg = _config(root)
    cfg.model_dir.mkdir(parents=True)
    (cfg.model_dir / "voices").mkdir()
    (cfg.model_dir / "config.json").write_bytes(config_bytes)
    cfg.model_file.write_bytes(model_bytes)
    (cfg.model_dir / "voices" / "af_maple.pt").write_bytes(voice_bytes)
    return cfg, manifest


def test_bundled_manifest_has_exact_identity_set():
    kokoro_assets.managed_kokoro_manifest.cache_clear()
    manifest = kokoro_assets.managed_kokoro_manifest()
    assert manifest["schema_version"] == 1
    assert len(manifest["assets"]) == 105
    assert sum(key.startswith("voices/") and key.endswith(".pt") for key in manifest["assets"]) == 103
    assert manifest["providers"]["huggingface"]["repo"] == HF_REPO
    assert manifest["providers"]["modelscope"]["repo"] == MS_REPO
    assert manifest["providers"]["huggingface"]["revision"] == "01e7505bd6a7a2ac4975463114c3a7650a9f7218"
    assert manifest["providers"]["modelscope"]["revision"] == "75afdb60a7c1429b9dfc8014cc18330cf800bb80"
    assert all(len(value) == 64 and value == value.lower() for value in manifest["assets"].values())


def test_managed_model_and_config_use_explicit_paths(managed, monkeypatch):
    cfg, _ = managed
    calls = []

    class FakeModel:
        MODEL_NAMES = {}

        def __init__(self, **kwargs):
            calls.append(kwargs)

        def to(self, _device):
            return self

        def eval(self):
            return self

    class FakePipeline:
        def __init__(self, **_kwargs):
            pass

    _install_fake_torch(monkeypatch)
    monkeypatch.setitem(sys.modules, "kokoro", types.SimpleNamespace(KModel=FakeModel, KPipeline=FakePipeline))
    instance = engine.TTSEngine(cfg).load()
    assert instance.is_loaded
    assert calls == [{"repo_id": HF_REPO, "config": str(cfg.model_dir / "config.json"), "model": str(cfg.model_file)}]


@pytest.mark.parametrize("asset_id", ["kokoro-v1_1-zh.pth", "config.json"])
def test_managed_core_mismatch_fails_before_kmodel_and_preserves_bytes(managed, monkeypatch, asset_id):
    cfg, _ = managed
    target = cfg.model_dir / asset_id
    before = target.read_bytes()
    target.write_bytes(before + b"tampered")
    calls = []
    _install_fake_torch(monkeypatch)
    monkeypatch.setitem(sys.modules, "kokoro", types.SimpleNamespace(KModel=lambda **kwargs: calls.append(kwargs), KPipeline=object))
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError, match=asset_id):
        engine.TTSEngine(cfg).load()
    assert calls == []
    assert target.read_bytes() == before + b"tampered"


@pytest.mark.parametrize("provider,expected_revision", [("huggingface", "a" * 40), ("modelscope", "b" * 40)])
def test_managed_downloads_receive_immutable_revision(managed, monkeypatch, provider, expected_revision):
    cfg, _ = managed
    calls = []

    def fake_download(repo, target, *, revision=None, **_kwargs):
        calls.append((repo, revision))
        return target

    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", fake_download)
    monkeypatch.setattr(model_sources, "_modelscope_snapshot_download", fake_download)
    monkeypatch.setattr(model_sources, "_kokoro_download_plan", lambda _cfg, managed: [(provider, HF_REPO if provider == "huggingface" else MS_REPO, expected_revision)])
    result = model_sources._download_kokoro_assets(cfg, cfg.model_dir, logger=model_sources.logger, managed=True)
    assert result == cfg.model_dir
    assert calls == [(HF_REPO if provider == "huggingface" else MS_REPO, expected_revision)]


def test_managed_voice_never_falls_back_to_raw_name(managed):
    cfg, _ = managed
    instance = engine.TTSEngine(cfg)
    assert instance._resolve_voice_for_pipeline("af_maple") == str(cfg.model_dir / "voices" / "af_maple.pt")
    voice = cfg.model_dir / "voices" / "af_maple.pt"
    before = voice.read_bytes()
    voice.write_bytes(before + b"tampered")
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError, match="voices/af_maple.pt"):
        instance._resolve_voice_for_pipeline("af_maple")
    assert voice.read_bytes() == before + b"tampered"


def test_shared_official_name_cannot_be_downgraded_to_custom(managed, tmp_path):
    cfg, _ = managed
    (cfg.model_dir / "voices" / "af_maple.pt").write_bytes(b"PK\x03\x04tampered")
    shared = tmp_path / "models" / "voices"
    shared.mkdir()
    (shared / "af_maple.pt").write_bytes(b"PK\x03\x04also-tampered")
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError):
        engine.TTSEngine(cfg)._resolve_voice_for_pipeline("af_maple")


def test_custom_voice_and_custom_model_mode_remain_available(tmp_path, monkeypatch):
    root = tmp_path / "models"
    monkeypatch.setenv("ANGEVOICE_MODELS_ROOT", str(root))
    custom_dir = tmp_path / "operator-model"
    voices = custom_dir / "voices"
    voices.mkdir(parents=True)
    (voices / "operator.pt").write_bytes(b"PK\x03\x04custom")
    cfg = _config(root, hf_repo="operator/kokoro", ms_repo="operator/kokoro")
    cfg.model_dir = custom_dir
    cfg.model_file = custom_dir / "kokoro-v1_1-zh.pth"
    assert not kokoro_assets.is_managed_kokoro_mode(cfg)
    assert engine.TTSEngine(cfg)._resolve_voice_for_pipeline("operator") == str(voices / "operator.pt")


def test_offline_managed_cache_never_calls_downloader_and_mismatch_fails(managed, monkeypatch):
    cfg, _ = managed
    monkeypatch.setattr(model_sources, "_download_kokoro_assets", lambda *_args, **_kwargs: pytest.fail("downloader called"))
    assert model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger) == cfg.model_dir
    cfg.model_file.write_bytes(cfg.model_file.read_bytes() + b"tampered")
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError):
        model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger)


def test_partial_managed_cache_rejects_tampered_voice_before_any_downloader(managed, monkeypatch):
    cfg, _ = managed
    cfg.model_source = "huggingface"
    cfg.model_file.unlink()
    voice = cfg.model_dir / "voices" / "af_maple.pt"
    before = voice.read_bytes()
    voice.write_bytes(before + b"tampered")
    calls = []
    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", lambda *_args, **_kwargs: calls.append("hf"))
    monkeypatch.setattr(model_sources, "_modelscope_snapshot_download", lambda *_args, **_kwargs: calls.append("ms"))
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError, match="voices/af_maple.pt"):
        model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger)
    assert calls == []
    assert voice.read_bytes() == before + b"tampered"


def test_managed_download_failure_never_uses_repo_only_kmodel(managed, monkeypatch):
    cfg, _ = managed
    cfg.model_source = "huggingface"
    cfg.model_file.unlink()
    calls = []
    _install_fake_torch(monkeypatch)
    monkeypatch.setitem(sys.modules, "kokoro", types.SimpleNamespace(KModel=lambda **kwargs: calls.append(kwargs), KPipeline=object))
    monkeypatch.setattr(model_sources, "_download_kokoro_assets", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="managed official assets"):
        engine.TTSEngine(cfg).load()
    assert calls == []


def test_managed_missing_official_voice_fails_without_raw_fallback(managed):
    cfg, _ = managed
    (cfg.model_dir / "voices" / "af_maple.pt").unlink()
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError, match="voices/af_maple.pt"):
        engine.TTSEngine(cfg)._resolve_voice_for_pipeline("af_maple")


def test_managed_unknown_voice_never_falls_back_to_raw_name(managed, monkeypatch):
    cfg, _ = managed
    network_calls = []
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: network_calls.append("attempted"))
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError, match="voices/operator.pt"):
        engine.TTSEngine(cfg)._resolve_voice_for_pipeline("operator")
    assert network_calls == []


def test_managed_unknown_voice_accepts_only_existing_local_custom_file(managed, monkeypatch):
    cfg, _ = managed
    custom_voice = cfg.model_dir / "voices" / "operator.pt"
    custom_voice.write_bytes(b"PK\x03\x04operator")
    network_calls = []
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: network_calls.append("attempted"))
    assert engine.TTSEngine(cfg)._resolve_voice_for_pipeline("operator") == str(custom_voice)
    assert network_calls == []


def test_valid_managed_cache_hashes_each_present_asset_once_per_ensure(managed, monkeypatch):
    cfg, _ = managed
    original = kokoro_assets.kokoro_file_sha256
    calls = []

    def counted(path):
        calls.append(Path(path).name)
        return original(path)

    monkeypatch.setattr(kokoro_assets, "kokoro_file_sha256", counted)
    assert model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger) == cfg.model_dir
    assert calls.count("config.json") == 1
    assert calls.count("kokoro-v1_1-zh.pth") == 1
    assert calls.count("af_maple.pt") == 1


def test_first_provider_partial_tampered_voice_blocks_second_provider(managed, monkeypatch):
    cfg, manifest = managed
    cfg.model_source = "huggingface"
    cfg.model_file.unlink()
    voice = cfg.model_dir / "voices" / "af_maple.pt"
    voice.unlink()
    calls = []

    def first(_repo, target, **_kwargs):
        calls.append("first")
        (target / "voices" / "af_maple.pt").write_bytes(b"PK\x03\x04tampered")
        return None

    def second(*_args, **_kwargs):
        calls.append("second")
        return None

    monkeypatch.setattr(model_sources, "_kokoro_download_plan", lambda *_args, **_kwargs: [("huggingface", HF_REPO, manifest["providers"]["huggingface"]["revision"]), ("modelscope", MS_REPO, manifest["providers"]["modelscope"]["revision"])])
    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", first)
    monkeypatch.setattr(model_sources, "_modelscope_snapshot_download", second)
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError, match="voices/af_maple.pt"):
        model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger)
    assert calls == ["first"]
    assert voice.read_bytes() == b"PK\x03\x04tampered"


def test_first_provider_legal_partial_output_allows_second_provider(managed, monkeypatch):
    cfg, manifest = managed
    cfg.model_source = "huggingface"
    model_bytes = cfg.model_file.read_bytes()
    voice_bytes = (cfg.model_dir / "voices" / "af_maple.pt").read_bytes()
    cfg.model_file.unlink()
    (cfg.model_dir / "voices" / "af_maple.pt").unlink()
    calls = []

    def first(_repo, target, **_kwargs):
        calls.append("first")
        (target / "voices" / "af_maple.pt").write_bytes(voice_bytes)
        return None

    def second(_repo, target, **_kwargs):
        calls.append("second")
        (target / "kokoro-v1_1-zh.pth").write_bytes(model_bytes)
        return target

    monkeypatch.setattr(model_sources, "_kokoro_download_plan", lambda *_args, **_kwargs: [("huggingface", HF_REPO, manifest["providers"]["huggingface"]["revision"]), ("modelscope", MS_REPO, manifest["providers"]["modelscope"]["revision"])])
    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", first)
    monkeypatch.setattr(model_sources, "_modelscope_snapshot_download", second)
    assert model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger) == cfg.model_dir
    assert calls == ["first", "second"]


def test_valid_managed_engine_load_hashes_core_once_at_loader_boundary(managed, monkeypatch):
    cfg, _ = managed
    calls = []
    original = kokoro_assets.kokoro_file_sha256

    def counted(path):
        calls.append(Path(path).name)
        return original(path)

    class FakeModel:
        MODEL_NAMES = {}

        def __init__(self, **_kwargs):
            pass

        def to(self, _device):
            return self

        def eval(self):
            return self

    _install_fake_torch(monkeypatch)
    monkeypatch.setattr(kokoro_assets, "kokoro_file_sha256", counted)
    monkeypatch.setitem(sys.modules, "kokoro", types.SimpleNamespace(KModel=FakeModel, KPipeline=lambda **_kwargs: object()))
    engine.TTSEngine(cfg).load()
    assert calls.count("config.json") == 1
    assert calls.count("kokoro-v1_1-zh.pth") == 1


def test_prefetch_download_hashes_present_assets_once_before_provider(managed, monkeypatch):
    cfg, _ = managed
    cfg.model_source = "huggingface"
    cfg.kokoro_prefetch_voices = True
    model_bytes = cfg.model_file.read_bytes()
    voice = cfg.model_dir / "voices" / "af_maple.pt"
    voice_bytes = voice.read_bytes()
    calls = []
    original = kokoro_assets.kokoro_file_sha256

    def counted(path):
        calls.append(Path(path).name)
        return original(path)

    def downloader(_repo, target, **_kwargs):
        assert calls.count("config.json") == 1
        assert calls.count("kokoro-v1_1-zh.pth") == 1
        assert calls.count("af_maple.pt") == 1
        (target / "voices" / "af_sol.pt").write_bytes(voice_bytes)
        return target

    monkeypatch.setattr(kokoro_assets, "kokoro_file_sha256", counted)
    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", downloader)
    monkeypatch.setattr(model_sources, "_kokoro_download_plan", lambda *_args, **_kwargs: [("huggingface", HF_REPO, "a" * 40)])
    assert model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger) == cfg.model_dir
    assert model_bytes == cfg.model_file.read_bytes()


def test_official_repo_missing_custom_dir_transitions_to_managed_target(managed, tmp_path, monkeypatch):
    cfg, manifest = managed
    cfg.model_source = "huggingface"
    cfg.model_dir = tmp_path / "missing-operator-dir"
    cfg.model_file = cfg.model_dir / "kokoro-v1_1-zh.pth"
    target = kokoro_assets.default_kokoro_model_dir()
    target.mkdir(parents=True, exist_ok=True)
    (target / "voices").mkdir(exist_ok=True)
    for item in target.rglob("*"):
        if item.is_file():
            item.unlink()
    config_bytes = b'{"model": "fake"}'
    model_bytes = b"PK\x03\x04" + b"m" * (10 * 1024 * 1024)
    voice_bytes = b"PK\x03\x04voice"
    received = []

    def downloader(_repo, destination, *, revision=None, **_kwargs):
        received.append(revision)
        (destination / "config.json").write_bytes(config_bytes)
        (destination / "kokoro-v1_1-zh.pth").write_bytes(model_bytes)
        (destination / "voices" / "af_maple.pt").write_bytes(voice_bytes)
        return destination

    manifest["assets"] = {"config.json": _digest(config_bytes), "kokoro-v1_1-zh.pth": _digest(model_bytes), "voices/af_maple.pt": _digest(voice_bytes)}
    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", downloader)
    monkeypatch.setattr(model_sources, "_kokoro_download_plan", lambda *_args, **_kwargs: [("huggingface", HF_REPO, manifest["providers"]["huggingface"]["revision"])])
    assert model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger) == target
    assert received == ["a" * 40]


def test_managed_download_rejects_nonmanaged_provider_candidate_before_kmodel(managed, tmp_path, monkeypatch):
    cfg, manifest = managed
    original_dir = cfg.model_dir
    config_bytes = (cfg.model_dir / "config.json").read_bytes()
    model_bytes = cfg.model_file.read_bytes()
    voice_bytes = (cfg.model_dir / "voices" / "af_maple.pt").read_bytes()
    cfg.model_source = "huggingface"
    cfg.model_file.unlink()
    external = tmp_path / "provider-output"
    (external / "voices").mkdir(parents=True)
    (external / "config.json").write_bytes(config_bytes)
    (external / "kokoro-v1_1-zh.pth").write_bytes(model_bytes)
    (external / "voices" / "af_maple.pt").write_bytes(voice_bytes)
    calls = []
    _install_fake_torch(monkeypatch)
    monkeypatch.setitem(sys.modules, "kokoro", types.SimpleNamespace(KModel=lambda **kwargs: calls.append(kwargs), KPipeline=object))
    monkeypatch.setattr(model_sources, "_kokoro_download_plan", lambda *_args, **_kwargs: [("huggingface", HF_REPO, manifest["providers"]["huggingface"]["revision"])])
    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", lambda *_args, **_kwargs: external)
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError, match="non-managed candidate"):
        engine.TTSEngine(cfg).load()
    assert cfg.model_dir == original_dir
    assert calls == []


def test_offline_custom_model_with_incomplete_prefetch_remains_usable(tmp_path, monkeypatch):
    root = tmp_path / "models"
    monkeypatch.setenv("ANGEVOICE_MODELS_ROOT", str(root))
    custom_dir = tmp_path / "operator-model"
    (custom_dir / "voices").mkdir(parents=True)
    (custom_dir / "config.json").write_bytes(b'{"model": "custom"}')
    (custom_dir / "kokoro-v1_1-zh.pth").write_bytes(b"PK\x03\x04" + b"m" * (10 * 1024 * 1024))
    cfg = _config(root, hf_repo="operator/kokoro", ms_repo="operator/kokoro")
    cfg.model_dir = custom_dir
    cfg.model_file = custom_dir / "kokoro-v1_1-zh.pth"
    cfg.kokoro_prefetch_voices = True
    monkeypatch.setattr(model_sources, "_download_kokoro_assets", lambda *_args, **_kwargs: pytest.fail("downloader called"))
    assert model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger) == custom_dir


def test_managed_provider_exception_stops_fail_closed_without_partial_output(managed, monkeypatch):
    cfg, manifest = managed
    cfg.model_source = "huggingface"
    cfg.model_file.unlink()
    original_error = OSError("provider unavailable")
    calls = []

    def first(*_args, **_kwargs):
        calls.append("first")
        raise original_error

    def second(*_args, **_kwargs):
        calls.append("second")
        return None

    monkeypatch.setattr(model_sources, "_kokoro_download_plan", lambda *_args, **_kwargs: [("huggingface", HF_REPO, manifest["providers"]["huggingface"]["revision"]), ("modelscope", MS_REPO, manifest["providers"]["modelscope"]["revision"])])
    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", first)
    monkeypatch.setattr(model_sources, "_modelscope_snapshot_download", second)
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError, match="provider download failed") as raised:
        model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger)
    assert raised.value.__cause__ is original_error
    assert calls == ["first"]


def test_managed_provider_exception_reports_written_tampered_asset(managed, monkeypatch):
    cfg, manifest = managed
    cfg.model_source = "huggingface"
    cfg.model_file.unlink()
    voice = cfg.model_dir / "voices" / "af_maple.pt"
    calls = []

    def first(_repo, target, **_kwargs):
        calls.append("first")
        (target / "voices" / "af_maple.pt").write_bytes(b"PK\x03\x04tampered")
        raise OSError("provider interrupted")

    def second(*_args, **_kwargs):
        calls.append("second")
        return None

    monkeypatch.setattr(model_sources, "_kokoro_download_plan", lambda *_args, **_kwargs: [("huggingface", HF_REPO, manifest["providers"]["huggingface"]["revision"]), ("modelscope", MS_REPO, manifest["providers"]["modelscope"]["revision"])])
    monkeypatch.setattr(model_sources, "_huggingface_snapshot_download", first)
    monkeypatch.setattr(model_sources, "_modelscope_snapshot_download", second)
    with pytest.raises(kokoro_assets.KokoroAssetIntegrityError, match="voices/af_maple.pt"):
        model_sources.ensure_kokoro_model_dir(cfg, logger=model_sources.logger)
    assert calls == ["first"]
    assert voice.read_bytes() == b"PK\x03\x04tampered"


def test_package_data_declares_manifest():
    project = Path(__file__).parents[1] / "pyproject.toml"
    assert "kokoro_assets_manifest.json" in project.read_text(encoding="utf-8")
