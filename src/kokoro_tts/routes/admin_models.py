"""Pydantic models for AngeVoice admin APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from ..admin_config_schema import ADMIN_CONFIG_FIELDS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminModelAction(StrictModel):
    include_current: bool = True
    force: bool = False


class AdminSingleModelAction(StrictModel):
    force: bool = False


class AdminAssetRepairAction(StrictModel):
    force_unload: bool = False


class AdminSwitchModelAction(StrictModel):
    model: str
    unload_previous: bool | None = None
    load: bool = True


class AdminApiKeyAction(StrictModel):
    rotate: bool = True


class AdminCredentialUpdate(StrictModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=10, max_length=256)


class AdminProfileAction(StrictModel):
    profile: str


# 管理后台可编辑字段统一维护在 admin_config_schema。
# Pydantic 仍会拒绝未知字段；取值范围和类型由
# validate_admin_config_values() 校验，因此新增可编辑字段只需要修改
# 一张 schema 表。
AdminConfigPatch = create_model(
    "AdminConfigPatch",
    __base__=StrictModel,
    **{key: (Any | None, None) for key in ADMIN_CONFIG_FIELDS.keys()},
)
