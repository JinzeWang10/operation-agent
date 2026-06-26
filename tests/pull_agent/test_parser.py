import pytest

from big_data_model.pull_agent.parser import parse_llm_output, ParseError

ASSETS = ["Linux操作系统", "GaussDB"]


def test_parse_ok():
    raw = '{"status":"ok","actions":[{"asset":"Linux操作系统","role":"运维经理"}]}'
    result = parse_llm_output(raw, ASSETS)
    assert result["status"] == "ok"
    assert result["actions"] == [{"asset": "Linux操作系统", "role": "运维经理"}]
    assert result["unresolved"] == []


def test_parse_failed():
    raw = '{"status":"failed","actions":[],"unresolved":["DBA"],"message":"x"}'
    result = parse_llm_output(raw, ASSETS)
    assert result["status"] == "failed"
    assert result["unresolved"] == ["DBA"]
    assert result["message"] == "x"


def test_parse_partial():
    raw = '{"status":"partial","actions":[{"asset":"GaussDB","role":"开发经理"}],"unresolved":["X"],"message":"y"}'
    result = parse_llm_output(raw, ASSETS)
    assert result["status"] == "partial"
    assert len(result["actions"]) == 1


def test_parse_invalid_json():
    with pytest.raises(ParseError):
        parse_llm_output("not json at all", ASSETS)


def test_parse_unknown_asset_rejected():
    raw = '{"status":"ok","actions":[{"asset":"UnknownSys","role":"运维经理"}]}'
    with pytest.raises(ParseError, match="unknown asset"):
        parse_llm_output(raw, ASSETS)


def test_parse_unknown_role_rejected():
    raw = '{"status":"ok","actions":[{"asset":"GaussDB","role":"CEO"}]}'
    with pytest.raises(ParseError, match="unknown role"):
        parse_llm_output(raw, ASSETS)


def test_parse_invalid_status():
    raw = '{"status":"success","actions":[]}'
    with pytest.raises(ParseError, match="invalid status"):
        parse_llm_output(raw, ASSETS)


def test_parse_strips_code_fence():
    raw = '```json\n{"status":"ok","actions":[]}\n```'
    result = parse_llm_output(raw, ASSETS)
    assert result["status"] == "ok"
