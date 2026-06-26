"""knowledge 层测试:pattern schema 校验、probe 注册表约束、库加载。"""
from pathlib import Path

import pytest

from big_data_model.incident.knowledge import (
    PROBES,
    Pattern,
    load_library,
    load_pattern,
)

PATTERNS_DIR = (
    Path(__file__).resolve().parents[2]
    / "big_data_model"
    / "incident"
    / "knowledge"
    / "patterns"
)


def _minimal(**overrides) -> dict:
    data = {
        "id": "PATTERN-TEST-01",
        "名称": "测试模式",
        "适用条件": "任意系统",
        "现象": "某现象",
        "候选根因": ["某根因"],
        "验证": [{"probe": "log_keyword_hits", "判定": "出现某关键字", "区分": []}],
        "排除": "无某现象时不成立",
    }
    data.update(overrides)
    return data


# -- schema 校验 ------------------------------------------------------------


def test_minimal_pattern_validates():
    p = Pattern.model_validate(_minimal())
    assert p.状态 == "启用"
    assert p.版本 == 1


def test_unregistered_probe_rejected():
    bad = _minimal(验证=[{"probe": "db_long_tx", "判定": "x", "区分": []}])
    with pytest.raises(ValueError, match="未注册"):
        Pattern.model_validate(bad)


def test_bad_id_rejected():
    with pytest.raises(ValueError, match="命名"):
        Pattern.model_validate(_minimal(id="pattern-db-01"))


def test_unknown_field_rejected():
    # 手写 YAML 字段名打错必须报错,不能静默忽略
    with pytest.raises(ValueError):
        Pattern.model_validate(_minimal(近期命中=["INC-1"]))


def test_empty_verification_rejected():
    with pytest.raises(ValueError):
        Pattern.model_validate(_minimal(验证=[]))


def test_bad_discriminator_ref_rejected():
    bad = _minimal(
        验证=[{"probe": "log_keyword_hits", "判定": "x", "区分": ["不是id"]}]
    )
    with pytest.raises(ValueError, match="不是合法的 pattern id"):
        Pattern.model_validate(bad)


def test_bad_symptom_tag_rejected():
    with pytest.raises(ValueError):
        Pattern.model_validate(_minimal(症状标签=["latency"]))


# -- 示范 pattern 与库加载 ----------------------------------------------------


def test_shipped_patterns_load():
    lib = load_library(PATTERNS_DIR)
    assert len(lib.patterns) >= 2
    assert lib.warnings == []  # 出厂库的交叉引用必须完整
    assert lib.get("PATTERN-DB-SATURATION-01") is not None


def test_shipped_probes_exist_in_registry():
    lib = load_library(PATTERNS_DIR)
    for p in lib.patterns:
        for v in p.验证:
            assert v.probe in PROBES


def test_duplicate_id_rejected(tmp_path):
    src = (PATTERNS_DIR / "PATTERN-DB-SATURATION-01.yaml").read_text(
        encoding="utf-8"
    )
    (tmp_path / "a.yaml").write_text(src, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(src, encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        load_library(tmp_path)


def test_unknown_cross_ref_warns(tmp_path):
    src = (PATTERNS_DIR / "PATTERN-DB-SATURATION-01.yaml").read_text(
        encoding="utf-8"
    )
    # 只放一个文件:它的「区分」指向 PATTERN-RELEASE-REGRESSION-01,不在库中
    (tmp_path / "a.yaml").write_text(src, encoding="utf-8")
    lib = load_library(tmp_path)
    assert any("PATTERN-RELEASE-REGRESSION-01" in w for w in lib.warnings)


def test_yaml_syntax_error_carries_filename(tmp_path):
    (tmp_path / "bad.yaml").write_text("id: [未闭合", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.yaml"):
        load_library(tmp_path)


def test_retired_pattern_excluded_from_prompt(tmp_path):
    import yaml as _yaml

    data = _minimal(id="PATTERN-TEST-02", 状态="废止")
    (tmp_path / "t.yaml").write_text(
        _yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )
    lib = load_library(tmp_path)
    assert lib.patterns and lib.active() == []
    assert lib.to_prompt() == ""


# -- prompt 渲染 --------------------------------------------------------------


def test_to_prompt_compact_and_complete():
    lib = load_library(PATTERNS_DIR)
    text = lib.to_prompt()
    assert "[PATTERN-DB-SATURATION-01 v1]" in text
    assert "db_instance_status" in text
    assert "排除:" in text
    # 全量注入的前提是紧凑:单条不超过 ~15 行
    for p in lib.active():
        assert len(p.to_prompt().splitlines()) <= 15
