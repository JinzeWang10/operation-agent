import pytest
from unittest.mock import AsyncMock
from app.agent.phase3 import ReportGenerator
from app.models import (
    IncidentRequest, AdapterResult, BaselineScanResult,
    InvestigationResult, Finding,
)
from app.config import Settings
from app.llm.client import LLMClient


@pytest.fixture
def request_fixture():
    return IncidentRequest(system_code="SBYL", influence_area="总公司")


@pytest.fixture
def phase1_result():
    return BaselineScanResult(
        results=[AdapterResult(adapter_name="bpc", data={"bpcAlarmtypeMap": {}})],
        total_adapters=1,
    )


@pytest.fixture
def phase2_result():
    return InvestigationResult(
        findings=[Finding(source="summary", description="Found alerts")],
        rounds_used=1,
        terminated_by="llm",
    )


@pytest.mark.asyncio
async def test_generate_with_llm(request_fixture, phase1_result, phase2_result):
    settings = Settings(llm_api_key="test", llm_base_url="http://test/v1")
    llm = LLMClient(settings)
    llm.chat = AsyncMock(return_value=(
        "# 巡检报告\n\n"
        "## 概览\n\n"
        "发现若干异常告警，包括数据库复制槽延迟、长事务告警、Oracle表空间使用率告警等，详见以下各章节分析。\n\n"
        "## 告警详情\n\n"
        "- 复制槽延迟告警 x3\n"
        "- GaussDB长事务告警 x1\n"
        "- Oracle表空间使用率告警 x1\n"
    ))

    generator = ReportGenerator(llm)
    report = await generator.generate(request_fixture, phase1_result, phase2_result)

    assert "巡检报告" in report
    assert "概览" in report


@pytest.mark.asyncio
async def test_generate_fallback_on_llm_error(request_fixture, phase1_result, phase2_result):
    settings = Settings(llm_api_key="test", llm_base_url="http://test/v1")
    llm = LLMClient(settings)
    llm.chat = AsyncMock(side_effect=Exception("LLM down"))

    generator = ReportGenerator(llm)
    report = await generator.generate(request_fixture, phase1_result, phase2_result)

    assert "模板生成" in report
    assert "SBYL" in report
    assert "Found alerts" in report


@pytest.mark.asyncio
async def test_generate_fallback_on_empty_response(request_fixture, phase1_result, phase2_result):
    settings = Settings(llm_api_key="test", llm_base_url="http://test/v1")
    llm = LLMClient(settings)
    llm.chat = AsyncMock(return_value="")

    generator = ReportGenerator(llm)
    report = await generator.generate(request_fixture, phase1_result, phase2_result)

    assert "模板生成" in report
