"""Runtime factories for killable model workers.

Each factory constructs an *in-process* runtime inside the child process.  Adding
another isolated engine should register one factory here and expose its product
adapter via the normal engine registry; the API process lifecycle client remains
unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

WorkerFactory = Callable[[object, str | None], object]


def _kokoro_factory(config, _requested_provider: str | None):
    from ..engine import TTSEngine

    return TTSEngine(config)


def _zipvoice_factory(config, requested_provider: str | None):
    from ..zipvoice.engine import ZipVoiceEngine

    return ZipVoiceEngine(config, requested_provider=requested_provider, process_isolation=False)


WORKER_ENGINE_FACTORIES: dict[str, WorkerFactory] = {
    "kokoro": _kokoro_factory,
    "zipvoice": _zipvoice_factory,
}


def supported_worker_engines() -> tuple[str, ...]:
    return tuple(sorted(WORKER_ENGINE_FACTORIES))


def create_worker_engine(config, engine_id: str, requested_provider: str | None = None):
    try:
        factory = WORKER_ENGINE_FACTORIES[str(engine_id)]
    except KeyError as exc:
        raise ValueError(f"Unsupported generic worker engine: {engine_id}") from exc
    return factory(config, requested_provider)
