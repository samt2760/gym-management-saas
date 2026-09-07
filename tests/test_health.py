from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import status


def test_health_reports_healthy_application_and_database(public_client):
    response = public_client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "status": "ok",
        "database": "ok",
    }


def test_health_reports_database_failure_and_logs_exception(
    public_client,
    caplog,
):
    connection = MagicMock()
    connection.__enter__.side_effect = RuntimeError("database unavailable")

    with patch("app.core.database.engine.connect", return_value=connection):
        response = public_client.get("/health")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {
        "status": "error",
        "database": "unavailable",
    }
    assert "Health check database failure" in caplog.text
