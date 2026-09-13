"""动态引擎参数模式和向后兼容的值解析。"""

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
    """公共每引擎生成控件的单一注册表。

    路由提交通用映射，不再使用特定模型的辅助函数验证参数。
    旧版字段名保留为公共键以保持向后兼容。
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

    @staticmethod
    def _parse_integer(value: Any, spec: EngineParameter) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise HTTPException(status_code=400, detail=f"{spec.key} 必须为整数") from exc
        below = spec.minimum is not None and parsed < spec.minimum
        above = spec.maximum is not None and parsed > spec.maximum
        if below or above:
            if spec.minimum is not None and spec.maximum is not None:
                detail = f"{spec.key} 必须在 {spec.minimum:g} 到 {spec.maximum:g} 之间"
            elif spec.minimum is not None:
                detail = f"{spec.key} 必须大于或等于 {spec.minimum:g}"
            else:
                detail = f"{spec.key} 必须小于或等于 {spec.maximum:g}"
            raise HTTPException(status_code=400, detail=detail)
        return parsed

    def _collect_values(self, available, source, supplied) -> dict[str, Any]:
        """非空通用参数覆盖旧字段；未知字段不参与类型校验。"""
        raw: dict[str, Any] = {}
        for values in (source, supplied):
            if values is None:
                continue
            for key in available:
                value = self._lookup(values, key)
                if value is not None and value != "":
                    raw[key] = value
        return raw

    def parse(self, model_id: str, source: Mapping[str, Any] | Any | None = None, *, supplied: Mapping[str, Any] | None = None) -> dict[str, Any]:
        available = {item.key: item for item in self._schemas.get(str(model_id or ""), ())}
        raw = self._collect_values(available, source, supplied)
        parsed: dict[str, Any] = {}
        for key, value in raw.items():
            spec = available[key]
            if spec.value_type == "boolean":
                parsed_value = self._parse_bool(value, key)
                if parsed_value is not None:
                    parsed[key] = parsed_value
            elif spec.value_type == "integer":
                parsed[key] = self._parse_integer(value, spec)
        return parsed
