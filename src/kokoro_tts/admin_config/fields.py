"""Shared admin configuration field primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdminConfigField:
    key: str
    env: str
    label: str
    group: str
    type: str
    default: Any
    min_value: float | int | None = None
    max_value: float | int | None = None
    step: float | int | None = None
    choices: tuple[tuple[str, str], ...] = ()
    restart: bool = False
    rebuild_moss: bool = False
    advanced: bool = False
    help: str = ""

    def as_schema(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "env": self.env,
            "label": self.label,
            "group": self.group,
            "type": self.type,
            "default": self.default,
            "min": self.min_value,
            "max": self.max_value,
            "step": self.step,
            "choices": [{"value": value, "label": label} for value, label in self.choices],
            "restart": self.restart,
            "rebuild_moss": self.rebuild_moss,
            "advanced": self.advanced,
            "help": self.help,
        }


def field_def(*args, **kwargs) -> AdminConfigField:
    return AdminConfigField(*args, **kwargs)
