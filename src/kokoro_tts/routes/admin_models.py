"""Pydantic models for AngeVoice admin APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

from ..admin_config_schema import ADMIN_CONFIG_FIELDS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminModelAction(StrictModel):
    include_current: bool = True
    force: bool = False


class AdminSingleModelAction(StrictModel):
    force: bool = False


class AdminSwitchModelAction(StrictModel):
    model: str
    unload_previous: bool | None = None
    load: bool = True


class AdminApiKeyAction(StrictModel):
    rotate: bool = True


class AdminProfileAction(StrictModel):
    profile: str


# 后台可编辑字段列表保持单一来源，定义在 admin_config_schema 中。
# Pydantic 仍会拒绝未知字段；值范围/类型由 validate_admin_config_values() 校验，
# 因此新增可编辑字段只需修改一处 schema 表。
AdminConfigPatch = create_model(
    "AdminConfigPatch",
    __base__=StrictModel,
    **{key: (Any | None, None) for key in ADMIN_CONFIG_FIELDS.keys()},
)
