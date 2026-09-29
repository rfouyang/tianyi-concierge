"""Transport schemas for POI management."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RecordPoiCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
