import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agent.orchestrator import Orchestrator
from app.agent.phase1 import BaselineScanner
from app.agent.phase2 import DeepInvestigator
from app.agent.phase3 import ReportGenerator
from app.models import (
    IncidentRequest, AdapterResult, BaselineScanResult,
    InvestigationResult, Finding,
)
from app.config import Settings


@pytest.fixture
def mock_scanner():
    scanner = MagicMock(spec=BaselineScanner)
    scanner.scan = AsyncMock(return_value=BaselineScanResult(
        results=[AdapterResult(adapter_name="bpc", data={"bpcAlarmtypeMap": {}})],
        total_adapters=7,
    ))
    return scanner


@pytest.fixture
def mock_investigator():
    inv = MagicMock(spec=DeepInvestigator)
    inv.investigate = AsyncMock(return_value=InvestigationResult(
        findings=[Finding(source="summary", description="No issues")],
        rounds_used=1,
        terminated_by="llm",
    ))
    return inv


@pytest.fixture
def mock_reporter():
    rep = MagicMock(spec=ReportGenerator)
    rep.generate = AsyncMock(return_value="# Report\nAll clear.")
    return rep


@pytest.mark.asyncio
async def test_orchestrator_full_pipeline(mock_scanner, mock_investigator, mock_reporter, settings):
    orchestrator = Orchestrator(mock_scanner, mock_investigator, mock_reporter, settings)
    request = IncidentRequest(system_code="SBYL", influence_area="总公司")

    report = await orchestrator.run(request)

    assert report.incident_id
    assert "Report" in report.report_markdown
    assert report.duration_seconds >= 0
    assert report.phases_summary["phase1"]["total_adapters"] == 7
    assert report.phases_summary["phase2"]["terminated_by"] == "llm"

    mock_scanner.scan.assert_called_once()
    mock_investigator.investigate.assert_called_once()
    mock_reporter.generate.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_phase2_failure(mock_scanner, mock_reporter, settings):
    """Phase 2 LLM failure — should still generate report via fallback."""
    inv = MagicMock(spec=DeepInvestigator)
    inv.investigate = AsyncMock(side_effect=Exception("LLM down"))

    orchestrator = Orchestrator(mock_scanner, inv, mock_reporter, settings)
    request = IncidentRequest(system_code="SBYL", influence_area="总公司")

    report = await orchestrator.run(request)

    assert report.phases_summary["phase2"]["terminated_by"] == "llm_unavailable"
    mock_reporter.generate.assert_called_once()
