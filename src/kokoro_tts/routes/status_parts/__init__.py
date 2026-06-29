"""Composable status router parts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import Request

from ...service_state import ServiceState


@dataclass(frozen=True)
class StatusRouteContext:
    state: ServiceState
    cfg: Any
    verify_api_key: Callable[[Request], Awaitable[None]]
    verify_admin: Callable
    templates: Any = None

