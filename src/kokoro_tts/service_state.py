"""AngeVoice 运行状态与共用服务工具。"""

import asyncio
import os
import threading
import time
from collections import OrderedDict
from typing import Callable

from .config import TTSConfig
from .engine import TTSEngine
from .engine_manager import EngineManager
from .engines.parameters import EngineParameterSchema
from .latency_tracker import LatencyTracker
from .resources import RuntimeResourceService
from .services import StreamingService, SynthesisService, VoiceProfileService
from .services.state_parts.cache_state import CacheStateMixin
from .services.state_parts.model_registry import ModelRegistryMixin
from .services.state_parts.request_registry import RequestRegistryMixin, normalize_client_request_id
from .services.state_parts.resource_state import ResourceStateMixin
from .services.state_parts.stats_state import StatsStateMixin


class ServiceState(
    StatsStateMixin,
    RequestRegistryMixin,
    CacheStateMixin,
    ModelRegistryMixin,
    ResourceStateMixin,
):
    """单个 AngeVoice FastAPI 应用的可变运行状态。"""

    def __init__(self, cfg: TTSConfig, eng: TTSEngine | None = None, model_manager: EngineManager | None = None):
        self.cfg = cfg
        self.model_manager = model_manager or EngineManager(cfg, initial_engine=eng)
        self.parameter_schema = getattr(self.model_manager.registry, "parameter_schema", EngineParameterSchema())
        self.voice_profiles = VoiceProfileService(cfg)
        self.zipvoice_profiles = self.voice_profiles.store_for("zipvoice")  # legacy compatibility alias
        self.model_manager.bind_voice_profile_service(self.voice_profiles)
        self.eng = eng or self.model_manager.get_engine(self.model_manager.current_model_id, load=False)
        self.tts_semaphore = asyncio.Semaphore(max(1, int(cfg.max_concurrent_requests)))
        self._websocket_connections = 0
        self._websocket_connection_lock = asyncio.Lock()
        self._idle_restart_lock = threading.Lock()
        self._idle_restart_scheduled = False
        self._last_idle_restart_plan_at = 0.0
        self._idle_restart_reason = ""
        self._idle_restart_models: list[str] = []
        self._process_exit = os._exit
        self._timer_factory = threading.Timer
        self.tts_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._cache_bytes = 0
        self.cache_lock = threading.Lock()
        self.active_requests: dict[str, dict] = {}
        self.cancelled_requests: set[str] = set()
        self.stats_lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.request_lock = threading.Lock()
        self.latency_tracker = LatencyTracker()
        self.stats = {
            "requests_total": 0,
            "requests_ok": 0,
            "requests_error": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_skips": 0,
            "characters_total": 0,
            "audio_bytes_total": 0,
            "synthesis_seconds_total": 0.0,
            "ws_cancelled_total": 0,
            "ws_connections_rejected_total": 0,
            "ws_connections_peak": 0,
            "outputs_saved_total": 0,
            "started_at": time.time(),
        }
        self.runtime_resources = RuntimeResourceService(self)
        self.synthesis = SynthesisService(self)
        self.streaming = StreamingService(self)
        self.model_manager.set_idle_unload_callback(self.handle_idle_unload_completed)

    def as_service_extras_kwargs(self) -> dict[str, Callable | object]:
        return {
            "tts_cache": self.tts_cache,
            "active_requests": self.active_requests,
            "stats": self.stats,
            "synthesize_threaded": self.synthesize_response_threaded,
            "new_request_id": self.new_request_id,
            "normalize_response_format": self.normalize_response_format,
            "mark_request": self.mark_request,
            "finish_request": self.finish_request,
            "increment_stat": self.inc_stat,
            "cache_clear": self.cache_clear,
            "cache_size": self.cache_size,
        }
