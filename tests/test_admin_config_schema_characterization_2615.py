from __future__ import annotations

from kokoro_tts.admin_config_schema import schema_payload


def _fields_by_key() -> dict[str, dict]:
    return {field["key"]: field for field in schema_payload()["fields"]}


def test_2615_admin_schema_groups_and_field_count_are_stable():
    schema = schema_payload()

    assert [group["key"] for group in schema["groups"]] == [
        "kokoro",
        "moss",
        "zipvoice",
        "text",
        "service",
        "audio",
        "security",
    ]
    assert len(schema["fields"]) == 81
    assert {profile["key"] for profile in schema["profiles"]} >= {
        "nas_stable",
        "low_latency",
        "balanced",
        "long_narration",
    }


def test_2615_admin_schema_text_frontend_fields_are_characterized():
    fields = _fields_by_key()

    assert fields["angevoice_tn_engine"] == {
        "key": "angevoice_tn_engine",
        "env": "ANGEVOICE_TN_ENGINE",
        "label": "默认文本处理",
        "group": "text",
        "type": "choice",
        "default": "wetext",
        "min": None,
        "max": None,
        "step": None,
        "choices": [
            {"value": "wetext", "label": "标准：文本规范化"},
            {"value": "legacy", "label": "保守：AngeVoice 2.6.613"},
            {"value": "off", "label": "关闭：仅基础清理"},
        ],
        "restart": False,
        "rebuild_moss": False,
        "advanced": False,
        "help": "使用 wetext runtime 进行数字、日期、时间等文本规范化；技术字符串会先做保护。Studio 可按单次请求覆盖此默认值。",
    }

    assert fields["text_single_newline_policy"]["choices"] == [
        {"value": "auto", "label": "智能合并"},
        {"value": "preserve", "label": "保留停顿"},
        {"value": "space", "label": "当作空格"},
    ]
    assert fields["moss_apply_angevoice_rules"]["choices"] == [
        {"value": "auto", "label": "智能处理"},
        {"value": "true", "label": "完整中文规则"},
        {"value": "false", "label": "仅温和清理"},
    ]


def test_2615_admin_schema_byte_fields_store_bytes_but_explain_mib_ui():
    fields = _fields_by_key()

    expected = {
        "cache_max_bytes": {
            "group": "service",
            "default": 536870912,
            "step": 1048576,
            "help": "前端以 MiB 显示和编辑；0 表示不限制，默认约 512 MiB。",
        },
        "cache_skip_audio_over_bytes": {
            "group": "service",
            "default": 20971520,
            "step": 1048576,
            "help": "前端以 MiB 显示和编辑；超过该大小的音频不写入缓存，0 表示关闭。",
        },
        "websocket_max_message_bytes": {
            "group": "security",
            "default": 33554432,
            "step": 1024,
            "help": "前端以 MiB 显示和编辑；限制首包/控制消息大小。32 MiB 可容纳约 20 MiB 参考音频的 base64 JSON。",
        },
    }
    for key, snapshot in expected.items():
        field = fields[key]
        assert field["type"] == "int"
        for snapshot_key, snapshot_value in snapshot.items():
            assert field[snapshot_key] == snapshot_value

