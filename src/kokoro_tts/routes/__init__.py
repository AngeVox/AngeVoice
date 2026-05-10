"""AngeVoice FastAPI 路由工厂。"""

from .admin import create_admin_router
from .audio import create_audio_router
from .status import create_status_router
from .ws import create_ws_router

__all__ = ["create_admin_router", "create_audio_router", "create_status_router", "create_ws_router"]
