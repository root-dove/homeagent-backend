from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.domain.cleanliness import CleanlinessState
from app.main import app
from app.models import Device, Mode, ModeRun
from app.services.scheduler import ModeRunStatus

REGISTRATION_TOKEN = "test-registration-token"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        device_registration_token=REGISTRATION_TOKEN,
        device_offline_after_seconds=90,
        device_command_lease_seconds=120,
        device_command_max_attempts=2,
    )


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def client(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> Iterator[TestClient]:
    def override_session() -> Generator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register_device(
    client: TestClient,
    *,
    device_key: str = "bedroom-camera",
) -> tuple[dict[str, object], str]:
    response = client.post(
        "/api/v1/devices/register",
        headers={"X-HomeAgent-Registration-Token": REGISTRATION_TOKEN},
        json={
            "device_key": device_key,
            "name": f"{device_key} 장치",
            "room_name": "침실",
            "metadata": {"model": "Raspberry Pi 5"},
        },
    )
    assert response.status_code == 201
    payload = response.json()
    return payload["device"], payload["api_key"]


def add_queued_run(session_factory: sessionmaker[Session]) -> str:
    with session_factory.begin() as session:
        mode = Mode(
            instance_key="cleanliness",
            mode_type="cleanliness",
            name="청결 모드",
            enabled=True,
            runtime_state=CleanlinessState.ANALYZING.value,
            state_version=1,
            config={},
        )
        run = ModeRun(
            mode_state_version=1,
            trigger="schedule_due",
            status=ModeRunStatus.QUEUED.value,
            scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
        )
        mode.runs.append(run)
        session.add(mode)
        session.flush()
        return str(run.id)


def test_device_registration_requires_admin_token(client: TestClient) -> None:
    payload = {
        "device_key": "bedroom-camera",
        "name": "침실 카메라",
        "room_name": "침실",
    }

    missing = client.post("/api/v1/devices/register", json=payload)
    invalid = client.post(
        "/api/v1/devices/register",
        headers={"X-HomeAgent-Registration-Token": "wrong"},
        json=payload,
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_registration_returns_key_once_and_rejects_duplicate(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    device_payload, api_key = register_device(client)

    assert device_payload["connection_status"] == "never_connected"
    assert api_key.startswith("ha_dev_")
    with session_factory() as session:
        device = session.scalar(select(Device))
        assert device is not None
        assert api_key not in device.api_key_hash

    duplicate = client.post(
        "/api/v1/devices/register",
        headers={"X-HomeAgent-Registration-Token": REGISTRATION_TOKEN},
        json={
            "device_key": "bedroom-camera",
            "name": "중복",
            "room_name": "침실",
        },
    )
    assert duplicate.status_code == 409


def test_registration_is_unavailable_without_server_token(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        device_registration_token=None,
    )

    response = client.post(
        "/api/v1/devices/register",
        headers={"X-HomeAgent-Registration-Token": REGISTRATION_TOKEN},
        json={
            "device_key": "bedroom-camera",
            "name": "침실 카메라",
            "room_name": "침실",
        },
    )

    assert response.status_code == 503


def test_heartbeat_authenticates_and_updates_device(client: TestClient) -> None:
    _, api_key = register_device(client)

    missing = client.post(
        "/api/v1/devices/heartbeat",
        json={"agent_version": "0.1.0", "camera_status": "ready"},
    )
    invalid = client.post(
        "/api/v1/devices/heartbeat",
        headers={"X-HomeAgent-Device-Key": f"{api_key}wrong"},
        json={"agent_version": "0.1.0", "camera_status": "ready"},
    )
    valid = client.post(
        "/api/v1/devices/heartbeat",
        headers={"X-HomeAgent-Device-Key": api_key},
        json={
            "agent_version": "0.1.0",
            "camera_status": "ready",
            "metadata": {"temperature_c": 51},
        },
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200
    assert valid.json()["connection_status"] == "online"
    assert valid.json()["last_agent_version"] == "0.1.0"
    assert valid.json()["last_camera_status"] == "ready"
    assert valid.json()["metadata"]["temperature_c"] == 51


def test_stale_heartbeat_is_reported_offline(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    device_payload, _ = register_device(client)
    with session_factory.begin() as session:
        device = session.get(Device, UUID(str(device_payload["id"])))
        assert device is not None
        device.last_heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)

    response = client.get(
        "/api/v1/devices",
        headers={"X-HomeAgent-Registration-Token": REGISTRATION_TOKEN},
    )

    assert response.status_code == 200
    assert response.json()[0]["connection_status"] == "offline"


def test_admin_can_list_device_status(client: TestClient) -> None:
    register_device(client, device_key="second-camera")
    register_device(client, device_key="first-camera")

    unauthorized = client.get("/api/v1/devices")
    response = client.get(
        "/api/v1/devices",
        headers={"X-HomeAgent-Registration-Token": REGISTRATION_TOKEN},
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert [item["device_key"] for item in response.json()] == [
        "first-camera",
        "second-camera",
    ]


def test_disabled_device_is_forbidden(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    device_payload, api_key = register_device(client)
    with session_factory.begin() as session:
        device = session.get(Device, UUID(str(device_payload["id"])))
        assert device is not None
        device.enabled = False

    response = client.post(
        "/api/v1/devices/heartbeat",
        headers={"X-HomeAgent-Device-Key": api_key},
        json={"agent_version": "0.1.0", "camera_status": "ready"},
    )

    assert response.status_code == 403


def test_only_one_device_can_claim_a_queued_command(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    _, first_key = register_device(client, device_key="first-camera")
    _, second_key = register_device(client, device_key="second-camera")
    run_id = add_queued_run(session_factory)

    first = client.post(
        "/api/v1/devices/commands/claim",
        headers={"X-HomeAgent-Device-Key": first_key},
        json={"limit": 1},
    )
    second = client.post(
        "/api/v1/devices/commands/claim",
        headers={"X-HomeAgent-Device-Key": second_key},
        json={"limit": 1},
    )

    assert first.status_code == 200
    assert first.json()["commands"][0]["id"] == run_id
    assert first.json()["commands"][0]["attempt_count"] == 1
    assert first.json()["commands"][0]["mode_instance_key"] == "cleanliness"
    assert second.status_code == 200
    assert second.json()["commands"] == []


def test_command_completion_is_idempotent(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    _, api_key = register_device(client)
    run_id = add_queued_run(session_factory)
    claimed = client.post(
        "/api/v1/devices/commands/claim",
        headers={"X-HomeAgent-Device-Key": api_key},
        json={"limit": 1},
    )
    assert claimed.status_code == 200

    first = client.post(
        f"/api/v1/devices/commands/{run_id}/complete",
        headers={"X-HomeAgent-Device-Key": api_key},
    )
    second = client.post(
        f"/api/v1/devices/commands/{run_id}/complete",
        headers={"X-HomeAgent-Device-Key": api_key},
    )

    assert first.status_code == 200
    assert first.json()["status"] == ModeRunStatus.COMPLETED.value
    assert first.json()["replayed"] is False
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.headers["X-HomeAgent-Idempotent-Replay"] == "true"


def test_retryable_failure_requeues_then_exhaustion_moves_mode_to_error(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    _, api_key = register_device(client)
    run_id = add_queued_run(session_factory)

    assert (
        client.post(
            "/api/v1/devices/commands/claim",
            headers={"X-HomeAgent-Device-Key": api_key},
            json={"limit": 1},
        ).status_code
        == 200
    )
    retry = client.post(
        f"/api/v1/devices/commands/{run_id}/fail",
        headers={"X-HomeAgent-Device-Key": api_key},
        json={"error_message": "camera busy", "retryable": True},
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == ModeRunStatus.QUEUED.value
    assert retry.json()["retry_scheduled"] is True

    claimed_again = client.post(
        "/api/v1/devices/commands/claim",
        headers={"X-HomeAgent-Device-Key": api_key},
        json={"limit": 1},
    )
    assert claimed_again.json()["commands"][0]["attempt_count"] == 2
    exhausted = client.post(
        f"/api/v1/devices/commands/{run_id}/fail",
        headers={"X-HomeAgent-Device-Key": api_key},
        json={"error_message": "camera unavailable", "retryable": True},
    )
    replayed = client.post(
        f"/api/v1/devices/commands/{run_id}/fail",
        headers={"X-HomeAgent-Device-Key": api_key},
        json={"error_message": "camera unavailable", "retryable": True},
    )

    assert exhausted.status_code == 200
    assert exhausted.json()["status"] == ModeRunStatus.FAILED.value
    assert exhausted.json()["mode_runtime_state"] == CleanlinessState.ERROR.value
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True


def test_expired_lease_is_rejected_then_reclaimed(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    _, first_key = register_device(client, device_key="first-camera")
    _, second_key = register_device(client, device_key="second-camera")
    run_id = add_queued_run(session_factory)
    assert (
        client.post(
            "/api/v1/devices/commands/claim",
            headers={"X-HomeAgent-Device-Key": first_key},
            json={"limit": 1},
        ).status_code
        == 200
    )
    with session_factory.begin() as session:
        run = session.get(ModeRun, UUID(run_id))
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    expired = client.post(
        f"/api/v1/devices/commands/{run_id}/complete",
        headers={"X-HomeAgent-Device-Key": first_key},
    )
    reclaimed = client.post(
        "/api/v1/devices/commands/claim",
        headers={"X-HomeAgent-Device-Key": second_key},
        json={"limit": 1},
    )

    assert expired.status_code == 409
    assert "expired" in expired.json()["detail"]
    assert reclaimed.status_code == 200
    assert reclaimed.json()["commands"][0]["id"] == run_id
    assert reclaimed.json()["commands"][0]["attempt_count"] == 2


def test_expired_lease_at_attempt_limit_fails_mode(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    _, first_key = register_device(client, device_key="first-camera")
    _, second_key = register_device(client, device_key="second-camera")
    run_id = add_queued_run(session_factory)
    claimed = client.post(
        "/api/v1/devices/commands/claim",
        headers={"X-HomeAgent-Device-Key": first_key},
        json={"limit": 1},
    )
    assert claimed.status_code == 200

    with session_factory.begin() as session:
        run = session.get(ModeRun, UUID(run_id))
        assert run is not None
        run.attempt_count = 2
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    reclaimed = client.post(
        "/api/v1/devices/commands/claim",
        headers={"X-HomeAgent-Device-Key": second_key},
        json={"limit": 1},
    )

    assert reclaimed.status_code == 200
    assert reclaimed.json()["commands"] == []
    with session_factory() as session:
        run = session.get(ModeRun, UUID(run_id))
        assert run is not None
        assert run.status == ModeRunStatus.FAILED.value
        assert run.error_message == "Command lease expired."
        assert run.mode.runtime_state == CleanlinessState.ERROR.value


def test_foreign_device_and_unknown_command_are_rejected(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    _, first_key = register_device(client, device_key="first-camera")
    _, second_key = register_device(client, device_key="second-camera")
    run_id = add_queued_run(session_factory)
    assert (
        client.post(
            "/api/v1/devices/commands/claim",
            headers={"X-HomeAgent-Device-Key": first_key},
            json={"limit": 1},
        ).status_code
        == 200
    )

    foreign = client.post(
        f"/api/v1/devices/commands/{run_id}/complete",
        headers={"X-HomeAgent-Device-Key": second_key},
    )
    unknown = client.post(
        "/api/v1/devices/commands/00000000-0000-0000-0000-000000000000/complete",
        headers={"X-HomeAgent-Device-Key": first_key},
    )

    assert foreign.status_code == 409
    assert unknown.status_code == 404
