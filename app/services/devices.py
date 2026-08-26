from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device
from app.services.device_keys import (
    InvalidDeviceApiKey,
    device_id_from_api_key,
    generate_device_api_key,
    verify_device_api_key,
)


class DeviceAlreadyExists(ValueError):
    pass


class DeviceAuthenticationFailed(PermissionError):
    pass


class DeviceDisabled(PermissionError):
    pass


def register_device(
    session: Session,
    *,
    device_key: str,
    name: str,
    room_name: str,
    metadata_json: dict[str, Any],
) -> tuple[Device, str]:
    if session.scalar(select(Device.id).where(Device.device_key == device_key)) is not None:
        raise DeviceAlreadyExists(f"Device '{device_key}' already exists.")

    device = Device(
        device_key=device_key,
        name=name,
        room_name=room_name,
        enabled=True,
        api_key_hash="pending",
        metadata_json=metadata_json,
    )
    session.add(device)
    session.flush()
    raw_api_key, stored_hash = generate_device_api_key(device.id)
    device.api_key_hash = stored_hash
    return device, raw_api_key


def authenticate_device(session: Session, raw_api_key: str) -> Device:
    try:
        device_id = device_id_from_api_key(raw_api_key)
    except InvalidDeviceApiKey as error:
        raise DeviceAuthenticationFailed("Device authentication failed.") from error

    device = session.get(Device, device_id)
    if device is None or not verify_device_api_key(raw_api_key, device.api_key_hash):
        raise DeviceAuthenticationFailed("Device authentication failed.")
    if not device.enabled:
        raise DeviceDisabled(f"Device '{device.device_key}' is disabled.")
    return device


def record_heartbeat(
    device: Device,
    *,
    now: datetime,
    agent_version: str,
    camera_status: str,
    metadata_json: dict[str, Any],
) -> None:
    device.last_heartbeat_at = now
    device.last_agent_version = agent_version
    device.last_camera_status = camera_status
    device.metadata_json = {**device.metadata_json, **metadata_json}


def list_devices(session: Session) -> list[Device]:
    return list(session.scalars(select(Device).order_by(Device.device_key)))


def connection_status(
    device: Device,
    *,
    now: datetime,
    offline_after_seconds: int,
) -> str:
    if not device.enabled:
        return "disabled"
    if device.last_heartbeat_at is None:
        return "never_connected"
    cutoff = now - timedelta(seconds=offline_after_seconds)
    heartbeat = device.last_heartbeat_at
    if heartbeat.tzinfo is None and now.tzinfo is not None:
        heartbeat = heartbeat.replace(tzinfo=now.tzinfo)
    return "online" if heartbeat >= cutoff else "offline"
