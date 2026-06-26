import logging

from big_data_model.pull_agent.chat_client import add_sys_manager_to_chat


def test_stub_returns_true_and_logs(caplog):
    caplog.set_level(logging.INFO, logger="big_data_model.pull_agent.chat_client")
    ok = add_sys_manager_to_chat("Linux操作系统", "运维经理")
    assert ok is True
    assert "Linux操作系统" in caplog.text
    assert "运维经理" in caplog.text
