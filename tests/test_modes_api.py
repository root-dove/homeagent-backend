from collections.abc import Generator, Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db_session
from app.domain.cleanliness import CleanlinessState
from app.main import app
from app.models import Mode


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
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_session() -> Generator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register_cleanliness_mode(client: TestClient, **overrides: object) -> Response:
    payload: dict[str, object] = {
        "instance_key": "cleanliness",
        "mode_type": "cleanliness",
        "name": "청결 모드",
        "config": {"interval_minutes": 30},
    }
    payload.update(overrides)
    return client.post("/api/v1/modes", json=payload)


def test_register_and_read_modes(client: TestClient) -> None:
    response = register_cleanliness_mode(client)

    assert response.status_code == 201
    created = response.json()
    assert created["instance_key"] == "cleanliness"
    assert created["enabled"] is False
    assert created["runtime_state"] == CleanlinessState.MONITORING.value
    assert created["state_version"] == 0
    assert created["config"] == {"interval_minutes": 30}

    get_response = client.get("/api/v1/modes/cleanliness")
    list_response = client.get("/api/v1/modes")

    assert get_response.status_code == 200
    assert get_response.json() == created
    assert list_response.status_code == 200
    assert list_response.json() == [created]


def test_register_rejects_duplicate_instance_key(client: TestClient) -> None:
    assert register_cleanliness_mode(client).status_code == 201

    response = register_cleanliness_mode(client)

    assert response.status_code == 409
    assert response.json()["detail"] == "Mode 'cleanliness' already exists."


def test_register_rejects_unsupported_mode_type(client: TestClient) -> None:
    response = register_cleanliness_mode(client, mode_type="security")

    assert response.status_code == 422
    assert response.json()["detail"] == "Mode type 'security' is not registered."


def test_register_validates_instance_key(client: TestClient) -> None:
    response = register_cleanliness_mode(client, instance_key="Clean Room")

    assert response.status_code == 422


def test_read_unknown_mode_returns_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/modes/unknown")

    assert response.status_code == 404
    assert response.json()["detail"] == "Mode 'unknown' does not exist."


def test_disable_is_idempotent_and_preserves_dirty_state(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    assert register_cleanliness_mode(client, enabled=True).status_code == 201
    with session_factory() as session:
        mode = session.query(Mode).filter_by(instance_key="cleanliness").one()
        mode.runtime_state = CleanlinessState.DIRTY.value
        mode.next_run_at = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)
        session.commit()

    first_response = client.post("/api/v1/modes/cleanliness/disable")
    second_response = client.post("/api/v1/modes/cleanliness/disable")

    assert first_response.status_code == 200
    assert first_response.json()["enabled"] is False
    assert first_response.json()["runtime_state"] == CleanlinessState.DIRTY.value
    assert first_response.json()["next_run_at"] is None
    assert first_response.json()["state_version"] == 1
    assert "X-HomeAgent-Idempotent-Replay" not in first_response.headers

    assert second_response.status_code == 200
    assert second_response.json()["runtime_state"] == CleanlinessState.DIRTY.value
    assert second_response.json()["state_version"] == 1
    assert second_response.headers["X-HomeAgent-Idempotent-Replay"] == "true"


def test_enable_is_idempotent_and_preserves_dirty_state(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    assert register_cleanliness_mode(client).status_code == 201
    with session_factory() as session:
        mode = session.query(Mode).filter_by(instance_key="cleanliness").one()
        mode.runtime_state = CleanlinessState.DIRTY.value
        session.commit()

    first_response = client.post("/api/v1/modes/cleanliness/enable")
    second_response = client.post("/api/v1/modes/cleanliness/enable")

    assert first_response.status_code == 200
    assert first_response.json()["enabled"] is True
    assert first_response.json()["runtime_state"] == CleanlinessState.DIRTY.value
    assert first_response.json()["state_version"] == 1

    assert second_response.status_code == 200
    assert second_response.json()["state_version"] == 1
    assert second_response.headers["X-HomeAgent-Idempotent-Replay"] == "true"


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_toggle_unknown_mode_returns_not_found(client: TestClient, action: str) -> None:
    response = client.post(f"/api/v1/modes/unknown/{action}")

    assert response.status_code == 404
