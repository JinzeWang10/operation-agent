"""案例台账测试:模型校验、追加/读取、命中口径、复盘模板加载。"""
from datetime import datetime
from pathlib import Path

import pytest

from big_data_model.incident.knowledge import (
    Case,
    CaseStore,
    Hypothesis,
    RootCause,
    hit_rank,
)
from big_data_model.incident.knowledge.case_store import load_case_yaml

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "big_data_model"
    / "incident"
    / "knowledge"
    / "case_template.yaml"
)


def _case(incident_id="INM-1", system="SBYL", occurred="2026-06-11T10:32:00", **kw):
    data = dict(
        事件ID=incident_id,
        系统=system,
        发生时间=occurred,
        来源="agent",
        Top3=[
            Hypothesis(类别="DB", 定位对象="DB1", 置信度="高"),
            Hypothesis(类别="MW", 定位对象="Redis-Cluster-A", 置信度="中"),
            Hypothesis(类别="NET", 定位对象="核心交换", 置信度="低"),
        ],
    )
    data.update(kw)
    return Case.model_validate(data)


# -- 命中口径 -----------------------------------------------------------------


def test_hit_rank_top1():
    c = _case(回填=RootCause(类别="DB", 定位对象="DB1", 描述="慢 SQL"))
    assert hit_rank(c) == 1


def test_hit_rank_normalizes_case_and_spaces():
    c = _case(回填=RootCause(类别="db", 定位对象=" db1 "))
    assert hit_rank(c) == 1


def test_hit_rank_miss():
    c = _case(回填=RootCause(类别="APP", 定位对象="核保服务"))
    assert hit_rank(c) is None


def test_hit_rank_unfilled():
    assert hit_rank(_case()) is None


def test_category_must_also_match():
    # 定位对象相同但类别不同,不算命中——粒度标准是"类别 × 定位对象"
    c = _case(回填=RootCause(类别="HOST", 定位对象="DB1"))
    assert hit_rank(c) is None


# -- 台账读写 -----------------------------------------------------------------


def test_append_and_get(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    store.append(_case())
    got = store.get("INM-1")
    assert got is not None and got.系统 == "SBYL"


def test_append_only_last_version_wins(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    store.append(_case())  # 归档时:未回填
    store.append(_case(回填=RootCause(类别="DB", 定位对象="DB1")))  # 复盘后追加
    assert len(store.all()) == 1
    assert hit_rank(store.get("INM-1")) == 1
    # 审计轨迹保留:文件里仍是两行
    lines = (tmp_path / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_recent_by_system(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    store.append(_case("INM-1", occurred="2026-06-01T10:00:00"))
    store.append(_case("INM-2", occurred="2026-01-01T10:00:00"))  # 超 90 天
    store.append(_case("INM-3", system="其他系统", occurred="2026-06-05T10:00:00"))
    store.append(_case("INM-4", occurred="说不清"))  # 时间不可解析,不纳入
    got = store.recent_by_system("SBYL", days=90, now=datetime(2026, 6, 11))
    assert [c.事件ID for c in got] == ["INM-1"]


def test_hit_stats(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    store.append(_case("INM-1", 回填=RootCause(类别="DB", 定位对象="DB1")))
    store.append(
        _case("INM-2", 回填=RootCause(类别="MW", 定位对象="Redis-Cluster-A"))
    )
    store.append(_case("INM-3", 回填=RootCause(类别="APP", 定位对象="核保服务")))
    store.append(_case("INM-4"))  # 未回填
    stats = store.hit_stats()
    assert stats == {"已回填": 3, "top1": 1, "top3": 2, "未命中": 1}


def test_unknown_field_rejected():
    with pytest.raises(ValueError):
        Case.model_validate(
            dict(事件ID="x", 系统="s", 发生时间="t", 来源="agent", 值班反馈="采纳")
        )


def test_empty_store(tmp_path):
    store = CaseStore(tmp_path / "missing.jsonl")
    assert store.all() == []
    assert store.get("INM-1") is None


# -- 复盘模板 -----------------------------------------------------------------


def test_template_loads_as_valid_case():
    case = load_case_yaml(TEMPLATE)
    assert case.来源 == "人工复盘"
    assert case.回填 is not None and case.回填.类别 == "DB"


def test_template_roundtrips_through_store(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    store.append(load_case_yaml(TEMPLATE))
    assert store.get("INM-20260611-0000000") is not None
