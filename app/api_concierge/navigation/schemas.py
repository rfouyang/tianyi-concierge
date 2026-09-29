"""Transport schemas for manual navigation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GoToPoiCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poi_id: str = Field(min_length=1)
    content: str | None = Field(default=None, max_length=2000)
