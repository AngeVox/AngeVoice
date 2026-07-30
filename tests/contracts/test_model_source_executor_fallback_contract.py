"""P2F-A contracts for provider executors and execution-level fallback."""

from __future__ import annotations

import ast
import inspect
import logging
import socket
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kokoro_tts import model_sources
from kokoro_tts.kokoro_assets import KokoroAssetIntegrityError
from kokoro_tts.model_source_metadata import MODEL_SOURCE_METADATA


PACKAGE_ROOT = Path(model_sources.__file__).resolve().parent
SYNTHETIC_MARKER = "P2F_GENERIC_PROVIDER_SYNTHETIC_SECRET_MARKER"
pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _forbid_real_network(monkeypatch):
    """Keep every P2F-A contract hermetic even if a future path drifts."""

    def fail_network(*_args, **_kwargs):
        pytest.fail("P2F-A contracts must not access the network")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(socket.socket, "connect", fail_network)


def _install_fake_huggingface_module(monkeypatch, snapshot_download) -> None:
    module = types.ModuleType("huggingface_hub")
    module.snapshot_download = snapshot_download
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


def _same_path(left: Path, right: Path) -> bool:
    return Path(left).resolve(strict=False) == Path(right).resolve(strict=False)


def _assert_safe_fallback_warning(log: Mock, *, repo: str) -> None:
    log.warning.assert_called_once()
    warning = log.warning.call_args
    rendered = warning.args[0] % warning.args[1:]
    assert "modelscope" in rendered
    assert repo in rendered
    assert "RuntimeError" in rendered
    assert "continuing fallback" in rendered
    assert SYNTHETIC_MARKER not in rendered
    assert "Traceback" not in rendered
    assert warning.kwargs.get("exc_info") in (None, False)


class TestHuggingFaceSnapshotExecutor:
    """Direct behavior contracts for the canonical Hugging Face owner."""

    def test_import_unavailable_returns_none_without_propagating(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)

        result = model_sources._huggingface_snapshot_download(
            "owner/model", tmp_path / "target", logger=Mock()
        )

        assert result is None

    def test_success_forwards_project_owned_optional_arguments(
        self, monkeypatch, tmp_path
    ):
        calls: list[dict[str, object]] = []
        downloaded = tmp_path / "downloaded"

        def snapshot_download(**kwargs):
            calls.append(kwargs)
            return str(downloaded)

        _install_fake_huggingface_module(monkeypatch, snapshot_download)
        target = tmp_path / "target"

        result = model_sources._huggingface_snapshot_download(
            "owner/model",
            target,
            logger=Mock(),
            allow_patterns=("config.json", "voices/*.pt"),
            revision="a" * 40,
        )

        assert result == downloaded
        assert calls == [
            {
                "repo_id": "owner/model",
                "local_dir": str(target),
                "allow_patterns": ["config.json", "voices/*.pt"],
                "revision": "a" * 40,
            }
        ]

    def test_success_does_not_invent_optional_sdk_arguments(
        self, monkeypatch, tmp_path
    ):
        calls: list[dict[str, object]] = []

        def snapshot_download(**kwargs):
            calls.append(kwargs)
            return kwargs["local_dir"]

        _install_fake_huggingface_module(monkeypatch, snapshot_download)
        target = tmp_path / "target"

        assert model_sources._huggingface_snapshot_download(
            "owner/model", target, logger=Mock()
        ) == target
        assert calls == [{"repo_id": "owner/model", "local_dir": str(target)}]

    def test_runtime_exception_is_converted_to_none_current_behavior_characterization(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION, not a design endorsement."""

        marker = "P2F_SYNTHETIC_SECRET_MARKER"
        error = RuntimeError(marker)
        sdk_calls: list[dict[str, object]] = []

        def snapshot_download(**kwargs):
            sdk_calls.append(kwargs)
            raise error

        _install_fake_huggingface_module(monkeypatch, snapshot_download)
        logger = Mock()

        result = model_sources._huggingface_snapshot_download(
            "owner/model", tmp_path / "target", logger=logger
        )

        assert result is None
        assert sdk_calls == [
            {
                "repo_id": "owner/model",
                "local_dir": str(tmp_path / "target"),
            }
        ]
        warning_args, warning_kwargs = logger.warning.call_args
        assert marker not in " ".join(str(value) for value in warning_args)
        assert warning_kwargs == {"exc_info": True}


class TestModelScopeSnapshotExecutor:
    """Direct behavior contracts for the canonical ModelScope owner."""

    def test_import_unavailable_returns_none_without_propagating(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setitem(sys.modules, "modelscope", None)
        monkeypatch.setitem(sys.modules, "modelscope.hub", None)
        monkeypatch.setitem(sys.modules, "modelscope.hub.snapshot_download", None)

        result = model_sources._modelscope_snapshot_download(
            "owner/model", tmp_path / "target", logger=Mock()
        )

        assert result is None

    def test_success_forwards_only_project_owned_arguments(
        self, monkeypatch, tmp_path
    ):
        calls: list[tuple[str, dict[str, object]]] = []
        downloaded = tmp_path / "downloaded"

        def snapshot_download(repo_id, **kwargs):
            calls.append((repo_id, kwargs))
            return str(downloaded)

        _install_fake_modelscope_module(monkeypatch, snapshot_download)
        target = tmp_path / "target"

        result = model_sources._modelscope_snapshot_download(
            "owner/model",
            target,
            logger=Mock(),
            revision="b" * 40,
        )

        assert result == downloaded
        assert calls == [
            (
                "owner/model",
                {"local_dir": str(target), "revision": "b" * 40},
            )
        ]
        assert not {
            "token",
            "endpoint",
            "proxy",
            "timeout",
            "retry",
        } & set(calls[0][1])

    def test_runtime_exception_propagates_current_behavior_characterization(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION, not a security guarantee."""

        error = RuntimeError("synthetic ModelScope runtime failure")

        def snapshot_download(_repo_id, **_kwargs):
            raise error

        _install_fake_modelscope_module(monkeypatch, snapshot_download)

        with pytest.raises(RuntimeError) as raised:
            model_sources._modelscope_snapshot_download(
                "owner/model", tmp_path / "target", logger=Mock()
            )

        assert raised.value is error

    def test_allow_pattern_parameter_surface_remains_provider_specific(self):
        """STATIC OWNERSHIP CONTRACT for the current wrapper signatures."""

        hf_parameters = inspect.signature(
            model_sources._huggingface_snapshot_download
        ).parameters
        modelscope_parameters = inspect.signature(
            model_sources._modelscope_snapshot_download
        ).parameters

        assert "allow_patterns" in hf_parameters
        assert "allow_patterns" not in modelscope_parameters


class TestOrdinaryKokoroFallback:
    """Execution-level contracts for ordinary/custom Kokoro."""

    def test_clean_failure_permits_ordered_fallback(self, monkeypatch, tmp_path):
        calls: list[str] = []
        target = tmp_path / "target"
        fallback = tmp_path / "fallback"
        monkeypatch.setattr(
            model_sources,
            "_kokoro_download_plan",
            lambda *_args, **_kwargs: [
                ("modelscope", "ms/repo", None),
                ("huggingface", "hf/repo", None),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope") or None,
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or fallback,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_kokoro_local_assets",
            lambda candidate, **_kwargs: _same_path(candidate, fallback),
        )

        result = model_sources._download_kokoro_assets(
            SimpleNamespace(), target, logger=Mock(), managed=False
        )

        assert result == fallback
        assert calls == ["modelscope", "huggingface"]

    def test_hf_sdk_exception_becomes_none_and_reaches_modelscope(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION across wrapper and family loop."""

        calls: list[str] = []
        error = RuntimeError("synthetic HF runtime failure")

        def hf_snapshot_download(**_kwargs):
            calls.append("huggingface")
            raise error

        _install_fake_huggingface_module(monkeypatch, hf_snapshot_download)
        fallback = tmp_path / "modelscope-result"
        monkeypatch.setattr(
            model_sources,
            "_kokoro_download_plan",
            lambda *_args, **_kwargs: [
                ("huggingface", "hf/repo", None),
                ("modelscope", "ms/repo", None),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope") or fallback,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_kokoro_local_assets",
            lambda candidate, **_kwargs: _same_path(candidate, fallback),
        )

        result = model_sources._download_kokoro_assets(
            SimpleNamespace(), tmp_path / "target", logger=Mock(), managed=False
        )

        assert result == fallback
        assert calls == ["huggingface", "modelscope"]

    def test_modelscope_sdk_exception_logs_safely_and_reaches_hf_fallback(
        self, monkeypatch, tmp_path
    ):
        calls: list[str] = []
        error = RuntimeError(SYNTHETIC_MARKER)
        fallback = tmp_path / "hf-result"
        log = Mock()

        def modelscope_snapshot_download(_repo_id, **_kwargs):
            calls.append("modelscope")
            raise error

        _install_fake_modelscope_module(monkeypatch, modelscope_snapshot_download)
        monkeypatch.setattr(
            model_sources,
            "_kokoro_download_plan",
            lambda *_args, **_kwargs: [
                ("modelscope", "ms/repo", None),
                ("huggingface", "hf/repo", None),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or fallback,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_kokoro_local_assets",
            lambda candidate, **_kwargs: _same_path(candidate, fallback),
        )

        result = model_sources._download_kokoro_assets(
            SimpleNamespace(),
            tmp_path / "target",
            logger=log,
            managed=False,
        )

        assert result == fallback
        assert calls == ["modelscope", "huggingface"]
        _assert_safe_fallback_warning(log, repo="ms/repo")

    @pytest.mark.parametrize(
        "error",
        [KeyboardInterrupt(), SystemExit(7), GeneratorExit()],
        ids=["keyboard-interrupt", "system-exit", "generator-exit"],
    )
    def test_modelscope_baseexception_propagates_without_fallback(
        self, error, monkeypatch, tmp_path
    ):
        calls: list[str] = []
        log = Mock()
        monkeypatch.setattr(
            model_sources,
            "_kokoro_download_plan",
            lambda *_args, **_kwargs: [
                ("modelscope", "ms/repo", None),
                ("huggingface", "hf/repo", None),
            ],
        )

        def fail_modelscope(*_args, **_kwargs):
            calls.append("modelscope")
            raise error

        monkeypatch.setattr(
            model_sources, "_modelscope_snapshot_download", fail_modelscope
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface")
            or pytest.fail("BaseException must not reach fallback"),
        )

        with pytest.raises(type(error)) as raised:
            model_sources._download_kokoro_assets(
                SimpleNamespace(),
                tmp_path / "target",
                logger=log,
                managed=False,
            )

        assert raised.value is error
        assert calls == ["modelscope"]
        log.warning.assert_not_called()

    def test_non_modelscope_exception_is_not_normalized(
        self, monkeypatch, tmp_path
    ):
        calls: list[str] = []
        error = RuntimeError(SYNTHETIC_MARKER)
        log = Mock()
        monkeypatch.setattr(
            model_sources,
            "_kokoro_download_plan",
            lambda *_args, **_kwargs: [
                ("huggingface", "hf/repo", None),
                ("modelscope", "ms/repo", None),
            ],
        )

        def fail_huggingface(*_args, **_kwargs):
            calls.append("huggingface")
            raise error

        monkeypatch.setattr(
            model_sources, "_huggingface_snapshot_download", fail_huggingface
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope")
            or pytest.fail("non-ModelScope exception must not reach fallback"),
        )

        with pytest.raises(RuntimeError) as raised:
            model_sources._download_kokoro_assets(
                SimpleNamespace(),
                tmp_path / "target",
                logger=log,
                managed=False,
            )

        assert raised.value is error
        assert calls == ["huggingface"]
        log.warning.assert_not_called()

    def test_success_stops_loop_and_resolves_plan_once(self, monkeypatch, tmp_path):
        calls: list[str] = []
        resolver_calls: list[object] = []
        result_path = tmp_path / "hf-result"
        cfg = SimpleNamespace(
            kokoro_hf_repo="hf/repo",
            kokoro_modelscope_repo="ms/repo",
        )

        def resolve(config):
            resolver_calls.append(config)
            return "huggingface"

        monkeypatch.setattr(model_sources, "resolve_model_source", resolve)
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or result_path,
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope")
            or pytest.fail("fallback must not run"),
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_kokoro_local_assets",
            lambda candidate, **_kwargs: _same_path(candidate, result_path),
        )

        assert model_sources._download_kokoro_assets(
            cfg, tmp_path / "target", logger=Mock(), managed=False
        ) == result_path
        assert calls == ["huggingface"]
        assert resolver_calls == [cfg]


class TestMossModelFallback:
    """Execution-level contracts for the independent MOSS model family."""

    def test_clean_failure_permits_ordered_fallback(self, monkeypatch, tmp_path):
        calls: list[str] = []
        fallback = tmp_path / "fallback"
        monkeypatch.setattr(
            model_sources,
            "_moss_download_plan",
            lambda _cfg: [
                ("modelscope", "ms/model"),
                ("huggingface", "hf/model"),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope") or None,
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or fallback,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_model_assets",
            lambda candidate, **_kwargs: _same_path(candidate, fallback),
        )

        assert model_sources._download_moss_model_assets(
            SimpleNamespace(), tmp_path / "target", logger=Mock()
        ) == fallback
        assert calls == ["modelscope", "huggingface"]

    def test_hf_sdk_exception_becomes_none_and_reaches_modelscope(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION across wrapper and MOSS loop."""

        calls: list[str] = []

        def hf_snapshot_download(**_kwargs):
            calls.append("huggingface")
            raise RuntimeError("synthetic HF runtime failure")

        _install_fake_huggingface_module(monkeypatch, hf_snapshot_download)
        fallback = tmp_path / "modelscope-result"
        monkeypatch.setattr(
            model_sources,
            "_moss_download_plan",
            lambda _cfg: [
                ("huggingface", "hf/model"),
                ("modelscope", "ms/model"),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope") or fallback,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_model_assets",
            lambda candidate, **_kwargs: _same_path(candidate, fallback),
        )

        assert model_sources._download_moss_model_assets(
            SimpleNamespace(), tmp_path / "target", logger=Mock()
        ) == fallback
        assert calls == ["huggingface", "modelscope"]

    def test_modelscope_sdk_exception_logs_safely_and_reaches_hf_fallback(
        self, monkeypatch, tmp_path
    ):
        calls: list[str] = []
        error = RuntimeError(SYNTHETIC_MARKER)
        fallback = tmp_path / "hf-model"
        log = Mock()

        def modelscope_snapshot_download(_repo_id, **_kwargs):
            calls.append("modelscope")
            raise error

        _install_fake_modelscope_module(monkeypatch, modelscope_snapshot_download)
        monkeypatch.setattr(
            model_sources,
            "_moss_download_plan",
            lambda _cfg: [
                ("modelscope", "ms/model"),
                ("huggingface", "hf/model"),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or fallback,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_model_assets",
            lambda candidate, **_kwargs: _same_path(candidate, fallback),
        )

        result = model_sources._download_moss_model_assets(
            SimpleNamespace(), tmp_path / "target", logger=log
        )

        assert result == fallback
        assert calls == ["modelscope", "huggingface"]
        _assert_safe_fallback_warning(log, repo="ms/model")

    def test_preferred_success_stops_loop(self, monkeypatch, tmp_path):
        calls: list[str] = []
        success = tmp_path / "success"
        monkeypatch.setattr(
            model_sources,
            "_moss_download_plan",
            lambda _cfg: [
                ("huggingface", "hf/model"),
                ("modelscope", "ms/model"),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or success,
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope")
            or pytest.fail("fallback must not run"),
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_model_assets",
            lambda candidate, **_kwargs: _same_path(candidate, success),
        )

        assert model_sources._download_moss_model_assets(
            SimpleNamespace(), tmp_path / "target", logger=Mock()
        ) == success
        assert calls == ["huggingface"]

    def test_clean_exhaustion_returns_target_for_later_runtime_validation(
        self, monkeypatch, tmp_path
    ):
        """Download exhaustion is distinct from later runtime rejection."""

        calls: list[str] = []
        target = tmp_path / "moss-model"
        cfg = SimpleNamespace(moss_model_dir=target, model_source="huggingface")
        monkeypatch.setattr(
            model_sources, "resolve_valid_moss_model_dir", lambda *_args, **_kwargs: None
        )
        monkeypatch.setattr(
            model_sources,
            "_moss_download_plan",
            lambda _cfg: [
                ("huggingface", "hf/model"),
                ("modelscope", "ms/model"),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or None,
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope") or None,
        )

        assert model_sources.ensure_moss_model_dir(cfg, logger=Mock()) == target
        assert cfg.moss_model_dir == target
        assert calls == ["huggingface", "modelscope"]


class TestMossTokenizerFallback:
    """Independent execution contracts for the MOSS audio tokenizer."""

    def test_clean_failure_permits_ordered_fallback(self, monkeypatch, tmp_path):
        calls: list[str] = []
        fallback = tmp_path / "tokenizer-fallback"
        monkeypatch.setattr(
            model_sources,
            "_moss_audio_tokenizer_download_plan",
            lambda _cfg: [
                ("modelscope", "ms/tokenizer"),
                ("huggingface", "hf/tokenizer"),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope") or None,
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or fallback,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_audio_tokenizer_assets",
            lambda candidate, **_kwargs: _same_path(candidate, fallback),
        )

        assert model_sources._download_moss_audio_tokenizer_assets(
            SimpleNamespace(), tmp_path / "tokenizer-target", logger=Mock()
        ) == fallback
        assert calls == ["modelscope", "huggingface"]

    def test_hf_sdk_exception_becomes_none_and_reaches_modelscope(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION across wrapper and tokenizer loop."""

        calls: list[str] = []

        def hf_snapshot_download(**_kwargs):
            calls.append("huggingface")
            raise RuntimeError("synthetic HF runtime failure")

        _install_fake_huggingface_module(monkeypatch, hf_snapshot_download)
        fallback = tmp_path / "modelscope-tokenizer"
        monkeypatch.setattr(
            model_sources,
            "_moss_audio_tokenizer_download_plan",
            lambda _cfg: [
                ("huggingface", "hf/tokenizer"),
                ("modelscope", "ms/tokenizer"),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope") or fallback,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_audio_tokenizer_assets",
            lambda candidate, **_kwargs: _same_path(candidate, fallback),
        )

        assert model_sources._download_moss_audio_tokenizer_assets(
            SimpleNamespace(), tmp_path / "tokenizer-target", logger=Mock()
        ) == fallback
        assert calls == ["huggingface", "modelscope"]

    def test_default_modelscope_exception_logs_safely_and_reaches_hf_fallback(
        self, monkeypatch, tmp_path
    ):
        calls: list[str] = []
        error = RuntimeError(SYNTHETIC_MARKER)
        fallback = tmp_path / "hf-tokenizer"
        log = Mock()
        cfg = SimpleNamespace(
            moss_audio_tokenizer_modelscope_repo="openmoss/MOSS-Audio-Tokenizer-Nano-ONNX",
            moss_audio_tokenizer_hf_repo="openmoss/MOSS-Audio-Tokenizer-Nano-ONNX",
        )

        def modelscope_snapshot_download(_repo_id, **_kwargs):
            calls.append("modelscope")
            raise error

        _install_fake_modelscope_module(monkeypatch, modelscope_snapshot_download)
        monkeypatch.setattr(
            model_sources,
            "resolve_model_source",
            lambda _cfg: "modelscope",
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or fallback,
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_audio_tokenizer_assets",
            lambda candidate, **_kwargs: _same_path(candidate, fallback),
        )

        result = model_sources._download_moss_audio_tokenizer_assets(
            cfg, tmp_path / "tokenizer-target", logger=log
        )

        assert result == fallback
        assert calls == ["modelscope", "huggingface"]
        _assert_safe_fallback_warning(
            log,
            repo="openmoss/MOSS-Audio-Tokenizer-Nano-ONNX",
        )

    def test_independent_repos_target_and_success_stop_without_model_crosswire(
        self, monkeypatch, tmp_path
    ):
        calls: list[tuple[str, Path]] = []
        resolver_calls: list[object] = []
        target = tmp_path / "audio-tokenizer"
        cfg = SimpleNamespace(
            moss_hf_repo="hf/model-do-not-use",
            moss_modelscope_repo="ms/model-do-not-use",
            moss_audio_tokenizer_hf_repo="hf/tokenizer",
            moss_audio_tokenizer_modelscope_repo="ms/tokenizer",
        )

        def resolve(config):
            resolver_calls.append(config)
            return "huggingface"

        def hf_download(repo, destination, **_kwargs):
            calls.append((repo, destination))
            return target

        monkeypatch.setattr(model_sources, "resolve_model_source", resolve)
        monkeypatch.setattr(
            model_sources,
            "_moss_download_plan",
            lambda _cfg: pytest.fail("MOSS model plan must not be used"),
        )
        monkeypatch.setattr(
            model_sources, "_huggingface_snapshot_download", hf_download
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: pytest.fail("fallback must not run"),
        )
        monkeypatch.setattr(
            model_sources,
            "has_valid_moss_audio_tokenizer_assets",
            lambda candidate, **_kwargs: _same_path(candidate, target),
        )

        assert model_sources._download_moss_audio_tokenizer_assets(
            cfg, target, logger=Mock()
        ) == target
        assert calls == [("hf/tokenizer", target)]
        assert resolver_calls == [cfg]

    def test_clean_exhaustion_returns_independent_target_for_runtime_validation(
        self, monkeypatch, tmp_path
    ):
        """Download exhaustion is distinct from later tokenizer rejection."""

        calls: list[str] = []
        model_target = tmp_path / "moss-model"
        tokenizer_target = tmp_path / "audio-tokenizer"
        cfg = SimpleNamespace(
            moss_model_dir=model_target,
            moss_audio_tokenizer_model_dir=tokenizer_target,
            model_source="modelscope",
        )
        monkeypatch.setattr(
            model_sources,
            "resolve_valid_moss_audio_tokenizer_dir",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            model_sources,
            "_moss_audio_tokenizer_download_plan",
            lambda _cfg: [
                ("modelscope", "ms/tokenizer"),
                ("huggingface", "hf/tokenizer"),
            ],
        )
        monkeypatch.setattr(
            model_sources,
            "_modelscope_snapshot_download",
            lambda *_args, **_kwargs: calls.append("modelscope") or None,
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface") or None,
        )

        assert model_sources.ensure_moss_audio_tokenizer_dir(
            cfg, logger=Mock()
        ) == tokenizer_target
        assert cfg.moss_audio_tokenizer_model_dir == tokenizer_target
        assert cfg.moss_model_dir == model_target
        assert calls == ["modelscope", "huggingface"]


class TestManagedKokoroBoundary:
    def test_managed_executor_exception_remains_intentional_fail_closed(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR CONTRACT: managed integrity must not inherit normal fallback."""

        error = RuntimeError("synthetic managed provider failure")
        calls: list[str] = []
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
            model_sources,
            "_kokoro_download_plan",
            lambda *_args, **_kwargs: [
                ("modelscope", "managed/ms", "a" * 40),
                ("huggingface", "managed/hf", "b" * 40),
            ],
        )

        def fail_modelscope(*_args, **_kwargs):
            calls.append("modelscope")
            raise error

        monkeypatch.setattr(
            model_sources, "_modelscope_snapshot_download", fail_modelscope
        )
        monkeypatch.setattr(
            model_sources,
            "_huggingface_snapshot_download",
            lambda *_args, **_kwargs: calls.append("huggingface")
            or pytest.fail("managed fallback must not run after exception"),
        )

        with pytest.raises(KokoroAssetIntegrityError) as raised:
            model_sources._download_kokoro_assets(
                SimpleNamespace(),
                tmp_path / "managed",
                logger=Mock(),
                managed=True,
            )

        assert raised.value.__cause__ is error
        assert calls == ["modelscope"]


class TestZipVoiceExecutorExclusion:
    def test_zipvoice_is_outside_generic_snapshot_executor_contract(self):
        """STATIC OWNERSHIP CONTRACT; ZipVoice remains a separate P2F boundary."""

        source = (PACKAGE_ROOT / "zipvoice" / "assets.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "huggingface_hub"
            for alias in node.names
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        assert "hf_hub_download" in imported
        assert "snapshot_download" not in called_names
        assert "_huggingface_snapshot_download" not in source
        assert "_modelscope_snapshot_download" not in source
        assert "_generic_download_plan" not in source
        assert MODEL_SOURCE_METADATA.excluded_engine_scope == "zipvoice"
