"""Behavior and mapping contracts for config_env 2.6.7."""

from __future__ import annotations

import ast
import dataclasses
import json
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
    declaration_mapping = [
        value
        for key, value in zip(int_env.keys, int_env.values)
        if key is None and isinstance(value, ast.DictComp)
    ]
    assert len(declaration_mapping) == 1
    mapping = declaration_mapping[0]
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
