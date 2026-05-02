"""Kokoro TTS HTTP 服务

提供 OpenAI 兼容的 TTS API 和 Web UI。
FastAPI 在启动时才导入。
"""

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

from .config import TTSConfig, load_config
from .engine import TTSEngine

logger = logging.getLogger(__name__)


def create_app(config: Optional[TTSConfig] = None, engine: Optional[TTSEngine] = None):
    """创建 FastAPI 应用（延迟导入 FastAPI）

    可传入自定义 config 和 engine，用于嵌入场景。
    """
    from fastapi import FastAPI, Request, HTTPException, Depends
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, StreamingResponse
    from pydantic import BaseModel, Field

    cfg = config or load_config()
    eng = engine or TTSEngine(cfg)

    app = FastAPI(
        title="Kokoro TTS",
        description="轻量级中文 TTS 服务 (Kokoro v1.1)",
        version="2.0.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 模板（可选）
    templates = None
    try:
        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    except Exception:
        pass

    # 请求模型
    class TTSRequest(BaseModel):
        input: str = Field(..., description="要合成的文本", alias="text")
        voice: str = Field(default="zm_010", description="音色名称")
        speed: float = Field(default=1.0, ge=0.5, le=2.0, description="语速")
        response_format: str = Field(default="wav", description="音频格式")

        class Config:
            populate_by_name = True

    # API Key 验证
    async def verify_api_key(request: Request):
        if cfg.api_key:
            auth = request.headers.get("Authorization", "")
            token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
            if token != cfg.api_key:
                raise HTTPException(status_code=401, detail="Invalid API key")

    # ── 路由 ──

    @app.on_event("startup")
    async def startup():
        eng.load()
        logger.info(f"Kokoro TTS 服务启动 (device={eng._device})")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if templates:
            voices = cfg.get_voices()
            return templates.TemplateResponse("index.html", {"request": request, "voices": voices})
        return HTMLResponse("<h1>Kokoro TTS</h1><p>API 文档: <a href='/docs'>/docs</a></p>")

    @app.get("/health")
    async def health():
        return {
            "status": "ok" if eng.is_loaded else "loading",
            "device": eng._device,
            "voices": cfg.get_voices(),
        }

    @app.get("/v1/audio/voices")
    async def list_voices():
        return {"voices": cfg.get_voices()}

    @app.post("/v1/audio/speech")
    async def openai_tts(req: TTSRequest, _=Depends(verify_api_key)):
        """OpenAI 兼容 TTS 接口"""
        try:
            audio_bytes = eng.synthesize(
                text=req.input,
                voice=req.voice,
                speed=req.speed,
            )
            media_type = "audio/wav" if req.response_format == "wav" else "audio/mpeg"
            return StreamingResponse(BytesIO(audio_bytes), media_type=media_type)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            raise HTTPException(status_code=500, detail=f"合成失败: {e}")

    @app.post("/api/tts")
    async def tts_post(request: Request, _=Depends(verify_api_key)):
        """兼容旧版接口（支持 JSON 和 Form）"""
        content_type = request.headers.get("Content-Type", "")

        if "application/json" in content_type:
            data = await request.json()
            text = data.get("text") or data.get("input") or data.get("prompt")
            voice = data.get("voice") or data.get("speaker") or cfg.default_voice
            speed = data.get("speed", data.get("rate", cfg.default_speed))
        else:
            form = await request.form()
            text = form.get("text")
            voice = form.get("voice", cfg.default_voice)
            speed = float(form.get("speed", cfg.default_speed))

        if not text:
            raise HTTPException(status_code=400, detail="缺少 text 参数")

        try:
            audio_bytes = eng.synthesize(text=text, voice=voice, speed=speed)
            return StreamingResponse(BytesIO(audio_bytes), media_type="audio/wav")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            raise HTTPException(status_code=500, detail=f"合成失败: {e}")

    @app.get("/api/tts")
    async def tts_get(text: str, voice: str = "zm_010", speed: float = 1.0, _=Depends(verify_api_key)):
        """GET 方式调用"""
        if not text:
            raise HTTPException(status_code=400, detail="缺少 text 参数")
        try:
            audio_bytes = eng.synthesize(text=text, voice=voice, speed=speed)
            return StreamingResponse(BytesIO(audio_bytes), media_type="audio/wav")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"合成失败: {e}")

    return app


def run_server(config: Optional[TTSConfig] = None):
    """启动 HTTP 服务"""
    import uvicorn

    cfg = config or load_config()
    app = create_app(config=cfg)
    logger.info(f"启动服务: {cfg.host}:{cfg.port}")
    uvicorn.run(app, host=cfg.host, port=cfg.port, workers=cfg.workers)
