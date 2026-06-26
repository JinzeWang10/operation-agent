import pytest
from big_data_model.models import (
    IncidentRequest, AdapterResult, BaselineScanResult,
    InvestigationResult, Finding,
)
from big_data_model.agent.prompts import (
    format_adapter_data, format_phase1_summary,
    build_phase2_prompt, build_phase3_prompt,
)


def test_format_bpc_data():
    data = {"bpcAlarmtypeMap": {"TestSys": {
        "2026-01-19 15:00:00": {"duration": "100", "rr_rate": "99.9", "succ_rate": "100.0", "trans_count": "500"},
    }}}
    text = format_adapter_data("bpc", data)
    assert "TestSys" in text
    assert "100ms" in text
    assert "99.9%" in text


def test_format_database_with_alerts():
    data = {"hostAlarmVO": [
        {"host": "1.2.3.4", "alertName": "Test Alert", "desc": "desc", "state": "未恢复"},
    ], "dbinfo": []}
    text = format_adapter_data("database", data)
    assert "活跃告警 (1)" in text
    assert "Test Alert" in text


def test_format_component_with_failures():
    data = {"componentVOList": [
        {"componentName": "redis", "clusterState": "正常", "instanceStateVOS": [
            {"ip": "1.1.1.1", "port": "7001", "role": "master", "state": "FAILED"},
            {"ip": "2.2.2.2", "port": "7001", "role": "master", "state": "RUNNING"},
        ]},
    ]}
    text = format_adapter_data("component", data)
    assert "1 运行中, 1 故障" in text
    assert "[FAILED] 1.1.1.1:7001" in text


def test_format_phase1_summary():
    result = BaselineScanResult(
        results=[
            AdapterResult(adapter_name="bpc", data={"bpcAlarmtypeMap": {}}),
            AdapterResult(adapter_name="prometheus", data={"tcpNodes": "10", "tcpAbnormalNodes": "0", "httpNodes": "0", "httpAbnormalNodes": "0"}),
        ],
        errors=[AdapterResult(adapter_name="database", error="timeout")],
        total_adapters=3,
    )
    text = format_phase1_summary(result)
    assert "BPC 业务交易监控" in text
    assert "Prometheus 网络监控" in text
    assert "不可达系统" in text
    assert "database" in text


def test_build_phase2_prompt():
    request = IncidentRequest(system_code="SBYL", influence_area="总公司")
    phase1 = BaselineScanResult(results=[], total_adapters=0)
    sys_prompt, user_msg = build_phase2_prompt(request, phase1, "2026-01-19 15:00:00", "2026-01-19 16:00:00")
    assert "SBYL" in sys_prompt
    assert "总公司" in sys_prompt
    assert "finish_investigation" in sys_prompt
    assert "基础巡检已完成" in user_msg


def test_build_phase3_prompt():
    request = IncidentRequest(system_code="SBYL", influence_area="总公司")
    phase1 = BaselineScanResult(results=[], total_adapters=0)
    phase2 = InvestigationResult(
        findings=[Finding(source="test", description="found something")],
        rounds_used=1, terminated_by="llm",
    )
    sys_prompt, context = build_phase3_prompt(request, phase1, phase2)
    assert "Markdown" in sys_prompt
    assert "SBYL" in context
    assert "found something" in context
