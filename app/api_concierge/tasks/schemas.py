"""Transport schemas for task design."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TaskActionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1)
    phase: str = "with_speech"
    required: bool = True


class TaskStopModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poi_id: str = Field(min_length=1)
    poi_name: str = Field(min_length=1)
    content: str = Field(min_length=1)
    actions: list[TaskActionModel] = Field(default_factory=list)
    audio: str | None = Field(default=None, description="Uploaded speech file in data/tts")
    audio_name: str | None = Field(default=None, max_length=120)


class SaveTaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    stops: list[TaskStopModel] = Field(min_length=1)


class SpeechPreviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)


class RehearseCommand(BaseModel):
    """Perform actions (and optionally speech) in place on Tianyi."""

    model_config = ConfigDict(extra="forbid")

    actions: list[TaskActionModel] = Field(default_factory=list)
    content: str | None = Field(default=None, max_length=2000)
    audio: str | None = None
    arms_confirmed: bool = False
