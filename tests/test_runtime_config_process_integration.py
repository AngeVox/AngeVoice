"""运行时配置在两个真实 spawn 进程中的写入串行化。"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.integration


def _save_config_in_child(path, changes, entered, release, ready, write_entered, pause):
    from kokoro_tts.admin_config import schema

    original_write = schema._atomic_write_json

    def observed_write(target, payload):
        if pause:
            entered.set()
            assert release.wait(15), "首个写入进程未获准继续"
        else:
            write_entered.set()
        original_write(target, payload)

    schema._atomic_write_json = observed_write
    if ready is not None:
        ready.set()
    schema.save_runtime_config_values(SimpleNamespace(runtime_config_file=path), changes)


def test_two_spawned_writers_merge_distinct_fields_without_lost_update(tmp_path):
    context = mp.get_context("spawn")
    path = tmp_path / "runtime-config.json"
    first_entered, release = context.Event(), context.Event()
    second_ready, second_write_entered = context.Event(), context.Event()
    first = context.Process(
        target=_save_config_in_child,
        args=(path, {"cache_max_items": 12}, first_entered, release, None, None, True),
    )
    second = context.Process(
        target=_save_config_in_child,
        args=(path, {"cache_max_bytes": 1024}, None, None, second_ready, second_write_entered, False),
    )
    try:
        first.start()
        assert first_entered.wait(15), "首个写入进程未进入原子发布"
        second.start()
        assert second_ready.wait(15), "第二个写入进程未启动"
        assert not second_write_entered.wait(2), "第二个进程绕过了配置文件锁"
    finally:
        release.set()
        for process in (first, second):
            if process.pid is None:
                continue
            process.join(timeout=15)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert first.exitcode == second.exitcode == 0
    assert json.loads(path.read_text(encoding="utf-8"))["values"] == {
        "cache_max_items": 12,
        "cache_max_bytes": 1024,
    }
