from collections.abc import Generator, Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db_session
from app.domain.cleanliness import CleanlinessState
from app.main import app
from app.models import ModeStateHistory


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


def register_mode(
    client: TestClient,
    *,
    enabled: bool = True,
    config: dict[str, object] | None = None,
) -> None:
    response = client.post(
        "/api/v1/modes",
        json={
            "instance_key": "cleanliness",
            "mode_type": "cleanliness",
            "name": "청결 모드",
            "enabled": enabled,
            "config": config or {"interval_minutes": 30, "retry_interval_minutes": 5},
        },
    )
    assert response.status_code == 201


def analysis_payload(classification: str) -> dict[str, object]:
    area_status = "clean" if classification == "clean" else classification
    return {
        "classification": classification,
        "confidence": 0.94,
        "overall_score": 92 if classification == "clean" else 35,
        "summary": "침대, 책상, 바닥을 영역별로 검사했습니다.",
        "areas": [
            {
                "area": "bed",
                "cleanliness_score": 95,
                "status": "clean",
                "issues": [],
            },
            {
                "area": "desk",
                "cleanliness_score": 88,
                "status": "clean",
                "issues": [],
            },
            {
                "area": "floor",
                "cleanliness_score": 25 if classification != "clean" else 90,
                "status": area_status,
                "issues": [] if classification == "clean" else ["바닥에 옷이 놓여 있음"],
            },
        ],
    }


def start_analysis(client: TestClient) -> Response:
    return client.post("/api/v1/modes/cleanliness/analysis/start")


def submit_result(client: TestClient, classification: str) -> Response:
    return client.post(
        "/api/v1/modes/cleanliness/analysis/result",
        json=analysis_payload(classification),
    )


def test_clean_result_schedules_next_monitoring_and_saves_area_details(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    register_mode(client)

    started = start_analysis(client)
    replayed = start_analysis(client)
    completed = submit_result(client, "clean")

    assert started.status_code == 200
    assert started.json()["transition"] == {
        "previous_state": "monitoring",
        "current_state": "analyzing",
        "trigger": "schedule_due",
        "timer_action": "none",
    }
    assert started.json()["mode"]["state_version"] == 1

    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    assert replayed.json()["transition"] is None
    assert replayed.json()["mode"]["state_version"] == 1
    assert replayed.headers["X-HomeAgent-Idempotent-Replay"] == "true"

    assert completed.status_code == 200
    assert completed.json()["mode"]["runtime_state"] == CleanlinessState.MONITORING.value
    assert completed.json()["mode"]["next_run_at"] is not None
    assert completed.json()["mode"]["state_version"] == 2
    assert completed.json()["transition"]["timer_action"] == "schedule_monitoring"

    with session_factory() as session:
        histories = list(
            session.scalars(select(ModeStateHistory).order_by(ModeStateHistory.created_at))
        )
        assert len(histories) == 2
        assert histories[-1].details["areas"][2] == {
            "area": "floor",
            "cleanliness_score": 90,
            "status": "clean",
            "issues": [],
        }


def test_dirty_verification_failure_stays_dirty_and_is_idempotent(
    client: TestClient,
) -> None:
    register_mode(client)
    assert start_analysis(client).status_code == 200

    dirty = submit_result(client, "dirty")
    verification = client.post("/api/v1/modes/cleanliness/cleaning-complete")
    repeated_verification = client.post("/api/v1/modes/cleanliness/cleaning-complete")
    failed = submit_result(client, "uncertain")

    assert dirty.status_code == 200
    assert dirty.json()["mode"]["runtime_state"] == CleanlinessState.DIRTY.value
    assert dirty.json()["mode"]["next_run_at"] is None

    assert verification.status_code == 200
    assert verification.json()["mode"]["runtime_state"] == CleanlinessState.VERIFYING.value
    assert repeated_verification.status_code == 200
    assert repeated_verification.json()["replayed"] is True
    assert repeated_verification.json()["mode"]["state_version"] == 3

    assert failed.status_code == 200
    assert failed.json()["mode"]["runtime_state"] == CleanlinessState.DIRTY.value
    assert failed.json()["mode"]["next_run_at"] is None
    assert failed.json()["transition"]["trigger"] == "verification_failed"


def test_verification_pass_schedules_monitoring(client: TestClient) -> None:
    register_mode(client)
    assert start_analysis(client).status_code == 200
    assert submit_result(client, "dirty").status_code == 200
    assert client.post("/api/v1/modes/cleanliness/cleaning-complete").status_code == 200

    response = submit_result(client, "clean")

    assert response.status_code == 200
    assert response.json()["mode"]["runtime_state"] == CleanlinessState.MONITORING.value
    assert response.json()["mode"]["next_run_at"] is not None
    assert response.json()["transition"]["trigger"] == "verification_passed"


def test_uncertain_result_schedules_retry_and_retry_can_start(client: TestClient) -> None:
    register_mode(client)
    assert start_analysis(client).status_code == 200

    uncertain = submit_result(client, "uncertain")
    retried = start_analysis(client)

    assert uncertain.status_code == 200
    assert uncertain.json()["mode"]["runtime_state"] == CleanlinessState.RETRY_WAIT.value
    assert uncertain.json()["mode"]["next_run_at"] is not None
    assert uncertain.json()["transition"]["timer_action"] == "schedule_retry"
    assert retried.status_code == 200
    assert retried.json()["mode"]["runtime_state"] == CleanlinessState.ANALYZING.value
    assert retried.json()["mode"]["next_run_at"] is None
    assert retried.json()["transition"]["trigger"] == "retry_due"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/modes/cleanliness/analysis/start", None),
        ("/api/v1/modes/cleanliness/analysis/result", analysis_payload("clean")),
        ("/api/v1/modes/cleanliness/cleaning-complete", None),
    ],
)
def test_disabled_mode_rejects_flow_requests(
    client: TestClient,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    register_mode(client, enabled=False)

    response = client.post(path, json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "Mode 'cleanliness' is disabled."


def test_analysis_result_is_rejected_when_not_expected(client: TestClient) -> None:
    register_mode(client)

    response = submit_result(client, "clean")

    assert response.status_code == 409
    assert "not expected" in response.json()["detail"]


def test_regular_analysis_cannot_start_while_dirty(client: TestClient) -> None:
    register_mode(client)
    assert start_analysis(client).status_code == 200
    assert submit_result(client, "dirty").status_code == 200

    response = start_analysis(client)

    assert response.status_code == 409
    assert "not allowed from 'dirty'" in response.json()["detail"]


def test_invalid_interval_rolls_back_completed_transition(client: TestClient) -> None:
    register_mode(client, config={"interval_minutes": 0})
    assert start_analysis(client).status_code == 200

    response = submit_result(client, "clean")
    saved = client.get("/api/v1/modes/cleanliness")

    assert response.status_code == 409
    assert "invalid 'interval_minutes'" in response.json()["detail"]
    assert saved.json()["runtime_state"] == CleanlinessState.ANALYZING.value
    assert saved.json()["state_version"] == 1


def test_analysis_result_requires_area_assessments(client: TestClient) -> None:
    register_mode(client)
    assert start_analysis(client).status_code == 200
    payload = analysis_payload("clean")
    payload["areas"] = []

    response = client.post(
        "/api/v1/modes/cleanliness/analysis/result",
        json=payload,
    )

    assert response.status_code == 422
