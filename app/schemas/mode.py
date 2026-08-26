from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModeCreate(BaseModel):
    instance_key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        examples=["cleanliness"],
    )
    mode_type: str = Field(min_length=1, max_length=50, examples=["cleanliness"])
    name: str = Field(min_length=1, max_length=100, examples=["청결 모드"])
    enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class ModeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    instance_key: str
    mode_type: str
    name: str
    enabled: bool
    runtime_state: str
    config: dict[str, Any]
    next_run_at: datetime | None
    state_version: int
    created_at: datetime
    updated_at: datetime
