"""Compatibility facade for admin runtime configuration schema.

New code should import from :mod:`kokoro_tts.admin_config`; this module keeps
the historical import path stable for existing callers and tests.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .admin_config.schema import (
    ADMIN_CONFIG_FIELDS,
    ADMIN_CONFIG_GROUPS,
    ADMIN_CONFIG_PROFILES,
    AdminConfigField,
    apply_admin_config_values,
    config_values,
    delete_runtime_config,
    export_env_patch,
    legacy_runtime_config_path,
    load_runtime_config,
    profile_values,
    read_runtime_config_values,
    runtime_config_info,
    runtime_config_path,
    save_runtime_config_values,
    schema_payload,
    validate_admin_config_values,
)

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:  # pragma: no cover - Docker/fnOS deployments provide fcntl.
    fcntl = None

__all__ = [
    "ADMIN_CONFIG_FIELDS",
    "ADMIN_CONFIG_GROUPS",
    "ADMIN_CONFIG_PROFILES",
    "AdminConfigField",
    "apply_admin_config_values",
    "config_values",
    "delete_runtime_config",
    "export_env_patch",
    "legacy_runtime_config_path",
    "load_runtime_config",
    "profile_values",
    "read_runtime_config_values",
    "runtime_config_info",
    "runtime_config_path",
    "save_runtime_config_values",
    "schema_payload",
    "validate_admin_config_values",
]
