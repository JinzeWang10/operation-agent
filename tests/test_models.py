import pytest
from big_data_model.models import (
    IncidentRequest, AdapterResult, BaselineScanResult,
    Finding, InvestigationResult, InspectionReport,
)


def test_incident_request_defaults():
    req = IncidentRequest(system_code="SBYL", influence_area="总公司")
    assert req.system_code == "SBYL"
    assert req.influence_area == "总公司"
    assert req.time_window_minutes == 60


def test_incident_request_custom_window():
    req = IncidentRequest(system_code="X", influence_area="Y", time_window_minutes=30)
    assert req.time_window_minutes == 30


def test_adapter_result_success():
    r = AdapterResult(adapter_name="bpc", data={"key": "val"}, duration_ms=123.4)
    assert r.error is None
    assert r.data == {"key": "val"}


def test_adapter_result_error():
    r = AdapterResult(adapter_name="bpc", error="timeout", duration_ms=15000)
    assert r.data is None
    assert r.error == "timeout"


def test_baseline_scan_result_empty():
    result = BaselineScanResult(total_adapters=7)
    assert result.results == []
    assert result.errors == []


def test_investigation_result_defaults():
    result = InvestigationResult()
    assert result.terminated_by == "not_started"
    assert result.rounds_used == 0


def test_inspection_report():
    report = InspectionReport(
        incident_id="abc123",
        report_markdown="# Report",
        duration_seconds=45.2,
    )
    assert report.incident_id == "abc123"
