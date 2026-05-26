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

    def parse(self, model_id: str, source: Mapping[str, Any] | Any | None = None, *, supplied: Mapping[str, Any] | None = None) -> dict[str, Any]:
        available = {item.key: item for item in self._schemas.get(str(model_id or ""), ())}
        if not available:
            return {}
        raw: dict[str, Any] = {}
        # 先解析旧版顶层字段，然后在迁移期间两者都提供时
        # 让通用 engine_params 负载生效。
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
                below_minimum = spec.minimum is not None and parsed_value < spec.minimum
                above_maximum = spec.maximum is not None and parsed_value > spec.maximum
                if below_minimum or above_maximum:
                    if spec.minimum is not None and spec.maximum is not None:
                        detail = f"{key} 必须在 {spec.minimum:g} 到 {spec.maximum:g} 之间"
                    elif spec.minimum is not None:
                        detail = f"{key} 必须大于或等于 {spec.minimum:g}"
                    else:
                        detail = f"{key} 必须小于或等于 {spec.maximum:g}"
                    raise HTTPException(status_code=400, detail=detail)
                parsed[key] = parsed_value
        return parsed
