"""P2F-C contracts for model-asset integrity and destination ownership.

Behavior contracts in this module freeze the current family-specific rules.
Characterization and static-ownership tests document missing project controls;
they are not safety endorsements or recommendations for future design.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import logging
import os
import socket
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoro_tts import kokoro_assets, model_sources
from kokoro_tts.zipvoice import assets as zipvoice_assets


PACKAGE_ROOT = Path(model_sources.__file__).resolve().parent
HF_REPO = "hexgrad/Kokoro-82M-v1.1-zh"
HF_REVISION = "01e7505bd6a7a2ac4975463114c3a7650a9f7218"
MS_REPO = "AI-ModelScope/Kokoro-82M-v1.1-zh"
MS_REVISION = "75afdb60a7c1429b9dfc8014cc18330cf800bb80"
LFS_POINTER = (
    b"version https://git-lfs.github.com/spec/v1\n"
    b"oid sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
    b"size 1048576\n"
)

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _forbid_real_network(monkeypatch):
    """Fail immediately if a P2F-C contract drifts into real networking."""

    def fail_network(*_args, **_kwargs):
        pytest.fail("P2F-C contracts must not access the network")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(socket.socket, "connect", fail_network)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _sized_file(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)
    return path


def _install_fake_huggingface(monkeypatch, downloader) -> None:
    module = types.ModuleType("huggingface_hub")
    module.snapshot_download = downloader
    module.hf_hub_download = downloader
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)


def _install_fake_modelscope(monkeypatch, downloader) -> None:
    root = types.ModuleType("modelscope")
    root.__path__ = []
    hub = types.ModuleType("modelscope.hub")
    hub.__path__ = []
    snapshot = types.ModuleType("modelscope.hub.snapshot_download")
    snapshot.snapshot_download = downloader
    monkeypatch.setitem(sys.modules, "modelscope", root)
    monkeypatch.setitem(sys.modules, "modelscope.hub", hub)
    monkeypatch.setitem(sys.modules, "modelscope.hub.snapshot_download", snapshot)


def _managed_fixture(tmp_path: Path, monkeypatch):
    models_root = tmp_path / "managed-models"
    monkeypatch.setenv("ANGEVOICE_MODELS_ROOT", str(models_root))
    model_dir = kokoro_assets.default_kokoro_model_dir()
    config_bytes = b'{"model": "synthetic"}'
    model_bytes = b"PK\x03\x04synthetic-model"
    voice_bytes = b"PK\x03\x04synthetic-voice"
    manifest = {
        "schema_version": 1,
        "providers": {
            "huggingface": {"repo": HF_REPO, "revision": HF_REVISION},
            "modelscope": {"repo": MS_REPO, "revision": MS_REVISION},
        },
        "assets": {
            "config.json": _digest(config_bytes),
            kokoro_assets.KOKORO_MODEL_FILENAME: _digest(model_bytes),
            "voices/af_maple.pt": _digest(voice_bytes),
        },
    }
    monkeypatch.setattr(kokoro_assets, "managed_kokoro_manifest", lambda: manifest)
    model_dir.mkdir(parents=True)
    (model_dir / "voices").mkdir()
    (model_dir / "config.json").write_bytes(config_bytes)
    (model_dir / kokoro_assets.KOKORO_MODEL_FILENAME).write_bytes(model_bytes)
    (model_dir / "voices" / "af_maple.pt").write_bytes(voice_bytes)
    cfg = SimpleNamespace(
        model_dir=model_dir,
        kokoro_hf_repo=HF_REPO,
        kokoro_modelscope_repo=MS_REPO,
        model_source="huggingface",
        kokoro_prefetch_voices=False,
    )
    return cfg, manifest, {
        "config.json": config_bytes,
        kokoro_assets.KOKORO_MODEL_FILENAME: model_bytes,
        "voices/af_maple.pt": voice_bytes,
    }


def _ordinary_config(model_dir: Path):
    return SimpleNamespace(
        model_dir=model_dir,
        kokoro_hf_repo="operator/kokoro",
        kokoro_modelscope_repo="operator/kokoro",
        model_source="huggingface",
        kokoro_prefetch_voices=False,
    )


def _make_ordinary_complete(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_bytes(b'{"model": "operator"}')
    (model_dir / kokoro_assets.KOKORO_MODEL_FILENAME).write_bytes(
        b"PK\x03\x04operator-model"
    )


def _make_moss_complete(root: Path, sentinel: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / sentinel).write_bytes(b"{}")
    _sized_file(root / "weights.data", 1024 * 1024)


def _zip_item(
    *,
    asset_id: str = "asset",
    payload_digest: str | None,
    destination: str = "zipvoice_distill/asset.bin",
    install_root: str = "model_root",
) -> dict:
    return {
        "id": asset_id,
        "repo": "synthetic/repository",
        "revision": "synthetic-pinned-revision",
        "license": "Apache-2.0",
        "filename": destination,
        "install_root": install_root,
        "destination": destination,
        "sha256": payload_digest,
        "verification_policy": (
            "strict_sha256"
            if payload_digest
            else "record_first_verified_download"
        ),
    }


def _zip_manager(
    tmp_path: Path,
    item: dict,
    *,
    download_enabled: bool = True,
):
    model_root = tmp_path / "zipvoice-models"
    cfg = SimpleNamespace(
        zipvoice_model_root=model_root,
        zipvoice_distill_dir=model_root / "zipvoice_distill",
        zipvoice_vocos_dir=model_root / "vocos",
        zipvoice_download_enabled=download_enabled,
    )
    manifest_path = tmp_path / "synthetic-zipvoice-manifest.json"
    _write_json(
        manifest_path,
        {"schema_version": 1, "runtime": "synthetic", "assets": [item]},
    )
    manager = zipvoice_assets.ZipVoiceAssetManager(
        cfg, manifest_path=manifest_path
    )
    return manager, manager._destination(item)


class TestManagedKokoroManifestIntegrity:
    def test_bundled_manifest_exact_shape_and_canonical_identity(self):
        """BEHAVIOR CONTRACT: the official manifest is the crypto owner."""

        kokoro_assets.managed_kokoro_manifest.cache_clear()
        manifest = kokoro_assets.managed_kokoro_manifest()
        assets = manifest["assets"]
        normalized = [
            kokoro_assets._normalized_asset_id(asset_id) for asset_id in assets
        ]

        assert manifest["schema_version"] == 1
        assert len(assets) == 105
        assert {"config.json", kokoro_assets.KOKORO_MODEL_FILENAME} <= set(
            assets
        )
        assert sum(
            name.startswith("voices/") and name.endswith(".pt")
            for name in assets
        ) == 103
        assert len(normalized) == len(set(normalized)) == 105
        assert normalized == list(assets)
        assert all(
            len(digest) == 64
            and digest == digest.lower()
            and set(digest) <= set("0123456789abcdef")
            for digest in assets.values()
        )
        assert manifest["providers"] == {
            "huggingface": {"repo": HF_REPO, "revision": HF_REVISION},
            "modelscope": {"repo": MS_REPO, "revision": MS_REVISION},
        }

    @pytest.mark.parametrize(
        "invalid_id",
        (
            "../voices/escape.pt",
            "/voices/absolute.pt",
            "C:/voices/drive.pt",
        ),
    )
    def test_manifest_rejects_noncanonical_or_escaping_asset_sets(
        self, invalid_id
    ):
        """BEHAVIOR CONTRACT: malformed identities cannot replace a voice."""

        kokoro_assets.managed_kokoro_manifest.cache_clear()
        assets = dict(kokoro_assets.managed_kokoro_manifest()["assets"])
        removed = next(name for name in assets if name.startswith("voices/"))
        digest = assets.pop(removed)
        assets[invalid_id] = digest

        with pytest.raises(kokoro_assets.KokoroAssetIntegrityError):
            kokoro_assets._validate_managed_assets(assets)

    def test_manifest_rejects_normalization_alias_as_duplicate_identity(self):
        """BEHAVIOR CONTRACT: an alias cannot replace a canonical asset."""

        kokoro_assets.managed_kokoro_manifest.cache_clear()
        assets = dict(kokoro_assets.managed_kokoro_manifest()["assets"])
        removed = next(
            name
            for name in assets
            if name.startswith("voices/") and name != "voices/af_maple.pt"
        )
        assets.pop(removed)
        assets["voices\\af_maple.pt"] = assets["voices/af_maple.pt"]

        with pytest.raises(kokoro_assets.KokoroAssetIntegrityError):
            kokoro_assets._validate_managed_assets(assets)

    def test_valid_existing_assets_bypass_provider_executor(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: valid managed bytes are verified and reused."""

        cfg, _manifest, _payloads = _managed_fixture(tmp_path, monkeypatch)
        monkeypatch.setattr(
            model_sources,
            "_download_kokoro_assets",
            lambda *_args, **_kwargs: pytest.fail("provider executor called"),
        )

        result = model_sources.ensure_kokoro_model_dir(
            cfg, logger=logging.getLogger("p2f-c-managed-valid")
        )

        assert result == cfg.model_dir
        kokoro_assets.verify_managed_kokoro_core_assets(cfg.model_dir)
        kokoro_assets.verify_managed_kokoro_present_voices(cfg.model_dir)


class TestManagedKokoroFailurePreservation:
    @pytest.mark.parametrize(
        "asset_id", ("config.json", kokoro_assets.KOKORO_MODEL_FILENAME)
    )
    def test_existing_corruption_fails_before_provider_and_preserves_bytes(
        self, tmp_path, monkeypatch, asset_id
    ):
        """BEHAVIOR CONTRACT: managed existing corruption fails closed."""

        cfg, _manifest, _payloads = _managed_fixture(tmp_path, monkeypatch)
        target = cfg.model_dir / asset_id
        corrupted = target.read_bytes() + b"-corrupt"
        target.write_bytes(corrupted)
        monkeypatch.setattr(
            model_sources,
            "_download_kokoro_assets",
            lambda *_args, **_kwargs: pytest.fail("provider executor called"),
        )

        with pytest.raises(
            kokoro_assets.KokoroAssetIntegrityError, match=asset_id
        ):
            model_sources.ensure_kokoro_model_dir(
                cfg, logger=logging.getLogger("p2f-c-managed-corrupt")
            )

        assert target.read_bytes() == corrupted

    def test_post_download_mismatch_stops_fallback_and_preserves_bytes(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: managed post-download verification is terminal."""

        cfg, manifest, _payloads = _managed_fixture(tmp_path, monkeypatch)
        model_path = cfg.model_dir / kokoro_assets.KOKORO_MODEL_FILENAME
        model_path.unlink()
        calls: list[str] = []
        wrong = b"PK\x03\x04wrong-managed-model"

        def first(_repo, target, **_kwargs):
            calls.append("huggingface")
            (target / kokoro_assets.KOKORO_MODEL_FILENAME).write_bytes(wrong)
            return target

        def second(*_args, **_kwargs):
            calls.append("modelscope")
            return None

        monkeypatch.setattr(
            model_sources,
            "_kokoro_download_plan",
            lambda *_args, **_kwargs: [
                ("huggingface", HF_REPO, HF_REVISION),
                ("modelscope", MS_REPO, MS_REVISION),
            ],
        )
        monkeypatch.setattr(
            model_sources, "_huggingface_snapshot_download", first
        )
        monkeypatch.setattr(
            model_sources, "_modelscope_snapshot_download", second
        )

        with pytest.raises(
            kokoro_assets.KokoroAssetIntegrityError,
            match=kokoro_assets.KOKORO_MODEL_FILENAME,
        ):
            model_sources.ensure_kokoro_model_dir(
                cfg, logger=logging.getLogger("p2f-c-managed-post-download")
            )

        assert calls == ["huggingface"]
        assert model_path.read_bytes() == wrong
        assert manifest["assets"][kokoro_assets.KOKORO_MODEL_FILENAME] != _digest(
            wrong
        )


class TestOrdinaryKokoroHeuristicIntegrity:
    def test_ordinary_rules_are_heuristic_and_not_manifest_identity(
        self, tmp_path
    ):
        """BEHAVIOR CONTRACT: HEURISTIC COMPLETENESS, NOT CRYPTOGRAPHIC IDENTITY."""

        model_dir = tmp_path / "operator-kokoro"
        _make_ordinary_complete(model_dir)
        assert kokoro_assets.has_valid_kokoro_local_assets(model_dir)
        assert not (model_dir / "assets_manifest.json").exists()
        assert model_sources._kokoro_voice_count(model_dir) == 0

        (model_dir / "config.json").unlink()
        assert not kokoro_assets.has_valid_kokoro_local_assets(model_dir)

    @pytest.mark.parametrize(
        "payload",
        (
            b"",
            LFS_POINTER,
            b"small plain-text placeholder",
        ),
    )
    def test_invalid_model_file_forms_are_rejected_and_preserved(
        self, tmp_path, payload
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION: invalid bytes are not cleaned."""

        model_dir = tmp_path / ("ordinary-" + _digest(payload)[:8])
        model_dir.mkdir()
        (model_dir / "config.json").write_bytes(b"{}")
        model_path = model_dir / kokoro_assets.KOKORO_MODEL_FILENAME
        model_path.write_bytes(payload)

        assert not kokoro_assets.has_valid_kokoro_local_assets(model_dir)
        assert model_path.read_bytes() == payload

    def test_complete_operator_destination_bypasses_download(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: operator-complete ordinary assets are reused."""

        model_dir = tmp_path / "operator-controlled" / "kokoro"
        _make_ordinary_complete(model_dir)
        cfg = _ordinary_config(model_dir)
        monkeypatch.setattr(
            model_sources,
            "_download_kokoro_assets",
            lambda *_args, **_kwargs: pytest.fail("downloader called"),
        )

        assert (
            model_sources.ensure_kokoro_model_dir(
                cfg, logger=logging.getLogger("p2f-c-ordinary-complete")
            )
            == model_dir
        )
        assert cfg.model_dir == model_dir

    def test_failed_executor_partial_is_invalid_and_preserved(
        self, tmp_path, monkeypatch
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION: no general partial cleanup."""

        target = tmp_path / "operator-partial-kokoro"
        cfg = _ordinary_config(target)
        partial = target / "partial-model.bin"

        def downloader(_repo, destination, **_kwargs):
            destination.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"partial ordinary bytes")
            return None

        monkeypatch.setattr(
            model_sources,
            "_kokoro_download_plan",
            lambda *_args, **_kwargs: [
                ("huggingface", "operator/kokoro", None)
            ],
        )
        monkeypatch.setattr(
            model_sources, "_huggingface_snapshot_download", downloader
        )

        assert (
            model_sources._download_kokoro_assets(
                cfg,
                target,
                logger=logging.getLogger("p2f-c-ordinary-partial"),
                managed=False,
            )
            is None
        )
        assert partial.read_bytes() == b"partial ordinary bytes"
        assert not kokoro_assets.has_valid_kokoro_local_assets(target)


class TestMossModelHeuristicIntegrity:
    def test_model_suffix_sentinel_size_and_placeholder_rules(self, tmp_path):
        """BEHAVIOR CONTRACT: MOSS completeness is heuristic and non-crypto."""

        assert model_sources._MOSS_VALID_MODEL_SUFFIXES == {
            ".onnx",
            ".ort",
            ".bin",
            ".safetensors",
            ".data",
        }

        missing_sentinel = tmp_path / "model-missing-sentinel"
        _sized_file(missing_sentinel / "weights.data", 1024 * 1024)
        assert not model_sources.has_valid_moss_model_assets(missing_sentinel)

        missing_weight = tmp_path / "model-missing-weight"
        missing_weight.mkdir()
        (missing_weight / "browser_poc_manifest.json").write_bytes(b"{}")
        assert not model_sources.has_valid_moss_model_assets(missing_weight)

        too_small = tmp_path / "model-too-small"
        too_small.mkdir()
        (too_small / "browser_poc_manifest.json").write_bytes(b"{}")
        _sized_file(too_small / "weights.data", 1024 * 1024 - 1)
        assert not model_sources.has_valid_moss_model_assets(too_small)

        zero = tmp_path / "model-zero"
        zero.mkdir()
        (zero / "browser_poc_manifest.json").write_bytes(b"{}")
        (zero / "weights.data").write_bytes(b"")
        assert not model_sources.has_valid_moss_model_assets(zero)

        hidden = tmp_path / "model-hidden"
        hidden.mkdir()
        (hidden / "browser_poc_manifest.json").write_bytes(b"{}")
        _sized_file(hidden / ".partial" / "weights.data", 1024 * 1024)
        assert not model_sources.has_valid_moss_model_assets(hidden)

        lfs = tmp_path / "model-lfs"
        lfs.mkdir()
        (lfs / "browser_poc_manifest.json").write_bytes(b"{}")
        (lfs / "weights.data").write_bytes(LFS_POINTER)
        assert not model_sources.has_valid_moss_model_assets(lfs)

        complete = tmp_path / "model-complete"
        _make_moss_complete(complete, "browser_poc_manifest.json")
        assert model_sources.has_valid_moss_model_assets(complete)
        assert not (complete / "sha256-manifest.json").exists()

    def test_complete_model_bypasses_executor(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: complete model assets bypass providers."""

        target = tmp_path / "operator-moss-model"
        _make_moss_complete(target, "browser_poc_manifest.json")
        cfg = SimpleNamespace(
            moss_model_dir=target, model_source="huggingface"
        )
        monkeypatch.setattr(
            model_sources,
            "_download_moss_model_assets",
            lambda *_args, **_kwargs: pytest.fail("model executor called"),
        )

        assert (
            model_sources.ensure_moss_model_dir(
                cfg, logger=logging.getLogger("p2f-c-moss-model-complete")
            )
            == target
        )

    def test_failed_model_executor_preserves_partial_bytes(
        self, tmp_path, monkeypatch
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION: model partials remain."""

        target = tmp_path / "moss-model-partial"
        partial = target / "interrupted.data"
        cfg = SimpleNamespace(model_source="huggingface")

        def downloader(_repo, destination, **_kwargs):
            destination.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"partial moss model")
            return destination

        monkeypatch.setattr(
            model_sources,
            "_moss_download_plan",
            lambda _cfg: [("huggingface", "synthetic/moss")],
        )
        monkeypatch.setattr(
            model_sources, "_huggingface_snapshot_download", downloader
        )

        assert (
            model_sources._download_moss_model_assets(
                cfg,
                target,
                logger=logging.getLogger("p2f-c-moss-model-partial"),
            )
            is None
        )
        assert partial.read_bytes() == b"partial moss model"
        assert not model_sources.has_valid_moss_model_assets(target)


class TestMossTokenizerHeuristicIntegrity:
    def test_model_and_tokenizer_sentinels_are_independent(self, tmp_path):
        """BEHAVIOR CONTRACT: the two heuristic families cannot substitute."""

        model = tmp_path / "moss-model"
        tokenizer = tmp_path / "moss-tokenizer"
        _make_moss_complete(model, "browser_poc_manifest.json")
        _make_moss_complete(tokenizer, "codec_browser_onnx_meta.json")

        assert model_sources.has_valid_moss_model_assets(model)
        assert not model_sources.has_valid_moss_audio_tokenizer_assets(model)
        assert model_sources.has_valid_moss_audio_tokenizer_assets(tokenizer)
        assert not model_sources.has_valid_moss_model_assets(tokenizer)

        wrong_model = tmp_path / "wrong-model"
        _make_moss_complete(wrong_model, "codec_browser_onnx_meta.json")
        wrong_tokenizer = tmp_path / "wrong-tokenizer"
        _make_moss_complete(wrong_tokenizer, "browser_poc_manifest.json")
        assert not model_sources.has_valid_moss_model_assets(wrong_model)
        assert not model_sources.has_valid_moss_audio_tokenizer_assets(
            wrong_tokenizer
        )

    def test_complete_tokenizer_bypasses_executor_and_keeps_target(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: complete tokenizer assets stay independent."""

        model_target = tmp_path / "model-target"
        tokenizer_target = tmp_path / "tokenizer-target"
        _make_moss_complete(model_target, "browser_poc_manifest.json")
        _make_moss_complete(
            tokenizer_target, "codec_browser_onnx_meta.json"
        )
        cfg = SimpleNamespace(
            moss_model_dir=model_target,
            moss_audio_tokenizer_model_dir=tokenizer_target,
            model_source="huggingface",
        )
        monkeypatch.setattr(
            model_sources,
            "_download_moss_audio_tokenizer_assets",
            lambda *_args, **_kwargs: pytest.fail("tokenizer executor called"),
        )

        assert (
            model_sources.ensure_moss_audio_tokenizer_dir(
                cfg, logger=logging.getLogger("p2f-c-tokenizer-complete")
            )
            == tokenizer_target
        )
        assert cfg.moss_model_dir == model_target
        assert cfg.moss_audio_tokenizer_model_dir == tokenizer_target

    def test_failed_tokenizer_executor_preserves_partial_bytes(
        self, tmp_path, monkeypatch
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION: tokenizer partials remain."""

        target = tmp_path / "moss-tokenizer-partial"
        partial = target / "interrupted.onnx"
        cfg = SimpleNamespace(model_source="huggingface")

        def downloader(_repo, destination, **_kwargs):
            destination.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"partial tokenizer")
            return destination

        monkeypatch.setattr(
            model_sources,
            "_moss_audio_tokenizer_download_plan",
            lambda _cfg: [("huggingface", "synthetic/tokenizer")],
        )
        monkeypatch.setattr(
            model_sources, "_huggingface_snapshot_download", downloader
        )

        assert (
            model_sources._download_moss_audio_tokenizer_assets(
                cfg,
                target,
                logger=logging.getLogger("p2f-c-tokenizer-partial"),
            )
            is None
        )
        assert partial.read_bytes() == b"partial tokenizer"
        assert not model_sources.has_valid_moss_audio_tokenizer_assets(target)


class TestZipVoiceManifestModes:
    def test_cpu_and_cuda_manifest_modes_remain_distinct(self):
        """BEHAVIOR CONTRACT: bundled digest modes are family data."""

        root = PACKAGE_ROOT / "zipvoice"
        cpu = json.loads(
            (root / "assets_manifest.json").read_text(encoding="utf-8")
        )
        cuda = json.loads(
            (root / "assets_manifest_cuda.json").read_text(encoding="utf-8")
        )

        assert len(cpu["assets"]) == 6
        assert len(cuda["assets"]) == 7
        assert sum(item["sha256"] is not None for item in cpu["assets"]) == 3
        assert sum(item["sha256"] is None for item in cpu["assets"]) == 3
        assert sum(item["sha256"] is not None for item in cuda["assets"]) == 4
        assert sum(item["sha256"] is None for item in cuda["assets"]) == 3
        assert {
            item["verification_policy"] for item in cpu["assets"]
        } == {"strict_sha256", "record_first_verified_download"}
        assert {
            item["verification_policy"] for item in cuda["assets"]
        } == {"strict_sha256", "record_first_verified_download"}
        assert {item["id"] for item in cuda["assets"]} - {
            item["id"] for item in cpu["assets"]
        } == {"zipvoice_distill_model_pt"}

    def test_default_manager_uses_bundled_manifest_not_runtime_input(
        self, tmp_path
    ):
        """STATIC OWNERSHIP CONTRACT: the default manifest is packaged data."""

        cfg = SimpleNamespace(
            zipvoice_model_root=tmp_path / "models",
            zipvoice_distill_dir=tmp_path / "models" / "distill",
            zipvoice_vocos_dir=tmp_path / "models" / "vocos",
        )
        manager = zipvoice_assets.ZipVoiceAssetManager(cfg)

        assert manager.manifest_path == Path(
            zipvoice_assets.__file__
        ).with_name("assets_manifest.json")
        assert len(manager.manifest["assets"]) == 6


class TestZipVoiceStrictDigest:
    def test_existing_strict_asset_bypasses_download(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: a correct declared digest is locally complete."""

        payload = b"strict verified bytes"
        item = _zip_item(payload_digest=_digest(payload))
        manager, destination = _zip_manager(tmp_path, item)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(payload)
        calls = []
        _install_fake_huggingface(
            monkeypatch, lambda **kwargs: calls.append(kwargs)
        )

        assert manager.ensure()["ready"] is True
        assert calls == []
        assert destination.read_bytes() == payload

    def test_existing_strict_mismatch_fails_closed_and_preserves_bytes(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: declared mismatch is terminal."""

        item = _zip_item(payload_digest=_digest(b"expected strict bytes"))
        manager, destination = _zip_manager(tmp_path, item)
        destination.parent.mkdir(parents=True)
        wrong = b"wrong strict bytes"
        destination.write_bytes(wrong)
        calls = []
        _install_fake_huggingface(
            monkeypatch, lambda **kwargs: calls.append(kwargs)
        )

        with pytest.raises(
            zipvoice_assets.ZipVoiceAssetIntegrityError, match="declared"
        ):
            manager.ensure()

        assert calls == []
        assert destination.read_bytes() == wrong
        assert not manager.status_path.exists()

    def test_post_download_strict_mismatch_is_preserved(
        self, tmp_path, monkeypatch
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION: no corrupt-byte cleanup."""

        item = _zip_item(payload_digest=_digest(b"expected download"))
        manager, destination = _zip_manager(tmp_path, item)
        wrong = b"wrong downloaded bytes"

        def downloader(**kwargs):
            output = Path(kwargs["local_dir"]) / kwargs["filename"]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(wrong)
            return str(output)

        _install_fake_huggingface(monkeypatch, downloader)

        with pytest.raises(
            zipvoice_assets.ZipVoiceAssetIntegrityError, match="declared"
        ):
            manager.ensure()

        assert destination.read_bytes() == wrong
        assert not manager.status_path.exists()

    def test_declared_digest_overrides_recorded_status(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: bundled strict identity is authoritative."""

        declared = b"declared authoritative"
        recorded = b"recorded but not declared"
        item = _zip_item(payload_digest=_digest(declared))
        manager, destination = _zip_manager(tmp_path, item)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(recorded)
        _write_json(
            manager.status_path,
            {
                "files": {
                    item["id"]: {
                        "sha256": _digest(recorded),
                        "verification_status": "verified",
                    }
                }
            },
        )
        calls = []
        _install_fake_huggingface(
            monkeypatch, lambda **kwargs: calls.append(kwargs)
        )

        with pytest.raises(
            zipvoice_assets.ZipVoiceAssetIntegrityError, match="declared"
        ):
            manager.ensure()

        assert calls == []
        assert destination.read_bytes() == recorded


class TestZipVoiceRecordFirstDigest:
    def test_existing_unrecorded_asset_refreshes_then_reuses_digest(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: first verified download establishes identity."""

        item = _zip_item(
            asset_id="metadata",
            payload_digest=None,
            destination="zipvoice_distill/metadata.json",
        )
        manager, destination = _zip_manager(tmp_path, item)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"untrusted existing bytes")
        trusted = b"trusted refreshed bytes"
        calls = []

        def downloader(**kwargs):
            calls.append(kwargs)
            output = Path(kwargs["local_dir"]) / kwargs["filename"]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(trusted)
            return str(output)

        _install_fake_huggingface(monkeypatch, downloader)
        assert manager.ensure()["ready"] is True
        saved = json.loads(
            manager.status_path.read_text(encoding="utf-8")
        )["files"]["metadata"]
        assert calls[0]["force_download"] is True
        assert saved["sha256"] == _digest(trusted)
        assert destination.read_bytes() == trusted

        calls.clear()
        assert manager.ensure()["ready"] is True
        assert calls == []
        assert destination.read_bytes() == trusted

    def test_recorded_mismatch_fails_closed_when_downloads_disabled(
        self, tmp_path
    ):
        """BEHAVIOR CONTRACT: recorded mismatch is not silently trusted."""

        item = _zip_item(
            asset_id="metadata",
            payload_digest=None,
            destination="zipvoice_distill/metadata.json",
        )
        manager, destination = _zip_manager(
            tmp_path, item, download_enabled=False
        )
        destination.parent.mkdir(parents=True)
        wrong = b"tampered recorded bytes"
        destination.write_bytes(wrong)
        status = {
            "files": {
                "metadata": {
                    "sha256": _digest(b"recorded expected bytes"),
                    "verification_status": "verified",
                }
            }
        }
        _write_json(manager.status_path, status)
        status_before = manager.status_path.read_bytes()

        with pytest.raises(
            zipvoice_assets.ZipVoiceAssetIntegrityError, match="recorded"
        ):
            manager.ensure()

        assert destination.read_bytes() == wrong
        assert manager.status_path.read_bytes() == status_before


class TestZipVoiceStatusAtomicity:
    def test_status_uses_temporary_write_then_atomic_replace(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: digest status uses atomic final replacement."""

        item = _zip_item(payload_digest=_digest(b"unused"))
        manager, _destination = _zip_manager(tmp_path, item)
        operations = []
        original_replace = os.replace

        def recorded_replace(source, destination):
            operations.append((Path(source), Path(destination)))
            return original_replace(source, destination)

        monkeypatch.setattr(zipvoice_assets.os, "replace", recorded_replace)
        payload = {"engine": "zipvoice", "files": {"asset": {"ok": True}}}
        manager._write_status(payload)

        assert operations == [
            (manager.status_path.with_suffix(".tmp"), manager.status_path)
        ]
        assert json.loads(
            manager.status_path.read_text(encoding="utf-8")
        ) == payload
        assert not manager.status_path.with_suffix(".tmp").exists()

    def test_failed_status_replace_does_not_create_authoritative_final(
        self, tmp_path, monkeypatch
    ):
        """BEHAVIOR CONTRACT: a failed replace leaves no half-written final."""

        item = _zip_item(payload_digest=_digest(b"unused"))
        manager, _destination = _zip_manager(tmp_path, item)

        def fail_replace(_source, _destination):
            raise OSError("synthetic status replace failure")

        monkeypatch.setattr(zipvoice_assets.os, "replace", fail_replace)
        payload = {"engine": "zipvoice", "files": {"asset": {"ok": True}}}

        with pytest.raises(OSError, match="synthetic status replace failure"):
            manager._write_status(payload)

        assert not manager.status_path.exists()
        temp = manager.status_path.with_suffix(".tmp")
        assert json.loads(temp.read_text(encoding="utf-8")) == payload


class TestDestinationOwnership:
    def test_operator_controlled_ordinary_and_moss_targets_are_accepted(
        self, tmp_path, monkeypatch
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION: operator-controlled destinations."""

        ordinary = tmp_path / "non-default" / "kokoro"
        moss = tmp_path / "non-default" / "moss"
        tokenizer = tmp_path / "non-default" / "tokenizer"
        _make_ordinary_complete(ordinary)
        _make_moss_complete(moss, "browser_poc_manifest.json")
        _make_moss_complete(tokenizer, "codec_browser_onnx_meta.json")
        ordinary_cfg = _ordinary_config(ordinary)
        moss_cfg = SimpleNamespace(
            moss_model_dir=moss,
            moss_audio_tokenizer_model_dir=tokenizer,
            model_source="huggingface",
        )
        monkeypatch.setattr(
            model_sources,
            "_download_kokoro_assets",
            lambda *_args, **_kwargs: pytest.fail("ordinary download called"),
        )
        monkeypatch.setattr(
            model_sources,
            "_download_moss_model_assets",
            lambda *_args, **_kwargs: pytest.fail("MOSS download called"),
        )
        monkeypatch.setattr(
            model_sources,
            "_download_moss_audio_tokenizer_assets",
            lambda *_args, **_kwargs: pytest.fail("tokenizer download called"),
        )

        assert (
            model_sources.ensure_kokoro_model_dir(
                ordinary_cfg, logger=logging.getLogger("operator-kokoro")
            )
            == ordinary
        )
        assert (
            model_sources.ensure_moss_model_dir(
                moss_cfg, logger=logging.getLogger("operator-moss")
            )
            == moss
        )
        assert (
            model_sources.ensure_moss_audio_tokenizer_dir(
                moss_cfg, logger=logging.getLogger("operator-tokenizer")
            )
            == tokenizer
        )

    def test_zipvoice_destination_has_no_general_parent_sandbox(self):
        """STATIC OWNERSHIP CONTRACT, not an exploitability claim."""

        tree = ast.parse(inspect.getsource(zipvoice_assets.ZipVoiceAssetManager))
        destination = next(
            node
            for node in tree.body[0].body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_destination"
        )
        called_attributes = {
            node.func.attr
            for node in ast.walk(destination)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }

        assert called_attributes.isdisjoint({"resolve", "relative_to"})
        assert any(
            isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
            for node in ast.walk(destination)
        )

    def test_managed_identity_validation_is_not_a_general_root_sandbox(
        self,
    ):
        """STATIC OWNERSHIP CONTRACT: identity and root ownership are distinct."""

        normalize_source = inspect.getsource(
            kokoro_assets._normalized_asset_id
        )
        mode_source = inspect.getsource(kokoro_assets.is_managed_kokoro_mode)

        assert "path.is_absolute()" in normalize_source
        assert '".."' in normalize_source
        assert "is_managed_kokoro_directory" in mode_source
        assert "relative_to" in inspect.getsource(
            kokoro_assets.is_managed_kokoro_directory
        )


class TestAssetAtomicityAndWriterLockBoundary:
    @pytest.mark.parametrize("provider", ("huggingface", "modelscope"))
    def test_generic_snapshot_receives_final_destination_directly(
        self, tmp_path, monkeypatch, provider
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION: SDK owns snapshot atomicity."""

        target = tmp_path / provider / "final-destination"
        calls = []

        if provider == "huggingface":
            def downloader(**kwargs):
                calls.append(kwargs)
                return kwargs["local_dir"]

            _install_fake_huggingface(monkeypatch, downloader)
            result = model_sources._huggingface_snapshot_download(
                "synthetic/repository",
                target,
                logger=logging.getLogger("p2f-c-hf-destination"),
            )
            assert calls == [
                {
                    "repo_id": "synthetic/repository",
                    "local_dir": str(target),
                }
            ]
        else:
            def downloader(repo_id, **kwargs):
                calls.append((repo_id, kwargs))
                return kwargs["local_dir"]

            _install_fake_modelscope(monkeypatch, downloader)
            result = model_sources._modelscope_snapshot_download(
                "synthetic/repository",
                target,
                logger=logging.getLogger("p2f-c-ms-destination"),
            )
            assert calls == [
                (
                    "synthetic/repository",
                    {"local_dir": str(target)},
                )
            ]

        assert result == target

    def test_zipvoice_asset_copy_is_not_status_atomic_replace(
        self, tmp_path, monkeypatch
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION: asset writes lack final replace."""

        payload = b"synthetic copied asset"
        item = _zip_item(payload_digest=_digest(payload))
        manager, destination = _zip_manager(tmp_path, item)
        cache_file = tmp_path / "synthetic-sdk-cache" / "asset.bin"
        cache_file.parent.mkdir()
        cache_file.write_bytes(payload)
        copies = []
        original_copy = zipvoice_assets.shutil.copy2

        def recorded_copy(source, target):
            copies.append((Path(source), Path(target)))
            return original_copy(source, target)

        def downloader(**_kwargs):
            return str(cache_file)

        _install_fake_huggingface(monkeypatch, downloader)
        monkeypatch.setattr(zipvoice_assets.shutil, "copy2", recorded_copy)
        monkeypatch.setattr(manager, "_write_status", lambda _payload: None)

        assert manager.ensure()["ready"] is True
        assert copies == [(cache_file, destination)]
        assert destination.read_bytes() == payload

    def test_project_has_no_general_asset_staging_or_writer_lock(self):
        """STATIC OWNERSHIP CONTRACT: not a safety endorsement."""

        model_source = inspect.getsource(model_sources)
        managed_source = inspect.getsource(kokoro_assets)
        zipvoice_source = inspect.getsource(zipvoice_assets)
        combined = "\n".join((model_source, managed_source, zipvoice_source))

        assert "FileLock" not in combined
        assert "threading.Lock" not in combined
        assert "fcntl" not in combined
        assert "msvcrt" not in combined
        assert "TemporaryDirectory" not in model_source
        assert "os.replace" not in model_source
        assert "shutil.copy2" in inspect.getsource(
            zipvoice_assets.ZipVoiceAssetManager.ensure
        )
        assert "os.replace" not in inspect.getsource(
            zipvoice_assets.ZipVoiceAssetManager.ensure
        )
        assert "os.replace" in inspect.getsource(
            zipvoice_assets.ZipVoiceAssetManager._write_status
        )


class TestPartialArtifactLifecycle:
    def test_family_policy_matrix_is_not_interchangeable(self):
        """STATIC OWNERSHIP CONTRACT: each family keeps its current owner."""

        managed = inspect.getsource(
            kokoro_assets.verify_managed_kokoro_asset_file
        )
        ordinary = inspect.getsource(
            kokoro_assets.has_valid_kokoro_local_assets
        )
        moss_model = inspect.getsource(model_sources._has_real_moss_asset)
        moss_tokenizer = inspect.getsource(
            model_sources._has_real_moss_audio_tokenizer_asset
        )
        zipvoice = inspect.getsource(zipvoice_assets.ZipVoiceAssetManager.ensure)

        assert "hmac.compare_digest" in managed
        assert "is_valid_kokoro_model_file" in ordinary
        assert "_has_runtime_manifest" in moss_model
        assert "_has_tokenizer_meta" in moss_tokenizer
        assert "declared or recorded" in zipvoice
        assert "unlink(" not in managed
        assert "unlink(" not in zipvoice

    def test_absence_contracts_are_explicit_characterizations(self):
        """CURRENT-BEHAVIOR CHARACTERIZATION, NOT A SAFETY ENDORSEMENT."""

        source = Path(__file__).read_text(encoding="utf-8")
        assert "CURRENT-BEHAVIOR CHARACTERIZATION" in source
        assert "NOT A SAFETY ENDORSEMENT" in source
        assert "HEURISTIC COMPLETENESS, NOT CRYPTOGRAPHIC IDENTITY" in source
