from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DeviceRegisterRequest(BaseModel):
    device_key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        examples=["bedroom-camera"],
    )
    name: str = Field(min_length=1, max_length=100, examples=["침실 카메라"])
    room_name: str = Field(min_length=1, max_length=100, examples=["침실"])
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceHeartbeatRequest(BaseModel):
    agent_version: str = Field(min_length=1, max_length=50)
    camera_status: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceResponse(BaseModel):
    id: UUID
    device_key: str
    name: str
    room_name: str
    enabled: bool
    connection_status: str
    last_heartbeat_at: datetime | None
    last_agent_version: str | None
    last_camera_status: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DeviceRegistrationResponse(BaseModel):
    device: DeviceResponse
    api_key: str


class CommandClaimRequest(BaseModel):
    limit: int = Field(default=1, ge=1, le=10)


class DeviceCommand(BaseModel):
    id: UUID
    command_type: str = "capture"
    mode_instance_key: str
    trigger: str
    scheduled_for: datetime
    attempt_count: int
    lease_expires_at: datetime


class CommandClaimResponse(BaseModel):
    commands: list[DeviceCommand]


class CommandFailureRequest(BaseModel):
    error_message: str = Field(min_length=1, max_length=500)
    retryable: bool = True


class CommandResultResponse(BaseModel):
    id: UUID
    status: str
    mode_runtime_state: str
    replayed: bool = False
    retry_scheduled: bool = False
