"""Transport schemas for loading maps and localizing."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoadMapCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    confirmed: bool = False


class SyncMapCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False


class SnapshotCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    overwrite: bool = False


class LocalizeAtPoseCommand(BaseModel):
    """An operator-placed arrow: position in metres, heading in radians."""

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    yaw: float
    search_half_size: float = Field(default=1.0, ge=0.25, le=5.0)
    allow_rotation: bool = False
    rotation_confirmed: bool = False


class BindDockCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False
