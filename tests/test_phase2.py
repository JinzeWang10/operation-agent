import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from app.agent.phase2 import DeepInvestigator
from app.agent.tools import build_tool_definitions, execute_tool
from app.adapters.mock_adapters import create_default_registry
from app.config import Settings
from app.llm.client import LLMClient


@pytest.fixture
def registry():
    return create_default_registry()


def test_tool_definitions_count(registry):
    tools = build_tool_definitions(registry)
    # 7 adapters + finish_investigation = 8 tools
    assert len(tools) == 8
    names = {t["function"]["name"] for t in tools}
    assert "query_bpc" in names
    assert "finish_investigation" in names


def test_tool_definitions_have_required_fields(registry):
    tools = build_tool_definitions(registry)
    for tool in tools:
        assert tool["type"] == "function"
        func = tool["function"]
        assert "name" in func
        assert "description" in func
        assert "parameters" in func


@pytest.mark.asyncio
async def test_execute_tool_adapter(registry):
    result_str = await execute_tool(
        "query_bpc",
        {"system_code": "X", "influence_area": "Y", "start_time": "2026-01-01 00:00:00", "end_time": "2026-01-01 01:00:00"},
        registry,
    )
    result = json.loads(result_str)
    assert "bpcAlarmtypeMap" in result


@pytest.mark.asyncio
async def test_execute_tool_finish():
    registry = create_default_registry()
    result_str = await execute_tool(
        "finish_investigation",
        {"summary": "Found 3 alerts"},
        registry,
    )
    result = json.loads(result_str)
    assert result["status"] == "investigation_finished"


@pytest.mark.asyncio
async def test_execute_tool_unknown_adapter():
    registry = create_default_registry()
    result_str = await execute_tool(
        "query_nonexistent",
        {"system_code": "X", "influence_area": "Y", "start_time": "a", "end_time": "b"},
        registry,
    )
    result = json.loads(result_str)
    assert "error" in result


@pytest.mark.asyncio
async def test_investigator_finish_immediately():
    """LLM calls finish_investigation on first round."""
    registry = create_default_registry()
    settings = Settings(llm_api_key="test", llm_base_url="http://test/v1")
    llm = LLMClient(settings)

    # Mock LLM to call finish_investigation
    mock_tc = MagicMock()
    mock_tc.id = "call_1"
    mock_tc.function.name = "finish_investigation"
    mock_tc.function.arguments = json.dumps({"summary": "All looks normal"})

    mock_message = MagicMock()
    mock_message.content = None
    mock_message.tool_calls = [mock_tc]
    llm.chat_with_tools = AsyncMock(return_value=mock_message)

    investigator = DeepInvestigator(llm, registry, max_rounds=3, timeout=60)
    result = await investigator.investigate("system prompt", "user message")

    assert result.terminated_by == "llm"
    assert result.rounds_used == 1
    assert any("All looks normal" in f.description for f in result.findings)


@pytest.mark.asyncio
async def test_investigator_query_then_finish():
    """LLM queries an adapter, then finishes."""
    registry = create_default_registry()
    settings = Settings(llm_api_key="test", llm_base_url="http://test/v1")
    llm = LLMClient(settings)

    # Round 1: query_database
    tc1 = MagicMock()
    tc1.id = "call_1"
    tc1.function.name = "query_database"
    tc1.function.arguments = json.dumps({
        "system_code": "SBYL", "influence_area": "总公司",
        "start_time": "2026-01-19 15:00:00", "end_time": "2026-01-19 15:30:00",
    })
    msg1 = MagicMock()
    msg1.content = None
    msg1.tool_calls = [tc1]

    # Round 2: finish_investigation
    tc2 = MagicMock()
    tc2.id = "call_2"
    tc2.function.name = "finish_investigation"
    tc2.function.arguments = json.dumps({"summary": "DB alerts found"})
    msg2 = MagicMock()
    msg2.content = None
    msg2.tool_calls = [tc2]

    llm.chat_with_tools = AsyncMock(side_effect=[msg1, msg2])

    investigator = DeepInvestigator(llm, registry, max_rounds=3, timeout=60)
    result = await investigator.investigate("sys", "usr")

    assert result.terminated_by == "llm"
    assert result.rounds_used == 2
    assert len(result.findings) >= 2  # query result + summary


@pytest.mark.asyncio
async def test_investigator_llm_error():
    """LLM call fails — investigation stops with error."""
    registry = create_default_registry()
    settings = Settings(llm_api_key="test", llm_base_url="http://test/v1")
    llm = LLMClient(settings)
    llm.chat_with_tools = AsyncMock(side_effect=Exception("LLM unavailable"))

    investigator = DeepInvestigator(llm, registry, max_rounds=3, timeout=60)
    result = await investigator.investigate("sys", "usr")

    assert result.terminated_by == "llm_error"
    assert len(result.errors) > 0
