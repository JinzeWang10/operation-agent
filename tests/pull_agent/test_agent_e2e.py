import pytest

from big_data_model.pull_agent.agent import handle_message


pytestmark = pytest.mark.e2e


async def test_e2e_pull_two_linux_gauss_ops():
    result = await handle_message("请拉Linux操作系统和GaussDB的运维经理")
    assert result["status"] == "ok"
    called = {(c["asset"], c["role"]) for c in result["called"]}
    assert ("Linux操作系统", "运维经理") in called
    assert ("GaussDB", "运维经理") in called


async def test_e2e_unspecified_role_pulls_both():
    result = await handle_message("把智能客服系统的人都拉进来")
    assert result["status"] == "ok"
    called = {(c["asset"], c["role"]) for c in result["called"]}
    assert ("智能客服系统", "运维经理") in called
    assert ("智能客服系统", "开发经理") in called


async def test_e2e_nickname_mapping():
    result = await handle_message("拉一下高斯的开发")
    assert result["status"] == "ok"
    called = {(c["asset"], c["role"]) for c in result["called"]}
    assert ("GaussDB", "开发经理") in called


async def test_e2e_ambiguous_returns_failed():
    result = await handle_message("拉个DBA过来")
    assert result["status"] == "failed"
    assert result["called"] == []
