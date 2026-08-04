"""复核台测试夹具:每个用例一个独立 sqlite overlay 库 + 一份小 cases.jsonl。"""
from pathlib import Path

import pytest

from big_data_model.incident.knowledge.case_store import Case, CaseStore, RootCause
from big_data_model.review.adapters import db


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    db.use_sqlite(tmp_path / "overlay.sqlite3")
    yield


def make_case(event_id, system, 类别=None, 定位对象="", 描述="", 有效性="valid",
              is_invalid=False, 低置信=False, occurred="2026-06-01T10:00:00",
              fault_reason="", 现场摘要=""):
    meta = {
        "有效性": 有效性, "is_invalid_flag": is_invalid, "低置信": 低置信,
        "症状标签": [], "影响范围": "",
    }
    回填 = RootCause(类别=类别, 定位对象=定位对象, 描述=描述) if 类别 else None
    return Case.model_validate(dict(
        事件ID=event_id, 系统=system, 发生时间=occurred, 来源="历史导入",
        现场摘要=现场摘要, 回填=回填,
        原始={"_kp_meta": meta, "fault_reason": fault_reason, "event_title": "标题"},
    ))


@pytest.fixture
def cases_file(tmp_path):
    """写一份覆盖 P0/P1/P2/免审 四类的小 cases.jsonl,返回路径。"""
    path = tmp_path / "cases.jsonl"
    store = CaseStore(path)
    store.append(make_case("P0-1", "车险核保系统", 类别="UNKNOWN",
                            描述="表空间100%导致只读", fault_reason="表空间满"))
    store.append(make_case("P2-1", "车险核保系统", 类别="UNKNOWN",
                            有效性="invalid", is_invalid=True, fault_reason="经核查无异常"))
    store.append(make_case("OK-1", "车险核保系统", 类别="DB",
                            定位对象="uwtfee表", 描述="慢SQL"))
    store.append(make_case("P1-1", "完全不存在的系统XYZ", 类别="DB",
                            定位对象="x表", 描述="慢SQL"))
    return path
