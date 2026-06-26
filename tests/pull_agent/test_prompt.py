from big_data_model.pull_agent.prompt import build_prompt


def test_build_prompt_contains_all_sections():
    msgs = build_prompt("拉Linux的运维经理", ["Linux操作系统", "GaussDB"])
    assert isinstance(msgs, list)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    sys = msgs[0]["content"]
    assert "Linux操作系统" in sys
    assert "GaussDB" in sys
    assert "运维经理" in sys
    assert "开发经理" in sys
    assert "status" in sys
    assert msgs[1]["content"] == "拉Linux的运维经理"


def test_build_prompt_escapes_json_braces():
    """JSON 示例中的大括号不应被 .format 吞掉."""
    msgs = build_prompt("x", ["A"])
    sys = msgs[0]["content"]
    assert '{"status":"ok"' in sys
