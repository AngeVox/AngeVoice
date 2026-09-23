"""真实 spawn 的关闭诊断；替身不代表模型推理或资源释放。"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from kokoro_tts.workers import EngineProcessClient, EngineWorkerSpec


pytestmark = pytest.mark.integration


class _ShutdownEngine:
    def __init__(self, fail_unload: bool):
        self.fail_unload = fail_unload

    def load(self):
        pass

    def metadata(self):
        return {"pid": os.getpid()}

    def unload(self):
        if self.fail_unload:
            raise RuntimeError("secret=synthetic-unload-token")


def _shutdown_factory(config, _provider):
    return _ShutdownEngine(config.fail_unload)


def test_shutdown_failure_is_visible_and_next_spawn_clears_it():
    config = SimpleNamespace(fail_unload=True, engine_process_kill_grace_seconds=3.0)
    client = EngineProcessClient(
        config=config, spec=EngineWorkerSpec("shutdown-recording", _shutdown_factory)
    )
    try:
        first_pid = client.load(timeout=15)["pid"]
        client.close()
        assert not client.alive
        assert "engine_runtime_failed" in client.last_exit_reason
        assert "退出码：" in client.last_exit_reason
        assert "secret=" not in client.last_exit_reason

        config.fail_unload = False
        second_pid = client.load(timeout=15)["pid"]
        assert second_pid != first_pid
        assert client.last_exit_reason == ""
        client.close()
        assert client.last_exit_reason == ""
    finally:
        client.close(kill=True)
