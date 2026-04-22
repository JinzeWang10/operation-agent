from unittest.mock import AsyncMock, patch

import pytest

from app.pull_agent.agent import handle_message


@pytest.mark.asyncio
async def test_handle_message_ok():
    fake = '{"status":"ok","actions":[{"asset":"Linux操作系统","role":"运维经理"},{"asset":"GaussDB","role":"运维经理"}]}'
    with patch("app.pull_agent.agent._llm_chat", new=AsyncMock(return_value=fake)):
        result = await handle_message("拉Linux和GaussDB的运维经理")
    assert result["status"] == "ok"
    assert len(result["called"]) == 2
    assert all(c["success"] for c in result["called"])


@pytest.mark.asyncio
async def test_handle_message_failed():
    fake = '{"status":"failed","actions":[],"unresolved":["DBA"],"message":"无法确认"}'
    with patch("app.pull_agent.agent._llm_chat", new=AsyncMock(return_value=fake)):
        result = await handle_message("拉个DBA")
    assert result["status"] == "failed"
    assert result["called"] == []
    assert result["unresolved"] == ["DBA"]


@pytest.mark.asyncio
async def test_handle_message_chat_api_raises():
    fake = '{"status":"ok","actions":[{"asset":"Linux操作系统","role":"运维经理"}]}'

    def boom(*_):
        raise RuntimeError("network down")

    with patch("app.pull_agent.agent._llm_chat", new=AsyncMock(return_value=fake)), \
         patch("app.pull_agent.agent.add_sys_manager_to_chat", side_effect=boom):
        result = await handle_message("拉Linux的运维经理")
    assert result["called"][0]["success"] is False
    assert "network down" in result["called"][0]["error"]


@pytest.mark.asyncio
async def test_handle_message_parse_error():
    with patch("app.pull_agent.agent._llm_chat", new=AsyncMock(return_value="not json")):
        result = await handle_message("任意")
    assert result["status"] == "failed"
    assert "解析" in result["message"] or "parse" in result["message"].lower()
