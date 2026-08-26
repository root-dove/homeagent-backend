import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models import Device
from app.schemas import (
    CommandClaimRequest,
    CommandClaimResponse,
    CommandFailureRequest,
    CommandResultResponse,
    DeviceCommand,
    DeviceHeartbeatRequest,
    DeviceRegisterRequest,
    DeviceRegistrationResponse,
    DeviceResponse,
)
from app.services.device_commands import (
    ClaimedCommand,
    CommandConflict,
    CommandLeaseExpired,
    CommandNotFound,
    CommandResult,
    claim_commands,
    complete_command,
    fail_command,
)
from app.services.devices import (
    DeviceAlreadyExists,
    DeviceAuthenticationFailed,
    DeviceDisabled,
    authenticate_device,
    connection_status,
    list_devices,
    record_heartbeat,
    register_device,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RegistrationToken = Annotated[
    str | None,
    Header(alias="X-HomeAgent-Registration-Token"),
]
DeviceApiKey = Annotated[str | None, Header(alias="X-HomeAgent-Device-Key")]


def get_authenticated_device(
    session: DatabaseSession,
    api_key: DeviceApiKey = None,
) -> Device:
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device API key is required.",
        )
    try:
        return authenticate_device(session, api_key)
    except DeviceAuthenticationFailed as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error
    except DeviceDisabled as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


AuthenticatedDevice = Annotated[Device, Depends(get_authenticated_device)]


@router.post(
    "/register",
    response_model=DeviceRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_device(
    payload: DeviceRegisterRequest,
    session: DatabaseSession,
    settings: AppSettings,
    registration_token: RegistrationToken = None,
) -> DeviceRegistrationResponse:
    _require_registration_token(registration_token, settings)
    try:
        device, api_key = register_device(
            session,
            device_key=payload.device_key,
            name=payload.name,
            room_name=payload.room_name,
            metadata_json=payload.metadata,
        )
        session.commit()
        session.refresh(device)
    except DeviceAlreadyExists as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Device '{payload.device_key}' already exists.",
        ) from error

    return DeviceRegistrationResponse(
        device=_device_response(device, settings=settings),
        api_key=api_key,
    )


@router.get("", response_model=list[DeviceResponse])
def read_devices(
    session: DatabaseSession,
    settings: AppSettings,
    registration_token: RegistrationToken = None,
) -> list[DeviceResponse]:
    _require_registration_token(registration_token, settings)
    return [_device_response(device, settings=settings) for device in list_devices(session)]


@router.post("/heartbeat", response_model=DeviceResponse)
def heartbeat(
    payload: DeviceHeartbeatRequest,
    device: AuthenticatedDevice,
    session: DatabaseSession,
    settings: AppSettings,
) -> DeviceResponse:
    record_heartbeat(
        device,
        now=datetime.now(UTC),
        agent_version=payload.agent_version,
        camera_status=payload.camera_status,
        metadata_json=payload.metadata,
    )
    session.commit()
    session.refresh(device)
    return _device_response(device, settings=settings)


@router.post("/commands/claim", response_model=CommandClaimResponse)
def claim_device_commands(
    payload: CommandClaimRequest,
    device: AuthenticatedDevice,
    session: DatabaseSession,
    settings: AppSettings,
) -> CommandClaimResponse:
    commands = claim_commands(
        session,
        device=device,
        now=datetime.now(UTC),
        limit=payload.limit,
        lease_seconds=settings.device_command_lease_seconds,
        max_attempts=settings.device_command_max_attempts,
    )
    session.commit()
    return CommandClaimResponse(commands=[_command_response(command) for command in commands])


@router.post("/commands/{run_id}/complete", response_model=CommandResultResponse)
def complete_device_command(
    run_id: UUID,
    device: AuthenticatedDevice,
    session: DatabaseSession,
    response: Response,
) -> CommandResultResponse:
    try:
        result = complete_command(
            session,
            device=device,
            run_id=run_id,
            now=datetime.now(UTC),
        )
    except CommandNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (CommandConflict, CommandLeaseExpired) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    session.commit()
    if result.replayed:
        response.headers["X-HomeAgent-Idempotent-Replay"] = "true"
    return _command_result_response(result)


@router.post("/commands/{run_id}/fail", response_model=CommandResultResponse)
def fail_device_command(
    run_id: UUID,
    payload: CommandFailureRequest,
    device: AuthenticatedDevice,
    session: DatabaseSession,
    settings: AppSettings,
    response: Response,
) -> CommandResultResponse:
    try:
        result = fail_command(
            session,
            device=device,
            run_id=run_id,
            now=datetime.now(UTC),
            error_message=payload.error_message,
            retryable=payload.retryable,
            max_attempts=settings.device_command_max_attempts,
        )
    except CommandNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (CommandConflict, CommandLeaseExpired) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    session.commit()
    if result.replayed:
        response.headers["X-HomeAgent-Idempotent-Replay"] = "true"
    return _command_result_response(result)


def _require_registration_token(provided: str | None, settings: Settings) -> None:
    expected = settings.device_registration_token
    if expected is None or not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device registration is not configured.",
        )
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device registration token.",
        )


def _device_response(device: Device, *, settings: Settings) -> DeviceResponse:
    now = datetime.now(UTC)
    return DeviceResponse(
        id=device.id,
        device_key=device.device_key,
        name=device.name,
        room_name=device.room_name,
        enabled=device.enabled,
        connection_status=connection_status(
            device,
            now=now,
            offline_after_seconds=settings.device_offline_after_seconds,
        ),
        last_heartbeat_at=device.last_heartbeat_at,
        last_agent_version=device.last_agent_version,
        last_camera_status=device.last_camera_status,
        metadata=device.metadata_json,
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


def _command_response(command: ClaimedCommand) -> DeviceCommand:
    lease_expires_at = command.run.lease_expires_at
    if lease_expires_at is None:
        raise RuntimeError("Claimed command has no lease expiration.")
    return DeviceCommand(
        id=command.run.id,
        mode_instance_key=command.mode_instance_key,
        trigger=command.run.trigger,
        scheduled_for=command.run.scheduled_for,
        attempt_count=command.run.attempt_count,
        lease_expires_at=lease_expires_at,
    )


def _command_result_response(result: CommandResult) -> CommandResultResponse:
    return CommandResultResponse(
        id=result.run.id,
        status=result.run.status,
        mode_runtime_state=result.mode_runtime_state,
        replayed=result.replayed,
        retry_scheduled=result.retry_scheduled,
    )
