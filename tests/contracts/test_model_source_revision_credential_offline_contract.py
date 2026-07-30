"""P2F-B contracts for revision, credential delegation, and offline ownership.

Characterization tests in this module describe current boundaries. They do not
claim that absent project controls are security guarantees or the final design.
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
import socket
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kokoro_tts import engine, kokoro_assets, model_sources
from kokoro_tts.config import TTSConfig
from kokoro_tts.config_env import BOOL_ENV, STR_ENV
from kokoro_tts.kokoro_assets import KokoroAssetIntegrityError
from kokoro_tts.model_source_metadata import MODEL_SOURCE_METADATA
from kokoro_tts.zipvoice import assets as zipvoice_assets


PACKAGE_ROOT = Path(model_sources.__file__).resolve().parent
SYNTHETIC_MARKER = "P2F_SYNTHETIC_CREDENTIAL_MARKER"
FORBIDDEN_PROJECT_ARGUMENTS = {
    "token",
    "use_auth_token",
    "endpoint",
    "base_url",
    "proxy",
    "proxies",
    "trust_env",
    "timeout",
    "retry",
    "retries",
    "resume",
    "resume_download",
    "user_agent",
}
HF_REPO = "hexgrad/Kokoro-82M-v1.1-zh"
HF_REVISION = "01e7505bd6a7a2ac4975463114c3a7650a9f7218"
MS_REPO = "AI-ModelScope/Kokoro-82M-v1.1-zh"
MS_REVISION = "75afdb60a7c1429b9dfc8014cc18330cf800bb80"
ZIPVOICE_REPO = "k2-fsa/ZipVoice"
ZIPVOICE_REVISION = "3baef9f2f52009cac656f4f8445b6e8f618a8235"
VOCOS_REPO = "charactr/vocos-mel-24khz"
VOCOS_REVISION = "a91e656a21df4e98ed0640ece71211deadd67933"

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _forbid_real_network(monkeypatch):
    """Fail immediately if a P2F-B contract drifts into real networking."""

    def fail_network(*_args, **_kwargs):
        pytest.fail("P2F-B contracts must not access the network")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(socket.socket, "connect", fail_network)


def _install_fake_huggingface_module(monkeypatch, **functions) -> None:
    module = types.ModuleType("huggingface_hub")
    for name, function in functions.items():
        setattr(module, name, function)
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)


def _install_fake_modelscope_module(monkeypatch, snapshot_download) -> None:
    root = types.ModuleType("modelscope")
    root.__path__ = []
    hub = types.ModuleType("modelscope.hub")
    hub.__path__ = []
    snapshot = types.ModuleType("modelscope.hub.snapshot_download")
    snapshot.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "modelscope", root)
    monkeypatch.setitem(sys.modules, "modelscope.hub", hub)
    monkeypatch.setitem(sys.modules, "modelscope.hub.snapshot_download", snapshot)


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _signature_names(callable_object) -> set[str]:
    return set(inspect.signature(callable_object).parameters)


def _recording_logger(name: str) -> tuple[logging.Logger, list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.Logger(name, level=logging.DEBUG)
    logger.propagate = False
    logger.addHandler(Handler())
    return logger, records


class TestManagedKokoroRevisionBoundary:
    def test_bundled_provider_identities_and_revisions_are_pinned(self):
        """BEHAVIOR CONTRACT for the managed manifest owner."""

        providers = kokoro_assets.managed_kokoro_manifest()["providers"]

        assert providers == {
            "huggingface": {"repo": HF_REPO, "revision": HF_REVISION},
            "modelscope": {"repo": MS_REPO, "revision": MS_REVISION},
        }
        assert all(
            len(item["revision"]) == 40
            and item["revision"] == item["revision"].lower()
            and set(item["revision"]) <= set("0123456789abcdef")
            for item in providers.values()
        )

    @pytest.mark.parametrize(
        ("preferred", "expected_repo", "expected_revision"),
        [
            ("huggingface", HF_REPO, HF_REVISION),
            ("modelscope", MS_REPO, MS_REVISION),
        ],
    )
    def test_managed_plan_carries_manifest_revision(
        self, preferred, expected_repo, expected_revision
    ):
        cfg = SimpleNamespace(
            model_source=preferred,
            model_source_effective="auto",
            kokoro_hf_repo=HF_REPO,
            kokoro_modelscope_repo=MS_REPO,
        )

        plan = model_sources._kokoro_download_plan(cfg, managed=True)

        assert plan[0] == (preferred, expected_repo, expected_revision)
        assert {provider: revision for provider, _repo, revision in plan} == {
            "huggingface": HF_REVISION,
            "modelscope": MS_REVISION,
        }

    @pytest.mark.parametrize(
        ("preferred", "expected_repo", "expected_revision"),
        [
            ("huggingface", HF_REPO, HF_REVISION),
            ("modelscope", MS_REPO, MS_REVISION),
        ],
    )
    def test_managed_loop_forwards_revision_to_selected_executor(
        self, preferred, expected_repo, expected_revision, monkeypatch, tmp_path
    ):
        calls: list[tuple[str, str, Path, dict[str, object]]] = []
        cfg = SimpleNamespace(
            model_source=preferred,
            model_source_effective="auto",
            kokoro_hf_repo=HF_REPO,
            kokoro_modelscope_repo=MS_REPO,
        )
        target = tmp_path / "managed"

        def record(provider):
            def download(repo, destination, **kwargs):
                calls.append((provider, repo, destination, kwargs))
                return target

            return download

        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            record("huggingface"),
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            record("modelscope"),
        )
        monkeypatch.setattr(
            model_sources,
            "verify_managed_kokoro_present_core_assets",
            lambda _target: None,
        )
        monkeypatch.setattr(
            model_sources,
            "verify_managed_kokoro_present_voices",
            lambda _target: None,
        )
        monkeypatch.setattr(
            model_sources,
            "_verify_managed_provider_candidates",
            lambda _candidates: None,
        )
        monkeypatch.setattr(
            model_sources, "is_managed_kokoro_mode", lambda *_args: True
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_kokoro_local_assets",
            lambda *_args, **_kwargs: True,
        )

        assert model_sources._download_kokoro_assets(
            cfg, target, logger=Mock(), managed=True
        ) == target
        assert calls[0][0:3] == (preferred, expected_repo, target)
        assert calls[0][3]["revision"] == expected_revision

    def test_operator_repo_cannot_substitute_managed_identity(self):
        """STATIC OWNERSHIP CONTRACT for exact manifest identity matching."""

        assert (
            kokoro_assets.managed_kokoro_provider_revision(
                "huggingface", "operator/custom-kokoro"
            )
            is None
        )
        assert (
            kokoro_assets.managed_kokoro_provider_revision(
                "modelscope", "operator/custom-kokoro"
            )
            is None
        )


class TestOrdinaryKokoroRevisionBoundary:
    def test_ordinary_plan_is_unpinned_current_behavior_characterization(self):
        """CURRENT-BEHAVIOR CHARACTERIZATION, not reproducibility."""

        cfg = SimpleNamespace(
            model_source="huggingface",
            model_source_effective="auto",
            kokoro_hf_repo="operator/hf-kokoro",
            kokoro_modelscope_repo="operator/ms-kokoro",
        )

        assert model_sources._kokoro_download_plan(cfg, managed=False) == [
            ("huggingface", "operator/hf-kokoro", None),
            ("modelscope", "operator/ms-kokoro", None),
        ]

    def test_ordinary_executors_receive_no_revision_characterization(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION for stable target/unpinned repos."""

        calls: list[tuple[str, str, Path, dict[str, object]]] = []
        target = tmp_path / "ordinary-stable-target"
        cfg = SimpleNamespace(
            model_source="huggingface",
            model_source_effective="auto",
            kokoro_hf_repo="operator/hf-kokoro",
            kokoro_modelscope_repo="operator/ms-kokoro",
        )

        def record(provider):
            def download(repo, destination, **kwargs):
                calls.append((provider, repo, destination, kwargs))
                return None

            return download

        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            record("huggingface"),
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            record("modelscope"),
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_kokoro_local_assets",
            lambda *_args, **_kwargs: False,
        )

        assert (
            model_sources._download_kokoro_assets(
                cfg, target, logger=Mock(), managed=False
            )
            is None
        )
        assert [(provider, repo) for provider, repo, _target, _kwargs in calls] == [
            ("huggingface", "operator/hf-kokoro"),
            ("modelscope", "operator/ms-kokoro"),
        ]
        assert all(destination == target for _, _, destination, _ in calls)
        assert all("revision" not in kwargs for _, _, _, kwargs in calls)


class TestMossRevisionBoundary:
    def test_model_plan_and_executor_are_unpinned_characterization(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION for the MOSS model owner."""

        calls: list[tuple[str, str, Path, dict[str, object]]] = []
        target = tmp_path / "moss-model-stable-target"
        cfg = SimpleNamespace(
            model_source="modelscope",
            model_source_effective="auto",
            moss_modelscope_repo="operator/ms-model",
            moss_hf_repo="operator/hf-model",
        )

        def record(provider):
            def download(repo, destination, **kwargs):
                calls.append((provider, repo, destination, kwargs))
                return None

            return download

        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            record("modelscope"),
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            record("huggingface"),
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_model_assets",
            lambda *_args, **_kwargs: False,
        )

        assert model_sources._moss_download_plan(cfg) == [
            ("modelscope", "operator/ms-model"),
            ("huggingface", "operator/hf-model"),
        ]
        assert (
            model_sources._download_moss_model_assets(
                cfg, target, logger=Mock()
            )
            is None
        )
        assert [(provider, repo) for provider, repo, _target, _kwargs in calls] == [
            ("modelscope", "operator/ms-model"),
            ("huggingface", "operator/hf-model"),
        ]
        assert all(destination == target for _, _, destination, _ in calls)
        assert all("revision" not in kwargs for _, _, _, kwargs in calls)

    def test_tokenizer_plan_and_executor_are_separate_unpinned_characterization(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION for the tokenizer owner."""

        calls: list[tuple[str, str, Path, dict[str, object]]] = []
        target = tmp_path / "moss-tokenizer-stable-target"
        cfg = SimpleNamespace(
            model_source="huggingface",
            model_source_effective="auto",
            moss_modelscope_repo="operator/ms-model-do-not-use",
            moss_hf_repo="operator/hf-model-do-not-use",
            moss_audio_tokenizer_modelscope_repo="operator/ms-tokenizer",
            moss_audio_tokenizer_hf_repo="operator/hf-tokenizer",
        )

        def record(provider):
            def download(repo, destination, **kwargs):
                calls.append((provider, repo, destination, kwargs))
                return None

            return download

        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            record("huggingface"),
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            record("modelscope"),
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_audio_tokenizer_assets",
            lambda *_args, **_kwargs: False,
        )

        assert model_sources._moss_audio_tokenizer_download_plan(cfg) == [
            ("huggingface", "operator/hf-tokenizer"),
            ("modelscope", "operator/ms-tokenizer"),
        ]
        assert (
            model_sources._download_moss_audio_tokenizer_assets(
                cfg, target, logger=Mock()
            )
            is None
        )
        assert [(provider, repo) for provider, repo, _target, _kwargs in calls] == [
            ("huggingface", "operator/hf-tokenizer"),
            ("modelscope", "operator/ms-tokenizer"),
        ]
        assert all(destination == target for _, _, destination, _ in calls)
        assert all("revision" not in kwargs for _, _, _, kwargs in calls)
        assert not any("model-do-not-use" in repo for _, repo, _, _ in calls)


class TestZipVoiceRevisionBoundary:
    def test_cpu_and_cuda_manifests_pin_bundled_provider_identities(self):
        """BEHAVIOR CONTRACT for bundled-data revision identity."""

        root = PACKAGE_ROOT / "zipvoice"
        for filename, expected_counts in (
            ("assets_manifest.json", {ZIPVOICE_REPO: 4, VOCOS_REPO: 2}),
            ("assets_manifest_cuda.json", {ZIPVOICE_REPO: 5, VOCOS_REPO: 2}),
        ):
            assets = _manifest(root / filename)["assets"]
            assert {
                item["repo"]: item["revision"] for item in assets
            } == {
                ZIPVOICE_REPO: ZIPVOICE_REVISION,
                VOCOS_REPO: VOCOS_REVISION,
            }
            assert {
                repo: sum(item["repo"] == repo for item in assets)
                for repo in expected_counts
            } == expected_counts

    def test_download_asset_forwards_bundled_identity_without_transport_kwargs(
        self, tmp_path
    ):
        calls: list[dict[str, object]] = []
        item = {
            "repo": ZIPVOICE_REPO,
            "filename": "zipvoice_distill/model.json",
            "revision": ZIPVOICE_REVISION,
        }

        def downloader(**kwargs):
            calls.append(kwargs)
            return str(tmp_path / kwargs["filename"])

        result = zipvoice_assets.ZipVoiceAssetManager._download_asset(
            downloader, item, tmp_path, force_download=False
        )

        assert result == tmp_path / "zipvoice_distill/model.json"
        assert calls == [
            {
                "repo_id": ZIPVOICE_REPO,
                "filename": "zipvoice_distill/model.json",
                "revision": ZIPVOICE_REVISION,
                "local_dir": str(tmp_path),
            }
        ]
        assert not FORBIDDEN_PROJECT_ARGUMENTS & set(calls[0])

    def test_zipvoice_has_no_generic_provider_fallback_owner(self):
        """STATIC OWNERSHIP CONTRACT, not runtime manifest validation."""

        source = (PACKAGE_ROOT / "zipvoice" / "assets.py").read_text(
            encoding="utf-8"
        )

        assert "_generic_download_plan" not in source
        assert "_huggingface_snapshot_download" not in source
        assert "_modelscope_snapshot_download" not in source
        assert "hf_hub_download" in source


class TestCredentialAndTransportDelegation:
    def test_wrapper_signatures_do_not_expose_credential_or_transport_controls(self):
        """STATIC OWNERSHIP CONTRACT: SDK defaults remain delegated."""

        for callable_object in (
            model_sources._huggingface_snapshot_download,
            model_sources._modelscope_snapshot_download,
            zipvoice_assets.ZipVoiceAssetManager._download_asset,
        ):
            assert not FORBIDDEN_PROJECT_ARGUMENTS & _signature_names(
                callable_object
            )

    def test_generic_success_calls_do_not_forward_delegated_kwargs(
        self, monkeypatch, tmp_path
    ):
        """PROJECT EXPLICIT FORWARDING is absent; SDK discovery is uncontracted."""

        hf_calls: list[dict[str, object]] = []
        ms_calls: list[tuple[str, dict[str, object]]] = []

        def hf_snapshot(**kwargs):
            hf_calls.append(kwargs)
            return kwargs["local_dir"]

        def ms_snapshot(repo_id, **kwargs):
            ms_calls.append((repo_id, kwargs))
            return kwargs["local_dir"]

        _install_fake_huggingface_module(
            monkeypatch, snapshot_download=hf_snapshot
        )
        _install_fake_modelscope_module(monkeypatch, ms_snapshot)

        assert model_sources._huggingface_snapshot_download(
            "operator/hf", tmp_path / "hf", logger=Mock()
        ) == tmp_path / "hf"
        assert model_sources._modelscope_snapshot_download(
            "operator/ms", tmp_path / "ms", logger=Mock()
        ) == tmp_path / "ms"
        assert not FORBIDDEN_PROJECT_ARGUMENTS & set(hf_calls[0])
        assert not FORBIDDEN_PROJECT_ARGUMENTS & set(ms_calls[0][1])

    def test_downloader_ast_does_not_claim_p2e_probe_transport_controls(self):
        """STATIC OWNERSHIP CONTRACT for the SDK-delegated transport seam."""

        source = (PACKAGE_ROOT / "model_sources.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        for name in (
            "_huggingface_snapshot_download",
            "_modelscope_snapshot_download",
        ):
            function = functions[name]
            keywords = {
                keyword.arg
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                for keyword in node.keywords
                if keyword.arg is not None
            }
            assert not FORBIDDEN_PROJECT_ARGUMENTS & keywords
            assert "_probe_url" not in {
                node.func.id
                for node in ast.walk(function)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }


class TestSyntheticCredentialLoggingBoundary:
    def test_hf_traceback_can_retain_synthetic_marker_characterization(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION and P2F security candidate input."""

        def snapshot_download(**_kwargs):
            raise RuntimeError(SYNTHETIC_MARKER)

        _install_fake_huggingface_module(
            monkeypatch, snapshot_download=snapshot_download
        )
        logger, records = _recording_logger("p2f-b-hf")

        assert model_sources._huggingface_snapshot_download(
            "operator/hf", tmp_path / "hf", logger=logger
        ) is None
        warning = records[-1]
        formatted = logging.Formatter("%(message)s").format(warning)

        assert warning.exc_info is not None
        assert SYNTHETIC_MARKER not in str(warning.msg)
        assert SYNTHETIC_MARKER not in " ".join(
            str(value) for value in warning.args
        )
        assert SYNTHETIC_MARKER in formatted

    def test_modelscope_propagates_same_synthetic_exception_without_redaction(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION: no project redaction seam."""

        error = RuntimeError(SYNTHETIC_MARKER)

        def snapshot_download(_repo_id, **_kwargs):
            raise error

        _install_fake_modelscope_module(monkeypatch, snapshot_download)

        with pytest.raises(RuntimeError) as raised:
            model_sources._modelscope_snapshot_download(
                "operator/ms", tmp_path / "ms", logger=Mock()
            )

        assert raised.value is error
        assert SYNTHETIC_MARKER in str(raised.value)


class TestGenericOfflineExecutorBoundary:
    def test_all_generic_provider_plans_are_empty_in_explicit_offline_mode(self):
        """BEHAVIOR CONTRACT for generic offline plan ownership."""

        cfg = SimpleNamespace(
            model_source="offline",
            model_source_effective="auto",
            kokoro_hf_repo=HF_REPO,
            kokoro_modelscope_repo=MS_REPO,
            moss_hf_repo="operator/hf-model",
            moss_modelscope_repo="operator/ms-model",
            moss_audio_tokenizer_hf_repo="operator/hf-tokenizer",
            moss_audio_tokenizer_modelscope_repo="operator/ms-tokenizer",
        )

        assert model_sources._kokoro_download_plan(cfg, managed=True) == []
        assert model_sources._kokoro_download_plan(cfg, managed=False) == []
        assert model_sources._moss_download_plan(cfg) == []
        assert model_sources._moss_audio_tokenizer_download_plan(cfg) == []

    def test_managed_offline_runs_local_integrity_owner_without_executor(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR CONTRACT: network suppressed and managed state fails closed."""

        target = tmp_path / "managed-missing"
        cfg = SimpleNamespace(
            model_source="offline",
            model_source_effective="auto",
            model_dir=target,
            kokoro_prefetch_voices=True,
        )
        integrity_calls: list[str] = []
        monkeypatch.setattr(
            model_sources,
            "has_valid_kokoro_local_assets",
            lambda *_args, **_kwargs: False,
        )
        monkeypatch.setattr(
            model_sources, "is_managed_kokoro_mode", lambda *_args: True
        )
        monkeypatch.setattr(
            model_sources, "default_kokoro_model_dir", lambda: target
        )
        monkeypatch.setattr(
            model_sources,
            "verify_managed_kokoro_present_core_assets",
            lambda _target: integrity_calls.append("core"),
        )
        monkeypatch.setattr(
            model_sources,
            "verify_managed_kokoro_present_voices",
            lambda _target: integrity_calls.append("voices"),
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail("HF executor called offline"),
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail(
                "ModelScope executor called offline"
            ),
        )

        with pytest.raises(KokoroAssetIntegrityError):
            model_sources.ensure_kokoro_model_dir(cfg, logger=Mock())

        assert integrity_calls

    def test_ordinary_offline_incomplete_assets_return_none_without_executor(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR CONTRACT for ordinary project preparation."""

        current = tmp_path / "ordinary"
        default = tmp_path / "default"
        cfg = SimpleNamespace(
            model_source="offline",
            model_source_effective="auto",
            model_dir=current,
            kokoro_prefetch_voices=True,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_kokoro_local_assets",
            lambda *_args, **_kwargs: False,
        )
        monkeypatch.setattr(
            model_sources, "is_managed_kokoro_mode", lambda *_args: False
        )
        monkeypatch.setattr(
            model_sources, "default_kokoro_model_dir", lambda: default
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail("HF executor called offline"),
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail(
                "ModelScope executor called offline"
            ),
        )

        assert model_sources.ensure_kokoro_model_dir(
            cfg, logger=Mock()
        ) is None
        assert cfg.model_dir == current


class TestOrdinaryKokoroOfflineGuard:
    def test_repo_only_kmodel_is_not_called_in_explicit_offline_mode(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR CONTRACT for the project guard before upstream KModel."""

        kmodel_calls: list[dict[str, object]] = []
        fake_torch = types.ModuleType("torch")
        fake_kokoro = types.ModuleType("kokoro")

        def kmodel(**kwargs):
            kmodel_calls.append(kwargs)
            return object()

        fake_kokoro.KModel = kmodel
        fake_kokoro.KPipeline = object
        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)
        cfg = SimpleNamespace(
            model_source="offline",
            model_source_effective="auto",
            model_dir=tmp_path / "missing",
            model_file=tmp_path / "missing" / "model.pth",
            kokoro_hf_repo="operator/hf-kokoro",
            resolve_device=lambda: "cpu",
        )
        instance = engine.TTSEngine(cfg)
        monkeypatch.setattr(
            instance,
            "_prepare_kokoro_load",
            lambda: (
                cfg.model_file,
                cfg.model_dir / "config.json",
                False,
            ),
        )

        with pytest.raises(RuntimeError, match="offline"):
            instance.load()

        assert kmodel_calls == []

    def test_upstream_kmodel_has_no_local_files_only_characterization(self):
        """CURRENT-BEHAVIOR CHARACTERIZATION; upstream networking is not claimed."""

        source = (PACKAGE_ROOT / "engine.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        tts_engine = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "TTSEngine"
        )
        load = next(
            node
            for node in tts_engine.body
            if isinstance(node, ast.FunctionDef) and node.name == "load"
        )
        kmodel_calls = [
            node
            for node in ast.walk(load)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "KModel"
        ]

        assert kmodel_calls
        assert all(
            "local_files_only"
            not in {keyword.arg for keyword in call.keywords}
            for call in kmodel_calls
        )


class TestMossOfflineBoundary:
    def test_model_offline_suppresses_executor_and_returns_unverified_target(
        self, monkeypatch, tmp_path
    ):
        """Network suppression is enforced; completeness is not implied."""

        target = tmp_path / "moss-model"
        cfg = SimpleNamespace(model_source="offline", moss_model_dir=target)
        checks: list[Path] = []

        def unresolved(candidate, **_kwargs):
            checks.append(candidate)
            return None

        monkeypatch.setattr(
            model_sources, "resolve_valid_moss_model_dir", unresolved
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail("HF executor called offline"),
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail(
                "ModelScope executor called offline"
            ),
        )

        assert model_sources.ensure_moss_model_dir(cfg, logger=Mock()) == target
        assert cfg.moss_model_dir == target
        assert checks == [target]

    def test_tokenizer_offline_suppresses_executor_and_keeps_independent_target(
        self, monkeypatch, tmp_path
    ):
        """Network suppression is enforced; completeness is not implied."""

        model_target = tmp_path / "moss-model"
        tokenizer_target = tmp_path / "moss-tokenizer"
        cfg = SimpleNamespace(
            model_source="offline",
            moss_model_dir=model_target,
            moss_audio_tokenizer_model_dir=tokenizer_target,
        )
        checks: list[Path] = []

        def unresolved(candidate, **_kwargs):
            checks.append(candidate)
            return None

        monkeypatch.setattr(
            model_sources,
            "resolve_valid_moss_audio_tokenizer_dir",
            unresolved,
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail("HF executor called offline"),
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail(
                "ModelScope executor called offline"
            ),
        )

        assert model_sources.ensure_moss_audio_tokenizer_dir(
            cfg, logger=Mock()
        ) == tokenizer_target
        assert cfg.moss_audio_tokenizer_model_dir == tokenizer_target
        assert cfg.moss_model_dir == model_target
        assert checks == [tokenizer_target]


class TestZipVoiceIndependentDownloadControl:
    @staticmethod
    def _single_bundled_asset_manifest(tmp_path: Path) -> tuple[Path, dict]:
        bundled = _manifest(PACKAGE_ROOT / "zipvoice" / "assets_manifest.json")
        item = dict(bundled["assets"][0])
        path = tmp_path / "zipvoice-single-asset.json"
        path.write_bytes(
            json.dumps(
                {"schema_version": bundled.get("schema_version", 1), "assets": [item]}
            ).encode("utf-8")
        )
        return path, item

    def test_model_source_offline_does_not_own_zipvoice_download(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION of independent family policy."""

        manifest_path, item = self._single_bundled_asset_manifest(tmp_path)
        calls: list[dict[str, object]] = []

        def hf_hub_download(**kwargs):
            calls.append(kwargs)
            output = Path(kwargs["local_dir"]) / kwargs["filename"]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"synthetic-zipvoice-asset")
            return str(output)

        _install_fake_huggingface_module(
            monkeypatch, hf_hub_download=hf_hub_download
        )
        monkeypatch.setattr(
            zipvoice_assets, "file_sha256", lambda _path: item["sha256"]
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail(
                "generic HF wrapper must not own ZipVoice"
            ),
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail(
                "generic ModelScope wrapper must not own ZipVoice"
            ),
        )
        root = tmp_path / "zipvoice"
        cfg = SimpleNamespace(
            model_source="offline",
            zipvoice_download_enabled=True,
            zipvoice_model_root=root,
            zipvoice_distill_dir=root / "zipvoice_distill",
            zipvoice_vocos_dir=root / "vocos",
        )

        result = zipvoice_assets.ZipVoiceAssetManager(
            cfg, manifest_path=manifest_path
        ).ensure()

        assert result["ready"] is True
        assert calls == [
            {
                "repo_id": item["repo"],
                "filename": item["filename"],
                "revision": item["revision"],
                "local_dir": str(root),
            }
        ]

    def test_download_disabled_avoids_sdk_import_and_generic_fallback(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR CONTRACT for ZipVoice's independent local-only control."""

        manifest_path, _item = self._single_bundled_asset_manifest(tmp_path)
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail("generic HF fallback called"),
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail(
                "generic ModelScope fallback called"
            ),
        )
        root = tmp_path / "zipvoice-disabled"
        cfg = SimpleNamespace(
            model_source="huggingface",
            zipvoice_download_enabled=False,
            zipvoice_model_root=root,
            zipvoice_distill_dir=root / "zipvoice_distill",
            zipvoice_vocos_dir=root / "vocos",
        )

        with pytest.raises(FileNotFoundError):
            zipvoice_assets.ZipVoiceAssetManager(
                cfg, manifest_path=manifest_path
            ).ensure()

    def test_no_project_level_global_offline_owner_is_claimed(self):
        """STATIC OWNERSHIP CONTRACT for separate configuration fields."""

        assert MODEL_SOURCE_METADATA.excluded_engine_scope == "zipvoice"
        assert "model_source" in TTSConfig.__dataclass_fields__
        assert "zipvoice_download_enabled" in TTSConfig.__dataclass_fields__
        assert STR_ENV["ANGEVOICE_MODEL_SOURCE"] == "model_source"
        assert (
            BOOL_ENV["ZIPVOICE_DOWNLOAD_ENABLED"]
            == "zipvoice_download_enabled"
        )
        assert (
            TTSConfig.__dataclass_fields__["model_source"].default
            != TTSConfig.__dataclass_fields__[
                "zipvoice_download_enabled"
            ].default
        )
