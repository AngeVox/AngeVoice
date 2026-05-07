"""AngeVoice FastAPI application factory.

The historical public API remains ``kokoro_tts.server.create_app`` and
``kokoro_tts.server.run_server``. Route implementations live under
``kokoro_tts.routes`` so this file stays focused on application assembly.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from .config import TTSConfig, load_config
from .engine import TTSEngine
from .engine_manager import EngineManager
from .routes import create_audio_router, create_status_router, create_ws_router
from .security import make_verify_api_key
from .service_state import ServiceState

logger = logging.getLogger(__name__)


_WORKER_ENV_EXPORTS = {
    "KOKORO_MODEL_DIR": "model_path",
    "KOKORO_DEVICE": "device",
    "KOKORO_DEFAULT_VOICE": "default_voice",
    "KOKORO_STREAM_FORMAT": "stream_format",
    "KOKORO_MP3_BITRATE": "mp3_bitrate",
    "KOKORO_MAX_CONCURRENT_REQUESTS": "max_concurrent_requests",
    "KOKORO_MAX_TEXT_LENGTH": "max_text_length",
    "KOKORO_SEGMENT_LENGTH": "segment_length",
    "KOKORO_CACHE_MAX_ITEMS": "cache_max_items",
    "KOKORO_BATCH_MAX_ITEMS": "batch_max_items",
    "KOKORO_BATCH_CONCURRENCY": "batch_concurrency",
    "KOKORO_DEFAULT_SPEED": "default_speed",
    "KOKORO_REQUEST_TIMEOUT_SECONDS": "request_timeout_seconds",
    "KOKORO_STREAM_BINARY_ENABLED": "stream_binary_enabled",
    "KOKORO_CACHE_ENABLED": "cache_enabled",
    "KOKORO_QUEUE_STATUS_ENABLED": "queue_status_enabled",
    "KOKORO_METRICS_ENABLED": "metrics_enabled",
    "KOKORO_BATCH_ENABLED": "batch_enabled",
    "KOKORO_ADMIN_ENABLED": "admin_enabled",
    "KOKORO_VOICE_UPLOAD_ENABLED": "voice_upload_enabled",
    "KOKORO_MP3_ENABLED": "mp3_enabled",
    "ANGEVOICE_ENABLED_MODELS": "enabled_models",
    "ANGEVOICE_DEFAULT_MODEL": "default_model",
    "ANGEVOICE_MODEL_SWITCH_ENABLED": "model_switch_enabled",
    "ANGEVOICE_MODEL_UNLOAD_ON_SWITCH": "model_unload_on_switch",
    "ANGEVOICE_MODEL_SWITCH_TIMEOUT_SECONDS": "model_switch_timeout_seconds",
    "ANGEVOICE_OUTPUT_DIR": "output_dir",
    "ANGEVOICE_SAVE_OUTPUTS": "save_outputs",
    "ANGEVOICE_OUTPUT_MAX_FILES": "output_max_files",
    "MOSS_EXECUTION_PROVIDER": "moss_execution_provider",
    "MOSS_CPU_THREADS": "moss_cpu_threads",
    "MOSS_DEFAULT_VOICE": "moss_default_voice",
    "MOSS_PROMPT_UPLOAD_MAX_BYTES": "moss_prompt_upload_max_bytes",
    "MOSS_MAX_NEW_FRAMES": "moss_max_new_frames",
    "MOSS_VOICE_CLONE_MAX_TEXT_TOKENS": "moss_voice_clone_max_text_tokens",
    "MOSS_SAMPLE_MODE": "moss_sample_mode",
    "MOSS_CUDA_ENABLED": "moss_cuda_enabled",
    "MOSS_ENABLE_WETEXT_PROCESSING": "moss_enable_wetext_processing",
    "MOSS_ENABLE_NORMALIZE_TTS_TEXT": "moss_enable_normalize_tts_text",
    "MOSS_APPLY_ANGEVOICE_RULES": "moss_apply_angevoice_rules",
    "MOSS_REALTIME_STREAMING_DECODE": "moss_realtime_streaming_decode",
    "MOSS_CUDA_SELF_TEST_ENABLED": "moss_cuda_self_test_enabled",
    "MOSS_AUTO_FALLBACK_CPU": "moss_auto_fallback_cpu",
    "MOSS_QUALITY_GATE_ENABLED": "moss_quality_gate_enabled",
    "MOSS_MAX_CLIP_RATIO": "moss_max_clip_ratio",
}


def _stringify_env_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def _export_config_for_workers(cfg: TTSConfig) -> None:
    for env_name, attr in _WORKER_ENV_EXPORTS.items():
        os.environ[env_name] = _stringify_env_value(getattr(cfg, attr))
    os.environ["KOKORO_CORS_ORIGINS"] = ",".join(cfg.cors_origins)
    if cfg.api_key:
        os.environ["KOKORO_API_KEY"] = cfg.api_key
    if cfg.moss_model_dir:
        os.environ["MOSS_MODEL_DIR"] = str(cfg.moss_model_dir)
    if cfg.moss_repo_path:
        os.environ["MOSS_TTS_NANO_PATH"] = str(cfg.moss_repo_path)
    if cfg.moss_prompt_audio_path:
        os.environ["MOSS_PROMPT_AUDIO_PATH"] = str(cfg.moss_prompt_audio_path)


def create_app(config: Optional[TTSConfig] = None, engine: Optional[TTSEngine] = None):
    """Create the AngeVoice FastAPI app with delayed heavyweight imports."""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    cfg = config or load_config()
    cfg.validate_security()
    manager = EngineManager(cfg, initial_engine=engine)
    state = ServiceState(cfg, engine, model_manager=manager)
    verify_api_key = make_verify_api_key(cfg)

    @asynccontextmanager
    async def lifespan(app):
        state.model_manager.switch_model(cfg.default_model, load=True)
        current = state.model_manager.current_snapshot()
        logger.info("AngeVoice service started (model=%s device=%s)", current.get("id"), current.get("device"))
        yield

    app = FastAPI(
        title="AngeVoice",
        description="Lightweight local TTS service with selectable model engines",
        version="2.6.1",
        lifespan=lifespan,
    )
    app.state.angevoice = state

    allow_credentials = "*" not in cfg.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        try:
            from fastapi.staticfiles import StaticFiles
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        except Exception:
            logger.debug("Static file serving is unavailable", exc_info=True)

    templates = None
    try:
        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    except Exception:
        logger.debug("Jinja2 templates are unavailable", exc_info=True)

    app.include_router(create_status_router(state, verify_api_key, templates=templates))
    app.include_router(create_audio_router(state, verify_api_key))
    app.include_router(create_ws_router(state))

    from .service_extras import register_extra_routes
    register_extra_routes(app=app, cfg=cfg, eng=state.eng, verify_api_key=verify_api_key, **state.as_service_extras_kwargs())
    return app


def run_server(config: Optional[TTSConfig] = None):
    import uvicorn

    cfg = config or load_config()
    logger.info("Starting AngeVoice service: %s:%s", cfg.host, cfg.port)
    if cfg.workers > 1:
        _export_config_for_workers(cfg)
        uvicorn.run(
            "kokoro_tts.server:create_app",
            factory=True,
            host=cfg.host,
            port=cfg.port,
            workers=cfg.workers,
        )
        return

    app = create_app(config=cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, workers=1)
