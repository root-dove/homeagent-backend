from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.health import database_is_ready
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_liveness_does_not_require_database(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {"application": "ok"}


def test_database_check_executes_select() -> None:
    with patch("app.api.v1.health.engine.connect") as connect:
        connection = connect.return_value.__enter__.return_value

        assert database_is_ready() is True
        connection.execute.assert_called_once()


def test_database_check_handles_sqlalchemy_error() -> None:
    with patch(
        "app.api.v1.health.engine.connect",
        side_effect=SQLAlchemyError("database unavailable"),
    ):
        assert database_is_ready() is False


def test_readiness_succeeds_when_database_is_available(client: TestClient) -> None:
    app.dependency_overrides[database_is_ready] = lambda: True

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"


def test_readiness_fails_when_database_is_unavailable(client: TestClient) -> None:
    app.dependency_overrides[database_is_ready] = lambda: False

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["database"] == "unavailable"
