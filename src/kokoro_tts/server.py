"""AngeVoice FastAPI application factory.

The historical public API remains ``kokoro_tts.server.create_app`` and
``kokoro_tts.server.run_server``. Route implementations live under
``kokoro_tts.routes`` so this file stays focused on application assembly.
"""

import logging
from pathlib import Path
from typing import Optional

from .config import TTSConfig, load_config
from .engine import TTSEngine
from .routes import create_audio_router, create_status_router, create_ws_router
from .security import make_verify_api_key
from .service_state import ServiceState

logger = logging.getLogger(__name__)


def create_app(config: Optional[TTSConfig] = None, engine: Optional[TTSEngine] = None):
    """Create the AngeVoice FastAPI app with delayed heavyweight imports."""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    cfg = config or load_config()
    eng = engine or TTSEngine(cfg)
    state = ServiceState(cfg, eng)
    verify_api_key = make_verify_api_key(cfg)

    @asynccontextmanager
    async def lifespan(app):
        eng.load()
        logger.info("AngeVoice service started (device=%s)", eng._device)
        yield

    app = FastAPI(
        title="AngeVoice",
        description="Lightweight Chinese TTS service built on Kokoro v1.1 model",
        version="2.5.0",
        lifespan=lifespan,
    )
    app.state.angevoice = state

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    register_extra_routes(app=app, cfg=cfg, eng=eng, verify_api_key=verify_api_key, **state.as_service_extras_kwargs())
    return app


def run_server(config: Optional[TTSConfig] = None):
    import uvicorn

    cfg = config or load_config()
    eng = TTSEngine(cfg)
    app = create_app(config=cfg, engine=eng)
    logger.info("Starting AngeVoice service: %s:%s", cfg.host, cfg.port)
    uvicorn.run(app, host=cfg.host, port=cfg.port, workers=cfg.workers)
