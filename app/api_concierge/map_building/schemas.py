"""Transport schemas for building a new map."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StartMapBuildCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    dock_name: str = Field(min_length=1)
    confirmed: bool = False
    overwrite: bool = False


class FinishMapBuildCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overwrite: bool | None = None
