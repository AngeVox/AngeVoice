"""Hermetic lifecycle regressions for lazy English G2P initialization."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

from kokoro_tts.config import TTSConfig
from kokoro_tts.engine import TTSEngine
import kokoro_tts.engine as engine_module


@pytest.fixture
def lazy_engine(monkeypatch, tmp_path):
    state = SimpleNamespace(
        language_codes=[],
        english_creations=0,
        english_repo_ids=[],
        fail_english=False,
        fail_phonemes=False,
        creation_delay=0.0,
        fail_stage=None,
        load_error=RuntimeError("fake runtime construction failed"),
        initialize_english_during_load=False,
    )

    class FakeKModel:
        MODEL_NAMES = {}

        def __init__(self, **_kwargs):
            if state.fail_stage == "model":
                raise state.load_error

        def to(self, _device):
            if state.fail_stage == "device":
                raise state.load_error
            return self

        def eval(self):
            if state.fail_stage == "eval":
                raise state.load_error
            return self

    class FakeKPipeline:
        def __init__(self, *, lang_code, repo_id, model, en_callable=None, **_kwargs):
            state.language_codes.append(lang_code)
            if lang_code == "z":
                if state.initialize_english_during_load:
                    en_callable("Hello")
                if state.fail_stage == "pipeline":
                    raise state.load_error
            if lang_code == "a":
                state.english_creations += 1
                state.english_repo_ids.append(repo_id)
                if state.creation_delay:
                    time.sleep(state.creation_delay)
                if state.fail_english:
                    raise RuntimeError("fake English G2P initialization failed")
            self.lang_code = lang_code
            self.repo_id = repo_id
            self.model = model
            self.en_callable = en_callable

        def __call__(self, text):
            if self.lang_code == "a" and state.fail_phonemes:
                raise RuntimeError("fake English phoneme generation failed")
            yield SimpleNamespace(phonemes=f"phonemes:{text}")

    fake_kokoro = ModuleType("kokoro")
    fake_kokoro.KModel = FakeKModel
    fake_kokoro.KPipeline = FakeKPipeline
    fake_torch = ModuleType("torch")
    fake_torch.set_num_threads = lambda _count: None
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(engine_module, "has_valid_kokoro_local_assets", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(engine_module, "_single_layer_rnn_dropout_compat", lambda: nullcontext())

    engine = TTSEngine(TTSConfig(model_dir=tmp_path, device="cpu", model_source="offline"))
    engine.load()
    return engine, state


def test_load_builds_only_chinese_pipeline(lazy_engine):
    engine, state = lazy_engine

    assert state.language_codes == ["z"]
    assert engine._en_pipeline is None
    assert engine._zh_pipeline is not None


@pytest.mark.parametrize("stage", ["model", "device", "eval", "pipeline"])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_failed_load_clears_owned_runtime_and_allows_retry(lazy_engine, stage, error_type):
    engine, state = lazy_engine
    engine.unload()
    state.fail_stage = stage
    state.load_error = error_type("fake runtime construction failed")
    state.initialize_english_during_load = True

    with pytest.raises(error_type) as caught:
        engine.load()

    assert caught.value is state.load_error
    assert not engine.is_loaded
    assert engine._model is None
    assert engine._zh_pipeline is None
    assert engine._en_pipeline is None

    state.fail_stage = None
    assert engine.load() is engine
    assert engine.is_loaded
    assert engine._zh_pipeline.model is engine._model
    assert engine._zh_pipeline.en_callable("Again") == "phonemes:Again"
    runtime = (engine._model, engine._zh_pipeline, engine._en_pipeline)
    creations = list(state.language_codes)
    assert engine.load() is engine
    assert runtime == (engine._model, engine._zh_pipeline, engine._en_pipeline)
    assert state.language_codes == creations
    engine.unload()
    assert not engine.is_loaded
    assert (engine._model, engine._zh_pipeline, engine._en_pipeline) == (None, None, None)


def test_first_english_callback_initializes_once_and_reuses_pipeline(lazy_engine):
    engine, state = lazy_engine
    callback = engine._zh_pipeline.en_callable

    assert callback("Hello") == "phonemes:Hello"
    assert callback("World") == "phonemes:World"

    assert state.english_creations == 1
    assert state.language_codes == ["z", "a"]
    assert engine._en_pipeline is not None


def test_failed_reload_preserves_last_successful_device(lazy_engine, monkeypatch):
    engine, state = lazy_engine
    engine.unload()
    monkeypatch.setattr(engine.config, "resolve_device", lambda: "cuda")
    state.fail_stage = "pipeline"
    with pytest.raises(RuntimeError):
        engine.load()
    assert engine.device == "cpu"
    state.fail_stage = None
    engine.load()
    assert engine.device == "cuda"
    engine.unload()
    assert engine.device == "cuda"


@pytest.mark.parametrize("message", ["WeightsUnpickler", "Unsupported operand 118"])
def test_failed_weight_load_retains_actionable_error_and_cause(lazy_engine, message):
    engine, state = lazy_engine
    engine.unload()
    state.fail_stage = "model"
    state.load_error = ValueError(message)
    with pytest.raises(RuntimeError, match="Kokoro 模型权重加载失败") as caught:
        engine.load()
    assert caught.value.__cause__ is state.load_error
    assert not engine.is_loaded
    assert engine._model is None


def test_remote_load_and_optional_thread_tuning_failure(lazy_engine, monkeypatch):
    engine, state = lazy_engine
    engine.unload()
    monkeypatch.setattr(engine, "_prepare_kokoro_load", lambda: (None, None, False))
    monkeypatch.setattr(engine_module, "resolve_model_source", lambda _config: "huggingface")

    def unavailable_thread_tuning(_count):
        raise RuntimeError("thread tuning unavailable")

    monkeypatch.setattr(sys.modules["torch"], "set_num_threads", unavailable_thread_tuning)
    assert engine.load() is engine
    assert engine.is_loaded
    assert engine._zh_pipeline.model is engine._model
    assert engine._en_pipeline is None


def test_lazy_english_pipeline_uses_repo_id_captured_during_load(lazy_engine):
    engine, state = lazy_engine
    load_time_repo_id = engine._zh_pipeline.repo_id
    engine.config.kokoro_hf_repo = "changed/repo"

    assert engine._zh_pipeline.en_callable("Hello") == "phonemes:Hello"
    assert state.english_repo_ids == [load_time_repo_id]
    assert state.english_repo_ids != ["changed/repo"]


@pytest.mark.parametrize(("text", "expected"), [("Kokoro", "kˈOkəɹO"), ("Sol", "sˈOl")])
def test_special_english_pronunciations_do_not_initialize_pipeline(lazy_engine, text, expected):
    engine, state = lazy_engine

    assert engine._zh_pipeline.en_callable(text) == expected
    assert engine._en_pipeline is None
    assert state.english_creations == 0


def test_failed_english_initialization_preserves_chinese_engine_and_can_retry(lazy_engine):
    engine, state = lazy_engine
    callback = engine._zh_pipeline.en_callable
    state.fail_english = True

    with pytest.raises(RuntimeError, match="fake English G2P initialization failed"):
        callback("Hello")

    assert engine._en_pipeline is None
    assert engine._zh_pipeline is not None
    assert engine.is_loaded

    state.fail_english = False
    assert callback("Hello") == "phonemes:Hello"
    assert state.english_creations == 2
    assert engine._en_pipeline is not None


def test_phoneme_generation_failure_falls_back_without_recreating_pipeline(lazy_engine):
    engine, state = lazy_engine
    callback = engine._zh_pipeline.en_callable

    assert callback("Hello") == "phonemes:Hello"
    existing_pipeline = engine._en_pipeline
    state.fail_phonemes = True
    assert callback("World") == "World"

    assert engine._en_pipeline is existing_pipeline
    assert state.english_creations == 1

    state.fail_phonemes = False
    assert callback("Again") == "phonemes:Again"
    assert engine._en_pipeline is existing_pipeline
    assert state.english_creations == 1


def test_concurrent_first_english_callbacks_construct_one_pipeline(lazy_engine):
    engine, state = lazy_engine
    callback = engine._zh_pipeline.en_callable
    state.creation_delay = 0.05

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(callback, f"word-{index}") for index in range(8)]
        results = [future.result(timeout=2) for future in futures]

    assert results == [f"phonemes:word-{index}" for index in range(8)]
    assert state.english_creations == 1
    assert engine._en_pipeline is not None
