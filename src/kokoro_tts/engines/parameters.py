"""Dynamic engine parameter schema and backward-compatible value parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import HTTPException


@dataclass(frozen=True)
class EngineParameter:
    key: str
    value_type: str
    label: str
    description: str
    default: Any = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    advanced: bool = True

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "key": self.key,
            "type": self.value_type,
            "label": self.label,
            "description": self.description,
            "default": self.default,
            "advanced": self.advanced,
        }
        if self.minimum is not None:
            payload["minimum"] = self.minimum
        if self.maximum is not None:
            payload["maximum"] = self.maximum
        return payload


class EngineParameterSchema:
    """Single registry of public per-engine generation controls.

    Routes submit a generic mapping and no longer validate parameters with
    model-specific helper functions.  Legacy field names remain the public keys
    for legacy compatibility.
    """

    def __init__(self):
        self._schemas: dict[str, tuple[EngineParameter, ...]] = {
            "zipvoice": (
                EngineParameter(
                    "zipvoice_num_steps", "integer", "采样步数",
                    "ZipVoice 推理采样步数。", default=8, minimum=1, maximum=32,
                ),
                EngineParameter(
                    "zipvoice_remove_long_sil", "boolean", "移除长静音",
                    "可选移除生成音频中的长内部静音。", default=False,
                ),
            ),
        }

    def schema_for(self, model_id: str) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self._schemas.get(str(model_id or ""), ())]

    def schema_catalog(self) -> dict[str, list[dict[str, Any]]]:
        return {model_id: self.schema_for(model_id) for model_id in self._schemas}

    @staticmethod
    def _lookup(source: Mapping[str, Any] | Any, key: str) -> Any:
        if hasattr(source, "get"):
            return source.get(key)
        return None

    @staticmethod
    def _parse_bool(value: Any, key: str) -> bool | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise HTTPException(status_code=400, detail=f"{key} 必须为布尔值")

    def parse(self, model_id: str, source: Mapping[str, Any] | Any | None = None, *, supplied: Mapping[str, Any] | None = None) -> dict[str, Any]:
        available = {item.key: item for item in self._schemas.get(str(model_id or ""), ())}
        if not available:
            return {}
        raw: dict[str, Any] = {}
        # Parse legacy top-level fields first, then let the generic
        # engine_params payload win when both are supplied during migration.
        if source is not None:
            for key in available:
                value = self._lookup(source, key)
                if value not in {None, ""}:
                    raw[key] = value
        if supplied:
            raw.update({key: value for key, value in dict(supplied).items() if value not in {None, ""}})
        parsed: dict[str, Any] = {}
        for key, value in raw.items():
            spec = available.get(key)
            if spec is None:
                continue
            if spec.value_type == "boolean":
                parsed_value = self._parse_bool(value, key)
                if parsed_value is not None:
                    parsed[key] = parsed_value
                continue
            if spec.value_type == "integer":
                try:
                    parsed_value = int(value)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=f"{key} 必须为整数") from exc
                if spec.minimum is not None and parsed_value < spec.minimum or spec.maximum is not None and parsed_value > spec.maximum:
                    raise HTTPException(status_code=400, detail=f"{key} 必须在 {spec.minimum:g} 到 {spec.maximum:g} 之间")
                parsed[key] = parsed_value
        return parsed
