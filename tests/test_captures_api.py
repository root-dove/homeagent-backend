import hashlib
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.domain.cleanliness import CleanlinessState
from app.main import app
from app.models import Capture, Mode, ModeRun
from app.services.scheduler import ModeRunStatus

REGISTRATION_TOKEN = "capture-registration-token"


@pytest.fixture
def capture_storage_dir(tmp_path: Path) -> Path:
    return tmp_path / "private-captures"


@pytest.fixture
def settings(capture_storage_dir: Path) -> Settings:
    return Settings(
        _env_file=None,
        device_registration_token=REGISTRATION_TOKEN,
        device_command_lease_seconds=120,
        device_command_max_attempts=2,
        capture_storage_dir=capture_storage_dir,
        capture_max_upload_bytes=1024 * 1024,
        capture_retention_days=7,
        capture_min_width=64,
        capture_min_height=64,
        capture_max_pixels=1_000_000,
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


def register_device(client: TestClient, *, device_key: str = "capture-camera") -> str:
    response = client.post(
        "/api/v1/devices/register",
        headers={"X-HomeAgent-Registration-Token": REGISTRATION_TOKEN},
        json={
            "device_key": device_key,
            "name": f"{device_key} 장치",
            "room_name": "침실",
        },
    )
    assert response.status_code == 201
    return response.json()["api_key"]


def add_queued_run(session_factory: sessionmaker[Session]) -> UUID:
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
        return run.id


def claim_run(client: TestClient, api_key: str) -> None:
    response = client.post(
        "/api/v1/devices/commands/claim",
        headers={"X-HomeAgent-Device-Key": api_key},
        json={"limit": 1},
    )
    assert response.status_code == 200
    assert len(response.json()["commands"]) == 1


def jpeg_bytes(width: int = 128, height: int = 72) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), color=(120, 100, 80)).save(
        output,
        format="JPEG",
        quality=90,
    )
    return output.getvalue()


def upload(
    client: TestClient,
    *,
    run_id: UUID,
    api_key: str,
    content: bytes | None = None,
    content_type: str = "image/jpeg",
    captured_at: str | None = None,
):
    return client.post(
        f"/api/v1/devices/commands/{run_id}/capture",
        headers={"X-HomeAgent-Device-Key": api_key},
        data={"captured_at": captured_at or datetime.now(UTC).isoformat()},
        files={"file": ("user-supplied-name.jpg", content or jpeg_bytes(), content_type)},
    )


def test_valid_capture_is_stored_privately_and_completes_run(
    client: TestClient,
    session_factory: sessionmaker[Session],
    capture_storage_dir: Path,
) -> None:
    api_key = register_device(client)
    run_id = add_queued_run(session_factory)
    claim_run(client, api_key)
    content = jpeg_bytes()

    response = upload(client, run_id=run_id, api_key=api_key, content=content)

    assert response.status_code == 201
    payload = response.json()
    assert payload["run_id"] == str(run_id)
    assert payload["content_type"] == "image/jpeg"
    assert payload["size_bytes"] == len(content)
    assert payload["sha256"] == hashlib.sha256(content).hexdigest()
    assert (payload["width"], payload["height"]) == (128, 72)
    assert payload["quality_status"] == "valid"
    assert payload["replayed"] is False

    with session_factory() as session:
        capture = session.scalar(select(Capture))
        run = session.get(ModeRun, run_id)
        assert capture is not None
        assert run is not None
        assert run.status == ModeRunStatus.COMPLETED.value
        assert capture.file_path == f"{capture.id}.jpg"
        assert "user-supplied-name" not in capture.file_path
        assert (capture_storage_dir / capture.file_path).read_bytes() == content


def test_capture_retry_is_idempotent_without_rewriting_file(
    client: TestClient,
    session_factory: sessionmaker[Session],
    capture_storage_dir: Path,
) -> None:
    api_key = register_device(client)
    run_id = add_queued_run(session_factory)
    claim_run(client, api_key)
    first = upload(client, run_id=run_id, api_key=api_key)
    stored_file = next(capture_storage_dir.glob("*.jpg"))
    original_mtime = stored_file.stat().st_mtime_ns

    replayed = upload(
        client,
        run_id=run_id,
        api_key=api_key,
        content=b"not-a-jpeg",
        content_type="application/octet-stream",
    )

    assert replayed.status_code == 200
    assert replayed.json()["id"] == first.json()["id"]
    assert replayed.json()["replayed"] is True
    assert replayed.headers["X-HomeAgent-Idempotent-Replay"] == "true"
    assert stored_file.stat().st_mtime_ns == original_mtime
    with session_factory() as session:
        assert len(list(session.scalars(select(Capture)))) == 1


@pytest.mark.parametrize(
    ("content", "content_type", "expected_detail"),
    [
        (b"not-a-jpeg", "image/jpeg", "valid JPEG"),
        (jpeg_bytes(), "image/png", "image/jpeg"),
        (jpeg_bytes(32, 32), "image/jpeg", "at least 64x64"),
    ],
)
def test_invalid_capture_does_not_complete_run_or_leave_file(
    client: TestClient,
    session_factory: sessionmaker[Session],
    capture_storage_dir: Path,
    content: bytes,
    content_type: str,
    expected_detail: str,
) -> None:
    api_key = register_device(client)
    run_id = add_queued_run(session_factory)
    claim_run(client, api_key)

    response = upload(
        client,
        run_id=run_id,
        api_key=api_key,
        content=content,
        content_type=content_type,
    )

    assert response.status_code == 422
    assert expected_detail in response.json()["detail"]
    assert list(capture_storage_dir.glob("*")) == []
    with session_factory() as session:
        run = session.get(ModeRun, run_id)
        assert run is not None
        assert run.status == ModeRunStatus.PROCESSING.value
        assert session.scalar(select(Capture)) is None


def test_oversized_capture_returns_413(
    client: TestClient,
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    settings.capture_max_upload_bytes = 10
    api_key = register_device(client)
    run_id = add_queued_run(session_factory)
    claim_run(client, api_key)

    response = upload(client, run_id=run_id, api_key=api_key)

    assert response.status_code == 413
    assert "10 byte" in response.json()["detail"]


@pytest.mark.parametrize(
    "captured_at",
    [
        "2026-08-26T12:00:00",
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        (datetime.now(UTC) - timedelta(days=2)).isoformat(),
    ],
)
def test_invalid_capture_time_is_rejected(
    client: TestClient,
    session_factory: sessionmaker[Session],
    captured_at: str,
) -> None:
    api_key = register_device(client)
    run_id = add_queued_run(session_factory)
    claim_run(client, api_key)

    response = upload(client, run_id=run_id, api_key=api_key, captured_at=captured_at)

    assert response.status_code == 422


def test_foreign_device_cannot_upload_assigned_command(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    first_key = register_device(client, device_key="first-camera")
    second_key = register_device(client, device_key="second-camera")
    run_id = add_queued_run(session_factory)
    claim_run(client, first_key)

    response = upload(client, run_id=run_id, api_key=second_key)

    assert response.status_code == 409
    assert "not assigned" in response.json()["detail"]


def test_expired_or_unknown_command_is_rejected_before_storage(
    client: TestClient,
    session_factory: sessionmaker[Session],
    capture_storage_dir: Path,
) -> None:
    api_key = register_device(client)
    run_id = add_queued_run(session_factory)
    claim_run(client, api_key)
    with session_factory.begin() as session:
        run = session.get(ModeRun, run_id)
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    expired = upload(client, run_id=run_id, api_key=api_key)
    unknown = upload(
        client,
        run_id=UUID("00000000-0000-0000-0000-000000000000"),
        api_key=api_key,
    )

    assert expired.status_code == 409
    assert unknown.status_code == 404
    assert not capture_storage_dir.exists()
