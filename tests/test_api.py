import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


def test_health_endpoint():
    from big_data_model.main import app
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert len(data["adapters"]) == 7
    assert "bpc" in data["adapters"]


def test_incidents_endpoint_returns_report():
    """Test the endpoint structure — mocks LLM to avoid real calls."""
    from big_data_model.main import app, orchestrator
    from big_data_model.models import InspectionReport

    mock_report = InspectionReport(
        incident_id="test123",
        report_markdown="# Test Report",
        phases_summary={"phase1": {}, "phase2": {}, "phase3": {}},
        duration_seconds=1.0,
    )
    orchestrator.run = AsyncMock(return_value=mock_report)

    client = TestClient(app)
    response = client.post("/api/v1/incidents", json={
        "system_code": "SBYL",
        "influence_area": "总公司",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["incident_id"] == "test123"
    assert "Test Report" in data["report_markdown"]
