from pathlib import Path

from kokoro_tts.admin_config_schema import ADMIN_CONFIG_FIELDS, validate_admin_config_values
from kokoro_tts.config import TTSConfig
from kokoro_tts.engine_manager import EngineManager
from kokoro_tts.kokoro_assets import is_valid_kokoro_config_file


def test_mixed_english_policy_is_choice_and_validated():
    field = ADMIN_CONFIG_FIELDS["moss_mixed_english_policy"]
    assert field.type == "choice"
    validated = validate_admin_config_values({"moss_mixed_english_policy": "preserve"})
    assert validated["moss_mixed_english_policy"] == "preserve"


def test_compact_json_config_not_misclassified(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"sample_rate":24000,"foo":"bar"}', encoding="utf-8")
    assert is_valid_kokoro_config_file(cfg_file) is True


def test_text_rules_false_not_reported_as_enabled():
    cfg = TTSConfig(moss_apply_angevoice_rules="false", enabled_models=["moss-nano-cpu"], default_model="moss-nano-cpu")
    manager = EngineManager(cfg)
    try:
        snap = manager.current_snapshot()
        assert snap["text_rules_enabled"] is False
    finally:
        manager.stop_idle_timer()
