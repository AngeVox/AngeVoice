"""Behavior and mapping contracts for config_env 2.6.7."""

from __future__ import annotations

import ast
import dataclasses
import json
import logging
import subprocess
from pathlib import Path

import pytest

from kokoro_tts import config_env
from kokoro_tts import config_env_domain
from kokoro_tts.admin_config import load_runtime_config
from kokoro_tts.config import TTSConfig


pytestmark = pytest.mark.contract

DATA_PATH = Path(__file__).parent / "data" / "config_env_surface_2_6_7.json"
SNAPSHOT = json.loads(DATA_PATH.read_text(encoding="utf-8"))
PATH_STR_FIELDS = set(SNAPSHOT["path_coercion_fields"])
CACHE_INT_ENV_NAMES = (
    "KOKORO_CACHE_MAX_ITEMS",
    "KOKORO_CACHE_MAX_BYTES",
    "KOKORO_CACHE_SKIP_TEXT_OVER_CHARS",
    "KOKORO_CACHE_SKIP_AUDIO_OVER_BYTES",
)
BATCH_INT_ENV_NAMES = (
    "KOKORO_BATCH_MAX_ITEMS",
    "KOKORO_BATCH_CONCURRENCY",
)
UPDATE_CHECK_ENV_NAMES = (
    "ANGEVOICE_UPDATE_CHECK_ENABLED",
    "ANGEVOICE_UPDATE_REPOSITORY",
    "ANGEVOICE_UPDATE_CHECK_TIMEOUT_SECONDS",
    "ANGEVOICE_UPDATE_CHECK_CACHE_SECONDS",
)
UPDATE_CHECK_DECLARATIONS = (
    ("ANGEVOICE_UPDATE_CHECK_ENABLED", "update_check_enabled", "bool", None, None),
    ("ANGEVOICE_UPDATE_REPOSITORY", "update_repository", "str", None, None),
    (
        "ANGEVOICE_UPDATE_CHECK_TIMEOUT_SECONDS",
        "update_check_timeout_seconds",
        "float",
        0.2,
        10.0,
    ),
    (
        "ANGEVOICE_UPDATE_CHECK_CACHE_SECONDS",
        "update_check_cache_seconds",
        "float",
        0.0,
        604800.0,
    ),
)
STR_ENV_KEY_ORDER = (
    "KOKORO_HOST", "KOKORO_DEVICE", "ANGEVOICE_DEPLOYMENT_PROFILE", "KOKORO_DEFAULT_VOICE",
    "KOKORO_STREAM_FORMAT", "KOKORO_MP3_BITRATE", "ANGEVOICE_AUDIO_MP3_BITRATE",
    "ANGEVOICE_AUDIO_OPUS_BITRATE", "ANGEVOICE_AUDIO_AAC_BITRATE", "ANGEVOICE_FFMPEG_BINARY",
    "ANGEVOICE_DEFAULT_MODEL", "ANGEVOICE_STARTUP_PRELOAD_MODEL", "ANGEVOICE_OUTPUT_DIR",
    "ANGEVOICE_RUNTIME_CONFIG_FILE", "ANGEVOICE_UPDATE_REPOSITORY", "ANGEVOICE_CREDENTIALS_DIR",
    "ANGEVOICE_ADMIN_CREDENTIALS_FILE", "ANGEVOICE_MODEL_SOURCE", "ANGEVOICE_MODEL_SOURCE_DETECT_URL",
    "ANGEVOICE_MODEL_SOURCE_PROBE_HF_URL", "ANGEVOICE_MODEL_SOURCE_PROBE_MODELSCOPE_URL",
    "ANGEVOICE_API_KEY_FILE", "ANGEVOICE_SINGLE_NEWLINE_POLICY", "ANGEVOICE_TN_ENGINE",
    "KOKORO_HF_REPO", "KOKORO_MODELSCOPE_REPO", "MOSS_MODELSCOPE_REPO", "MOSS_HF_REPO",
    "MOSS_AUDIO_TOKENIZER_MODELSCOPE_REPO", "MOSS_AUDIO_TOKENIZER_HF_REPO", "MOSS_EXECUTION_PROVIDER",
    "ZIPVOICE_EXECUTION_PROVIDER", "MOSS_DEFAULT_VOICE", "MOSS_SAMPLE_MODE",
    "MOSS_PROCESS_ISOLATION_PROVIDERS", "MOSS_APPLY_ANGEVOICE_RULES", "MOSS_MIXED_ENGLISH_POLICY",
)
FLOAT_ENV_KEY_ORDER = (
    "KOKORO_DEFAULT_SPEED", "KOKORO_REQUEST_TIMEOUT_SECONDS", "ANGEVOICE_WEBSOCKET_STREAM_IDLE_TIMEOUT_SECONDS",
    "KOKORO_STREAM_CHUNK_SECONDS", "KOKORO_STREAM_PREBUFFER_SECONDS", "ANGEVOICE_MODEL_SWITCH_TIMEOUT_SECONDS",
    "MOSS_PROMPT_AUDIO_MAX_SECONDS", "ZIPVOICE_PROMPT_AUDIO_MAX_SECONDS", "ZIPVOICE_GUIDANCE_SCALE",
    "ZIPVOICE_T_SHIFT", "ZIPVOICE_TARGET_RMS", "ZIPVOICE_FEAT_SCALE", "ZIPVOICE_CUDA_MAX_DURATION",
    "MOSS_STREAM_CHUNK_SECONDS", "MOSS_STREAM_PREBUFFER_SECONDS", "MOSS_MAX_CLIP_RATIO",
    "MOSS_OUTPUT_TARGET_PEAK", "MOSS_OUTPUT_GAIN", "KOKORO_RATE_LIMIT_QPS",
    "MOSS_STREAM_BUDGET_THRESHOLD_LOW", "MOSS_STREAM_BUDGET_THRESHOLD_MID", "MOSS_STREAM_BUDGET_THRESHOLD_HIGH",
    "MOSS_STREAM_CHUNK_MIN_FLOOR", "MOSS_PROCESS_KILL_GRACE_SECONDS", "ANGEVOICE_ENGINE_PROCESS_KILL_GRACE_SECONDS",
    "ANGEVOICE_ENGINE_PROCESS_STREAM_DRAIN_SECONDS", "ANGEVOICE_ENGINE_PROCESS_STREAM_IDLE_TIMEOUT_SECONDS",
    "ANGEVOICE_FFMPEG_TIMEOUT_SECONDS", "MOSS_OUTPUT_EDGE_FADE_MS", "MOSS_TRIM_SILENCE_DB",
    "MOSS_MAX_SILENCE_MS", "MOSS_CROSSFADE_MS", "MOSS_SEGMENT_PAUSE_MS", "MOSS_RUNTIME_PAUSE_MAX_MS",
    "MOSS_FULL_CODEC_OOM_COOLDOWN_SECONDS", "MOSS_VRAM_SNAPSHOT_TTL_SECONDS",
    "ANGEVOICE_MODEL_SOURCE_DETECT_TIMEOUT_SECONDS", "ANGEVOICE_MODEL_SOURCE_PROBE_TIMEOUT_SECONDS",
    "ANGEVOICE_UPDATE_CHECK_TIMEOUT_SECONDS", "ANGEVOICE_UPDATE_CHECK_CACHE_SECONDS",
    "ANGEVOICE_IDLE_TIMEOUT_SECONDS", "ANGEVOICE_IDLE_CHECK_INTERVAL",
    "ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_DELAY_SECONDS", "ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_COOLDOWN_SECONDS",
)
BOOL_ENV_KEY_ORDER = (
    "KOKORO_STREAM_BINARY_ENABLED", "ANGEVOICE_ACCESS_LOG_ENABLED", "KOKORO_CACHE_ENABLED",
    "KOKORO_QUEUE_STATUS_ENABLED", "KOKORO_METRICS_ENABLED", "KOKORO_BATCH_ENABLED",
    "KOKORO_ADMIN_ENABLED", "KOKORO_VOICE_UPLOAD_ENABLED", "KOKORO_MP3_ENABLED",
    "ANGEVOICE_FFMPEG_ENABLED", "ANGEVOICE_MODEL_SWITCH_ENABLED", "ANGEVOICE_MODEL_UNLOAD_ON_SWITCH",
    "ANGEVOICE_SAVE_OUTPUTS", "ANGEVOICE_IDLE_UNLOAD_CURRENT", "KOKORO_PREFETCH_VOICES",
    "MOSS_CUDA_ENABLED", "MOSS_ENABLE_WETEXT_PROCESSING", "MOSS_ENABLE_NORMALIZE_TTS_TEXT",
    "MOSS_REALTIME_STREAMING_DECODE", "MOSS_CUDA_SELF_TEST_ENABLED", "MOSS_AUTO_FALLBACK_CPU",
    "MOSS_QUALITY_GATE_ENABLED", "MOSS_OUTPUT_PEAK_NORMALIZE_ENABLED", "MOSS_PROCESS_ISOLATION_ENABLED",
    "KOKORO_PROCESS_ISOLATION_ENABLED", "ZIPVOICE_PROCESS_ISOLATION_ENABLED", "ANGEVOICE_STARTUP_PRELOAD_ENABLED",
    "MOSS_OUTPUT_DECLICK_ENABLED", "MOSS_AUDIO_POLISH_ENABLED", "MOSS_TRIM_SILENCE_ENABLED",
    "MOSS_VRAM_GUARD_ENABLED", "MOSS_DISABLE_FULL_CODEC_AFTER_OOM", "ZIPVOICE_DOWNLOAD_ENABLED",
    "ZIPVOICE_REMOVE_LONG_SIL", "ZIPVOICE_CUDA_ENABLED", "ZIPVOICE_AUTO_FALLBACK_CPU",
    "KOKORO_TRUST_PROXY_HEADERS", "KOKORO_PUBLIC_STATUS_ENDPOINTS", "ANGEVOICE_UPDATE_CHECK_ENABLED",
    "ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD",
)
INT_ENV_KEY_ORDER = (
    "KOKORO_PORT",
    "KOKORO_WORKERS",
    "KOKORO_MAX_CONCURRENT_REQUESTS",
    "KOKORO_MAX_TEXT_LENGTH",
    "KOKORO_SEGMENT_LENGTH",
    "MOSS_SEGMENT_LENGTH",
    "KOKORO_CACHE_MAX_ITEMS",
    "KOKORO_CACHE_MAX_BYTES",
    "KOKORO_CACHE_SKIP_TEXT_OVER_CHARS",
    "KOKORO_CACHE_SKIP_AUDIO_OVER_BYTES",
    "KOKORO_BATCH_MAX_ITEMS",
    "KOKORO_BATCH_CONCURRENCY",
    "KOKORO_VOICE_UPLOAD_MAX_BYTES",
    "ANGEVOICE_OUTPUT_MAX_FILES",
    "MOSS_CPU_THREADS",
    "ZIPVOICE_CPU_THREADS",
    "ZIPVOICE_CUDA_DEVICE_INDEX",
    "ZIPVOICE_NUM_STEPS",
    "ZIPVOICE_PROMPT_UPLOAD_MAX_BYTES",
    "MOSS_PROMPT_UPLOAD_MAX_BYTES",
    "KOKORO_TTS_REQUEST_MAX_BYTES",
    "MOSS_PROMPT_CACHE_MAX_ITEMS",
    "MOSS_MAX_NEW_FRAMES",
    "MOSS_VOICE_CLONE_MAX_TEXT_TOKENS",
    "MOSS_SEED",
    "MOSS_CUDA_MEMORY_LIMIT_MB",
    "MOSS_STREAM_QUEUE_MAX_ITEMS",
    "MOSS_VRAM_SAFE_FREE_MB",
    "MOSS_VRAM_CRITICAL_FREE_MB",
    "MOSS_LOW_VRAM_SEGMENT_LENGTH",
    "MOSS_LOW_VRAM_MAX_NEW_FRAMES",
    "MOSS_LOW_VRAM_TEXT_TOKENS",
    "KOKORO_RATE_LIMIT_BURST",
    "KOKORO_MAX_QUEUE_LENGTH",
    "KOKORO_WS_MAX_CONNECTIONS",
    "KOKORO_WS_MAX_MESSAGE_BYTES",
    "ANGEVOICE_RESTART_AFTER_IDLE_UNLOAD_EXIT_CODE",
)


def _known_env_names() -> set[str]:
    names = set()
    for key in ("str_env", "int_env", "float_env", "bool_env"):
        names.update(SNAPSHOT[key])
    names.update(item["env"] for item in SNAPSHOT["special_cases"])
    names.update(item["env"] for item in SNAPSHOT["direct_readers"])
    return names


@pytest.fixture(autouse=True)
def _clean_configuration_environment(monkeypatch):
    for name in _known_env_names():
        monkeypatch.delenv(name, raising=False)


def _cfg(tmp_path: Path) -> TTSConfig:
    return TTSConfig(model_dir=tmp_path / "model")


def _clamp(value, minimum, maximum):
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def test_mapping_tables_match_the_checked_in_surface() -> None:
    assert dict(sorted(config_env.STR_ENV.items())) == SNAPSHOT["str_env"]
    assert dict(sorted(config_env.BOOL_ENV.items())) == SNAPSHOT["bool_env"]
    assert {
        env: {"attr": spec.attr, "min": spec.min_value, "max": spec.max_value}
        for env, spec in sorted(config_env.INT_ENV.items())
    } == SNAPSHOT["int_env"]
    assert {
        env: {"attr": spec.attr, "min": spec.min_value, "max": spec.max_value}
        for env, spec in sorted(config_env.FLOAT_ENV.items())
    } == SNAPSHOT["float_env"]
    assert tuple(config_env.STR_ENV) == STR_ENV_KEY_ORDER
    assert tuple(config_env.FLOAT_ENV) == FLOAT_ENV_KEY_ORDER
    assert tuple(config_env.BOOL_ENV) == BOOL_ENV_KEY_ORDER
    assert tuple(config_env.INT_ENV) == INT_ENV_KEY_ORDER


def test_update_check_declarations_project_exact_existing_maps_and_order() -> None:
    declarations = config_env_domain.UPDATE_CHECK_ENV_DECLARATIONS
    assert tuple(
        (item.env_name, item.attr, item.family, item.min_value, item.max_value)
        for item in declarations
    ) == UPDATE_CHECK_DECLARATIONS

    families = {
        "str": config_env.STR_ENV,
        "float": config_env.FLOAT_ENV,
        "bool": config_env.BOOL_ENV,
    }
    for declaration in declarations:
        mapping = families[declaration.family]
        actual = mapping[declaration.env_name]
        if declaration.family == "float":
            assert actual == config_env.FloatEnvSpec(
                declaration.attr, declaration.min_value, declaration.max_value
            )
        else:
            assert actual == declaration.attr

    assert tuple(name for name in config_env.STR_ENV if name in UPDATE_CHECK_ENV_NAMES) == (
        "ANGEVOICE_UPDATE_REPOSITORY",
    )
    assert tuple(name for name in config_env.FLOAT_ENV if name in UPDATE_CHECK_ENV_NAMES) == (
        "ANGEVOICE_UPDATE_CHECK_TIMEOUT_SECONDS",
        "ANGEVOICE_UPDATE_CHECK_CACHE_SECONDS",
    )
    assert tuple(name for name in config_env.BOOL_ENV if name in UPDATE_CHECK_ENV_NAMES) == (
        "ANGEVOICE_UPDATE_CHECK_ENABLED",
    )

    source_root = Path(config_env.__file__).parent
    for relative in ("config_env.py", "server.py"):
        source = (source_root / relative).read_text(encoding="utf-8")
        assert "UPDATE_CHECK_ENV_DECLARATIONS" in source
        assert not any(name in source for name in UPDATE_CHECK_ENV_NAMES)
    domain_source = (source_root / "config_env_domain.py").read_text(encoding="utf-8")
    assert all(domain_source.count(name) == 1 for name in UPDATE_CHECK_ENV_NAMES)


def test_update_check_apply_env_keeps_bool_string_float_behavior(monkeypatch, tmp_path, caplog) -> None:
    cfg = _cfg(tmp_path)
    config_env.apply_env(cfg)
    assert cfg.update_check_enabled is True
    assert cfg.update_repository == "angevox/AngeVoice"
    assert cfg.update_check_timeout_seconds == 3.0
    assert cfg.update_check_cache_seconds == 21600.0

    for raw in ("1", " true ", "YES", "On", "y"):
        monkeypatch.setenv("ANGEVOICE_UPDATE_CHECK_ENABLED", raw)
        caplog.clear()
        config_env.apply_env(cfg)
        assert cfg.update_check_enabled is True
        assert caplog.records == []
    for raw in ("", "false", "unknown"):
        monkeypatch.setenv("ANGEVOICE_UPDATE_CHECK_ENABLED", raw)
        caplog.clear()
        config_env.apply_env(cfg)
        assert cfg.update_check_enabled is False
        assert caplog.records == []

    for raw in (" owner/repository ", ""):
        monkeypatch.setenv("ANGEVOICE_UPDATE_REPOSITORY", raw)
        caplog.clear()
        config_env.apply_env(cfg)
        assert cfg.update_repository == raw
        assert caplog.records == []

    for env_name, attr, minimum, maximum, nan_result in (
        ("ANGEVOICE_UPDATE_CHECK_TIMEOUT_SECONDS", "update_check_timeout_seconds", 0.2, 10.0, 0.2),
        ("ANGEVOICE_UPDATE_CHECK_CACHE_SECONDS", "update_check_cache_seconds", 0.0, 604800.0, 0.0),
    ):
        monkeypatch.setenv(env_name, "7.5")
        config_env.apply_env(cfg)
        assert getattr(cfg, attr) == 7.5
        for raw in ("nan", "inf", "-inf"):
            monkeypatch.setenv(env_name, raw)
            caplog.clear()
            config_env.apply_env(cfg)
            expected = {"nan": nan_result, "inf": maximum, "-inf": minimum}[raw]
            assert getattr(cfg, attr) == expected
            assert caplog.records == []
        for raw in ("", "not-a-float"):
            setattr(cfg, attr, 4.5)
            monkeypatch.setenv(env_name, raw)
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="kokoro_tts.config_env"):
                config_env.apply_env(cfg)
            assert getattr(cfg, attr) == 4.5
            records = [record for record in caplog.records if record.name == "kokoro_tts.config_env"]
            assert len(records) == 1
            assert records[0].msg == "忽略无效浮点环境变量 %s=%r"
            assert records[0].args == (env_name, raw)
        monkeypatch.setenv(env_name, str(minimum - 1))
        config_env.apply_env(cfg)
        assert getattr(cfg, attr) == minimum
        monkeypatch.setenv(env_name, str(maximum + 1))
        config_env.apply_env(cfg)
        assert getattr(cfg, attr) == maximum


def test_update_check_fields_remain_outside_admin_runtime_config(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setenv("ANGEVOICE_UPDATE_CHECK_ENABLED", "false")
    monkeypatch.setenv("ANGEVOICE_UPDATE_REPOSITORY", "owner/repository")
    config_env.apply_env(cfg)
    runtime = tmp_path / "runtime-config.json"
    runtime.write_bytes(
        json.dumps(
            {"values": {"update_check_enabled": True, "update_repository": "runtime/repository"}}
        ).encode("utf-8")
    )
    cfg.runtime_config_file = runtime
    load_runtime_config(cfg)
    assert cfg.update_check_enabled is False
    assert cfg.update_repository == "owner/repository"


def test_all_mapping_attributes_are_ttsconfig_fields_and_env_names_are_unique() -> None:
    fields = {field.name for field in dataclasses.fields(TTSConfig)}
    map_names = []
    for key in ("str_env", "int_env", "float_env", "bool_env"):
        map_names.extend(SNAPSHOT[key])
        for value in SNAPSHOT[key].values():
            attr = value if isinstance(value, str) else value["attr"]
            assert attr in fields
    assert len(map_names) == len(set(map_names))
    for item in SNAPSHOT["special_cases"] + SNAPSHOT["direct_readers"]:
        if item["attr"] is not None:
            assert item["attr"] in fields
    aliases = {
        tuple(item["envs"]): item["attr"] for item in SNAPSHOT["legacy_aliases"]
    }
    assert aliases[
        ("ANGEVOICE_AUDIO_MP3_BITRATE", "KOKORO_MP3_BITRATE")
    ] == "mp3_bitrate"
    assert config_env.STR_ENV["ANGEVOICE_AUDIO_MP3_BITRATE"] == "mp3_bitrate"
    assert config_env.STR_ENV["KOKORO_MP3_BITRATE"] == "mp3_bitrate"


def test_cache_integer_declarations_preserve_mapping_content_order_and_owners() -> None:
    assert len(config_env.INT_ENV) == 37
    assert sum(
        len(mapping)
        for mapping in (
            config_env.STR_ENV,
            config_env.INT_ENV,
            config_env.FLOAT_ENV,
            config_env.BOOL_ENV,
        )
    ) == 158
    assert tuple(
        (item.env_name, item.attr, item.min_value, item.max_value)
        for item in config_env_domain.CACHE_INT_DECLARATIONS
    ) == tuple(
        (
            env_name,
            SNAPSHOT["int_env"][env_name]["attr"],
            SNAPSHOT["int_env"][env_name]["min"],
            SNAPSHOT["int_env"][env_name]["max"],
        )
        for env_name in CACHE_INT_ENV_NAMES
    )
    assert tuple(
        name for name in config_env.INT_ENV if name in CACHE_INT_ENV_NAMES
    ) == CACHE_INT_ENV_NAMES
    assert all(
        config_env.INT_ENV[name]
        == config_env.IntEnvSpec(
            SNAPSHOT["int_env"][name]["attr"],
            SNAPSHOT["int_env"][name]["min"],
            SNAPSHOT["int_env"][name]["max"],
        )
        for name in CACHE_INT_ENV_NAMES
    )

    # P2B owns parser/mapping declarations only. Worker export and Admin field
    # metadata remain compatibility/presentation consumers until later phases.
    package_root = Path(config_env.__file__).parent
    source_paths = {
        relative: package_root / relative
        for relative in (
            "config_env.py",
            "config_env_domain.py",
            "server.py",
            "admin_config/groups/cache.py",
        )
    }
    trees = {
        relative: ast.parse(path.read_text(encoding="utf-8"))
        for relative, path in source_paths.items()
    }

    def assignment_value(tree: ast.Module, name: str) -> ast.AST:
        assignments = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            ):
                assignments.append(node.value)
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == name
            ):
                assignments.append(node.value)
        assert len(assignments) == 1
        assert assignments[0] is not None
        return assignments[0]

    def constant_value(node: ast.AST) -> object:
        assert isinstance(node, ast.Constant)
        return node.value

    def call_argument(
        call: ast.Call, position: int, keyword: str, default: object
    ) -> object:
        if len(call.args) > position:
            return constant_value(call.args[position])
        matches = [item.value for item in call.keywords if item.arg == keyword]
        assert len(matches) <= 1
        return constant_value(matches[0]) if matches else default

    literal_occurrences = {env_name: [] for env_name in CACHE_INT_ENV_NAMES}
    for source_path in package_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        relative = source_path.relative_to(package_root).as_posix()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in literal_occurrences
            ):
                literal_occurrences[node.value].append(relative)

    expected_contexts = {
        "config_env_domain.py",
        "server.py",
        "admin_config/groups/cache.py",
    }
    for env_name in CACHE_INT_ENV_NAMES:
        assert set(literal_occurrences[env_name]) == expected_contexts
        assert len(literal_occurrences[env_name]) == len(expected_contexts)
    assert not any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in CACHE_INT_ENV_NAMES
        for node in ast.walk(trees["config_env.py"])
    )

    declaration_tuple = assignment_value(
        trees["config_env_domain.py"], "CACHE_INT_DECLARATIONS"
    )
    assert isinstance(declaration_tuple, ast.Tuple)
    declaration_calls = [
        item
        for item in declaration_tuple.elts
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "EnvIntDeclaration"
    ]
    assert len(declaration_calls) == len(CACHE_INT_ENV_NAMES)
    for env_name in CACHE_INT_ENV_NAMES:
        matches = [
            call
            for call in declaration_calls
            if constant_value(call.args[0]) == env_name
        ]
        assert len(matches) == 1
        call = matches[0]
        expected = SNAPSHOT["int_env"][env_name]
        assert call_argument(call, 1, "attr", None) == expected["attr"]
        assert call_argument(call, 2, "min_value", None) == expected["min"]
        assert call_argument(call, 3, "max_value", None) == expected["max"]

    worker_exports = assignment_value(trees["server.py"], "_WORKER_ENV_EXPORTS")
    assert isinstance(worker_exports, ast.Dict)
    for env_name in CACHE_INT_ENV_NAMES:
        matches = [
            value
            for key, value in zip(worker_exports.keys, worker_exports.values)
            if isinstance(key, ast.Constant) and key.value == env_name
        ]
        assert len(matches) == 1
        assert constant_value(matches[0]) == SNAPSHOT["int_env"][env_name]["attr"]

    admin_fields = assignment_value(trees["admin_config/groups/cache.py"], "FIELDS")
    admin_calls = [
        node
        for node in ast.walk(admin_fields)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "field_def"
    ]
    for env_name in CACHE_INT_ENV_NAMES:
        matches = [
            call
            for call in admin_calls
            if len(call.args) >= 2 and constant_value(call.args[1]) == env_name
        ]
        assert len(matches) == 1
        assert constant_value(matches[0].args[0]) == SNAPSHOT["int_env"][env_name]["attr"]

    config_tree = trees["config_env.py"]
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "config_env_domain"
        and any(item.name == "CACHE_INT_DECLARATIONS" for item in node.names)
        for node in config_tree.body
    )
    int_env = assignment_value(config_tree, "INT_ENV")
    assert isinstance(int_env, ast.Dict)
    declaration_mappings = [
        value
        for key, value in zip(int_env.keys, int_env.values)
        if key is None and isinstance(value, ast.DictComp)
    ]
    assert len(declaration_mappings) == 2

    def declaration_mapping_for(name: str) -> ast.DictComp:
        matches = [
            mapping
            for mapping in declaration_mappings
            if len(mapping.generators) == 1
            and isinstance(mapping.generators[0].iter, ast.Name)
            and mapping.generators[0].iter.id == name
        ]
        assert len(matches) == 1
        return matches[0]

    mapping = declaration_mapping_for("CACHE_INT_DECLARATIONS")
    assert (
        isinstance(mapping.key, ast.Attribute)
        and isinstance(mapping.key.value, ast.Name)
        and mapping.key.value.id == "declaration"
        and mapping.key.attr == "env_name"
    )
    assert len(mapping.generators) == 1
    generator = mapping.generators[0]
    assert (
        isinstance(generator.target, ast.Name)
        and generator.target.id == "declaration"
        and isinstance(generator.iter, ast.Name)
        and generator.iter.id == "CACHE_INT_DECLARATIONS"
    )


def test_batch_integer_declarations_preserve_mapping_order_and_owners() -> None:
    assert tuple(
        (item.env_name, item.attr, item.min_value, item.max_value)
        for item in config_env_domain.BATCH_INT_DECLARATIONS
    ) == tuple(
        (
            env_name,
            SNAPSHOT["int_env"][env_name]["attr"],
            SNAPSHOT["int_env"][env_name]["min"],
            SNAPSHOT["int_env"][env_name]["max"],
        )
        for env_name in BATCH_INT_ENV_NAMES
    )
    assert tuple(name for name in config_env.INT_ENV if name in BATCH_INT_ENV_NAMES) == (
        BATCH_INT_ENV_NAMES
    )
    assert all(
        config_env.INT_ENV[name]
        == config_env.IntEnvSpec(
            SNAPSHOT["int_env"][name]["attr"],
            SNAPSHOT["int_env"][name]["min"],
            SNAPSHOT["int_env"][name]["max"],
        )
        for name in BATCH_INT_ENV_NAMES
    )

    package_root = Path(config_env.__file__).parent
    config_tree = ast.parse((package_root / "config_env.py").read_text(encoding="utf-8"))
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "config_env_domain"
        and any(item.name == "BATCH_INT_DECLARATIONS" for item in node.names)
        for node in config_tree.body
    )
    int_env = next(
        node.value
        for node in config_tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "INT_ENV"
    )
    assert isinstance(int_env, ast.Dict)
    batch_mappings = [
        value
        for key, value in zip(int_env.keys, int_env.values)
        if key is None
        and isinstance(value, ast.DictComp)
        and len(value.generators) == 1
        and isinstance(value.generators[0].iter, ast.Name)
        and value.generators[0].iter.id == "BATCH_INT_DECLARATIONS"
    ]
    assert len(batch_mappings) == 1
    mapping = batch_mappings[0]
    assert (
        isinstance(mapping.key, ast.Attribute)
        and isinstance(mapping.key.value, ast.Name)
        and mapping.key.value.id == "declaration"
        and mapping.key.attr == "env_name"
    )

    source_paths = {
        "config_env.py": package_root / "config_env.py",
        "config_env_domain.py": package_root / "config_env_domain.py",
        "server.py": package_root / "server.py",
        "service_extras.py": package_root / "service_extras.py",
    }
    source_text = {
        name: path.read_text(encoding="utf-8") for name, path in source_paths.items()
    }
    for env_name in BATCH_INT_ENV_NAMES:
        assert env_name not in source_text["config_env.py"]
        assert source_text["config_env_domain.py"].count(env_name) == 1
        assert source_text["server.py"].count(env_name) == 1
    assert "cfg.batch_max_items" in source_text["service_extras.py"]
    assert 'getattr(cfg, "batch_concurrency", 1)' in source_text["service_extras.py"]
    admin_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (package_root / "admin_config").rglob("*.py")
    )
    assert all(env_name not in admin_source for env_name in BATCH_INT_ENV_NAMES)


@pytest.mark.parametrize("env_name", BATCH_INT_ENV_NAMES)
def test_batch_integer_apply_env_behavior_warning_and_runtime_config_non_ownership(
    monkeypatch, tmp_path, caplog, env_name
) -> None:
    attr = SNAPSHOT["int_env"][env_name]["attr"]
    cfg = _cfg(tmp_path)
    setattr(cfg, attr, 23)
    config_env.apply_env(cfg)
    assert getattr(cfg, attr) == 23

    for raw, expected in (
        ("7", 7),
        ("1", 1),
        ("0", 1),
        ("-7", 1),
        ("  7  ", 7),
        ("+7", 7),
        (str(10**200), 10**200),
    ):
        monkeypatch.setenv(env_name, raw)
        config_env.apply_env(cfg)
        assert getattr(cfg, attr) == expected

    for raw in ("not-an-integer", ""):
        setattr(cfg, attr, 23)
        monkeypatch.setenv(env_name, raw)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="kokoro_tts.config_env"):
            config_env.apply_env(cfg)
        assert getattr(cfg, attr) == 23
        records = [
            record for record in caplog.records if record.name == "kokoro_tts.config_env"
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert records[0].msg == "忽略无效整数环境变量 %s=%r"
        assert records[0].args == (env_name, raw)
        assert records[0].getMessage() == f"忽略无效整数环境变量 {env_name}={raw!r}"

    monkeypatch.setenv(env_name, "7")
    config_env.apply_env(cfg)
    runtime = tmp_path / "runtime-config.json"
    runtime.write_bytes(json.dumps({"values": {attr: 19}}).encode("utf-8"))
    cfg.runtime_config_file = runtime
    load_runtime_config(cfg)
    # Batch fields are not Admin runtime-config fields. The same-name JSON
    # value is ignored; this is not a precedence contest, so the applied ENV
    # value remains unchanged.
    assert getattr(cfg, attr) == 7


@pytest.mark.parametrize("env_name", BATCH_INT_ENV_NAMES)
def test_batch_integer_parser_and_apply_env_keep_separate_ownership(
    monkeypatch, tmp_path, env_name
) -> None:
    monkeypatch.setenv(env_name, "-7")
    assert config_env_domain.parse_int_env(env_name, 23) == -7
    cfg = _cfg(tmp_path)
    config_env.apply_env(cfg)
    assert getattr(cfg, SNAPSHOT["int_env"][env_name]["attr"]) == 1


@pytest.mark.parametrize("env_name", CACHE_INT_ENV_NAMES)
def test_cache_integer_apply_env_behavior_and_runtime_precedence(
    monkeypatch, tmp_path, caplog, env_name
) -> None:
    attr = SNAPSHOT["int_env"][env_name]["attr"]
    cfg = _cfg(tmp_path)
    setattr(cfg, attr, 23)
    config_env.apply_env(cfg)
    assert getattr(cfg, attr) == 23

    monkeypatch.setenv(env_name, "7")
    config_env.apply_env(cfg)
    assert getattr(cfg, attr) == 7

    monkeypatch.setenv(env_name, "not-an-integer")
    with caplog.at_level("WARNING", logger="kokoro_tts.config_env"):
        config_env.apply_env(cfg)
    assert getattr(cfg, attr) == 7
    assert sum(record.name == "kokoro_tts.config_env" for record in caplog.records) == 1

    monkeypatch.setenv(env_name, "-7")
    config_env.apply_env(cfg)
    assert getattr(cfg, attr) == 0

    runtime = tmp_path / "runtime-config.json"
    runtime.write_bytes(json.dumps({"values": {attr: 19}}).encode("utf-8"))
    cfg.runtime_config_file = runtime
    load_runtime_config(cfg)
    assert getattr(cfg, attr) == 19


def test_p2a1_snapshots_keep_head_hashes() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in (
        "ttsconfig_shape_2_6_7.json",
        "config_env_surface_2_6_7.json",
        "admin_config_surface_2_6_7.json",
    ):
        path = Path(__file__).with_name("data") / name
        relative = path.relative_to(root).as_posix()
        current = subprocess.check_output(["git", "hash-object", relative], cwd=root)
        expected = subprocess.check_output(
            ["git", "rev-parse", f"HEAD:{relative}"], cwd=root
        ).strip()
        assert current.strip() == expected


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _reader_source_and_qualname(reader: str) -> tuple[Path, list[str]]:
    source_root = Path(config_env.__file__).parent
    module_files = {
        "kokoro_tts.config": source_root / "config.py",
        "kokoro_tts.model_sources": source_root / "model_sources.py",
        "kokoro_tts.zipvoice.runtime_cpu_onnx": source_root
        / "zipvoice"
        / "runtime_cpu_onnx.py",
        "kokoro_tts.zipvoice.runtime_cuda_torch": source_root
        / "zipvoice"
        / "runtime_cuda_torch.py",
    }
    module = next(
        (
            name
            for name in sorted(module_files, key=len, reverse=True)
            if reader.startswith(name + ".")
        ),
        None,
    )
    assert module is not None, f"unresolvable direct-reader module: {reader}"
    return module_files[module], reader.removeprefix(module + ".").split(".")


def _resolve_qualname(tree: ast.Module, qualname: list[str]) -> ast.AST:
    children: list[ast.stmt] = tree.body
    resolved: ast.AST | None = None
    for name in qualname:
        resolved = next(
            (
                node
                for node in children
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == name
            ),
            None,
        )
        assert resolved is not None, f"unresolvable direct-reader qualname: {'.'.join(qualname)}"
        children = resolved.body
    return resolved


class _FunctionBodyEnvReader(ast.NodeVisitor):
    """Collect only os.environ reads owned by one resolved function/method."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Nested definitions have their own ownership and are not reader body facts.
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "getenv"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                self.names.add(node.args[0].value)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and _is_os_environ(node.func.value)
            ):
                self.names.add(node.args[0].value)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if (
            _is_os_environ(node.value)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            self.names.add(node.slice.value)
        self.generic_visit(node)


def _reader_env_names(reader: str) -> set[str]:
    module_path, qualname = _reader_source_and_qualname(reader)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    symbol = _resolve_qualname(tree, qualname)
    assert isinstance(symbol, (ast.FunctionDef, ast.AsyncFunctionDef))
    visitor = _FunctionBodyEnvReader()
    for statement in symbol.body:
        visitor.visit(statement)
    return visitor.names


def test_declared_direct_env_readers_are_resolved_and_receiver_owned() -> None:
    direct_readers = SNAPSHOT["direct_readers"]
    assert len(direct_readers) == 10
    for item in direct_readers:
        module_path, qualname = _reader_source_and_qualname(item["reader"])
        assert module_path.is_file()
        assert qualname
        assert item["env"] in _reader_env_names(item["reader"])


@pytest.mark.parametrize("env_name,attr", sorted(SNAPSHOT["str_env"].items()))
def test_every_string_mapping_applies_its_sentinel(
    monkeypatch, tmp_path, env_name, attr
) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setenv(env_name, "contract-sentinel")
    config_env.apply_env(cfg)
    expected = (
        Path("contract-sentinel")
        if attr in PATH_STR_FIELDS
        else "contract-sentinel"
    )
    assert getattr(cfg, attr) == expected


@pytest.mark.parametrize(
    "env_name,spec", sorted(SNAPSHOT["int_env"].items())
)
def test_every_integer_mapping_handles_valid_invalid_and_clamped_values(
    monkeypatch, tmp_path, env_name, spec
) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setenv(env_name, "7")
    config_env.apply_env(cfg)
    assert getattr(cfg, spec["attr"]) == _clamp(7, spec["min"], spec["max"])

    monkeypatch.setenv(env_name, "not-an-integer")
    fallback = _cfg(tmp_path)
    original = getattr(fallback, spec["attr"])
    config_env.apply_env(fallback)
    assert getattr(fallback, spec["attr"]) == original

    if spec["min"] is not None:
        monkeypatch.setenv(env_name, str(spec["min"] - 100))
        below = _cfg(tmp_path)
        config_env.apply_env(below)
        assert getattr(below, spec["attr"]) == spec["min"]
    if spec["max"] is not None:
        monkeypatch.setenv(env_name, str(spec["max"] + 100))
        above = _cfg(tmp_path)
        config_env.apply_env(above)
        assert getattr(above, spec["attr"]) == spec["max"]


@pytest.mark.parametrize(
    "env_name,spec", sorted(SNAPSHOT["float_env"].items())
)
def test_every_float_mapping_handles_valid_invalid_and_clamped_values(
    monkeypatch, tmp_path, env_name, spec
) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setenv(env_name, "1.25")
    config_env.apply_env(cfg)
    assert getattr(cfg, spec["attr"]) == pytest.approx(
        _clamp(1.25, spec["min"], spec["max"])
    )

    monkeypatch.setenv(env_name, "not-a-float")
    fallback = _cfg(tmp_path)
    original = getattr(fallback, spec["attr"])
    config_env.apply_env(fallback)
    assert getattr(fallback, spec["attr"]) == original

    if spec["min"] is not None:
        monkeypatch.setenv(env_name, str(spec["min"] - 100.5))
        below = _cfg(tmp_path)
        config_env.apply_env(below)
        assert getattr(below, spec["attr"]) == pytest.approx(spec["min"])
    if spec["max"] is not None:
        monkeypatch.setenv(env_name, str(spec["max"] + 100.5))
        above = _cfg(tmp_path)
        config_env.apply_env(above)
        assert getattr(above, spec["attr"]) == pytest.approx(spec["max"])


@pytest.mark.parametrize("env_name,attr", sorted(SNAPSHOT["bool_env"].items()))
def test_every_boolean_mapping_covers_true_and_false(
    monkeypatch, tmp_path, env_name, attr
) -> None:
    monkeypatch.setenv(env_name, "YES")
    enabled = _cfg(tmp_path)
    config_env.apply_env(enabled)
    assert getattr(enabled, attr) is True

    monkeypatch.setenv(env_name, "off")
    disabled = _cfg(tmp_path)
    config_env.apply_env(disabled)
    assert getattr(disabled, attr) is False


def test_api_key_explicit_and_auto_paths_do_not_touch_disk(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("KOKORO_API_KEY", "contract-explicit-key")
    explicit = _cfg(tmp_path)
    config_env.apply_env(explicit)
    assert explicit.api_key == "contract-explicit-key"
    assert explicit.api_key_auto_generated is False

    monkeypatch.setenv("KOKORO_API_KEY", "auto")
    monkeypatch.setattr(
        config_env, "load_or_generate_api_key", lambda _cfg: "mock-generated-key"
    )
    automatic = _cfg(tmp_path)
    config_env.apply_env(automatic)
    assert automatic.api_key == "mock-generated-key"
    assert automatic.api_key_auto_generated is True
    assert not list(tmp_path.rglob(".angevoice-api-key"))


def test_auto_api_key_boolean_true_generates_once_without_writing_disk(
    monkeypatch, tmp_path
) -> None:
    calls = []

    def generate_once(cfg):
        calls.append(cfg)
        return "mock-auto-key"

    monkeypatch.setenv("KOKORO_AUTO_API_KEY", "true")
    monkeypatch.setattr(config_env, "load_or_generate_api_key", generate_once)
    cfg = _cfg(tmp_path)
    config_env.apply_env(cfg)
    assert cfg.api_key == "mock-auto-key"
    assert cfg.api_key_auto_generated is True
    assert calls == [cfg]
    assert not list(tmp_path.rglob("*"))


def test_auto_api_key_boolean_false_keeps_key_empty_without_generator(
    monkeypatch, tmp_path
) -> None:
    calls = []
    monkeypatch.setenv("KOKORO_AUTO_API_KEY", "off")
    monkeypatch.setattr(
        config_env,
        "load_or_generate_api_key",
        lambda _cfg: calls.append("unexpected") or "unexpected-key",
    )
    cfg = _cfg(tmp_path)
    config_env.apply_env(cfg)
    assert cfg.api_key is None
    assert cfg.api_key_auto_generated is False
    assert calls == []


def test_list_special_cases_preserve_split_and_normalization(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "KOKORO_CORS_ORIGINS", " https://a.invalid, ,https://b.invalid "
    )
    monkeypatch.setenv("ANGEVOICE_ENABLED_MODELS", " KOKORO, MOSS-NANO-CPU, ")
    cfg = _cfg(tmp_path)
    config_env.apply_env(cfg)
    assert cfg.cors_origins == ["https://a.invalid", "https://b.invalid"]
    assert cfg.enabled_models == ["kokoro", "moss-nano-cpu"]


@pytest.mark.parametrize(
    "env_name,attr",
    [
        ("MOSS_MODEL_DIR", "moss_model_dir"),
        ("MOSS_AUDIO_TOKENIZER_MODEL_DIR", "moss_audio_tokenizer_model_dir"),
        ("MOSS_TTS_NANO_PATH", "moss_repo_path"),
        ("MOSS_PROMPT_AUDIO_PATH", "moss_prompt_audio_path"),
        ("ZIPVOICE_PROFILES_DIR", "zipvoice_profiles_dir"),
        ("ZIPVOICE_REPO_PATH", "zipvoice_repo_path"),
    ],
)
def test_path_special_cases_expand_to_path(
    monkeypatch, tmp_path, env_name, attr
) -> None:
    monkeypatch.setenv(env_name, "contract-path")
    cfg = _cfg(tmp_path)
    config_env.apply_env(cfg)
    assert getattr(cfg, attr) == Path("contract-path")


def test_zipvoice_root_derives_children_then_explicit_dirs_override(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ZIPVOICE_MODEL_ROOT", "zip-root")
    derived = _cfg(tmp_path)
    config_env.apply_env(derived)
    assert derived.zipvoice_model_root == Path("zip-root")
    assert derived.zipvoice_distill_dir == Path("zip-root/zipvoice_distill")
    assert derived.zipvoice_vocos_dir == Path("zip-root/vocos-mel-24khz")

    monkeypatch.setenv("ZIPVOICE_DISTILL_DIR", "custom-distill")
    monkeypatch.setenv("ZIPVOICE_VOCOS_DIR", "custom-vocos")
    overridden = _cfg(tmp_path)
    config_env.apply_env(overridden)
    assert overridden.zipvoice_distill_dir == Path("custom-distill")
    assert overridden.zipvoice_vocos_dir == Path("custom-vocos")
