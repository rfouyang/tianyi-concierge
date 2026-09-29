"""Transport schemas for running guide tasks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RunTaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    arms_confirmed: bool = False
