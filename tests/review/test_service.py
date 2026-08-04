"""service:机器+overlay 合并 DTO、优先级、导出。"""
import json

from big_data_model.incident.knowledge.case_store import CaseStore
from big_data_model.review import overlay, service


def _by_id(dtos):
    return {d["event_id"]: d for d in dtos}


def test_build_cases_priority(cases_file):
    d = _by_id(service.build_cases(cases_file))
    assert d["P0-1"]["review"]["priority"] == "P0"
    assert d["P2-1"]["review"]["priority"] == "P2"
    assert d["OK-1"]["review"]["priority"] is None
    assert d["P1-1"]["review"]["priority"] == "P1"


def test_dto_shows_machine_and_evidence(cases_file):
    d = _by_id(service.build_cases(cases_file))["P0-1"]
    assert d["类别"]["machine"] == "UNKNOWN"
    assert d["类别"]["value"] == "UNKNOWN"        # 未改时 value==machine
    assert d["证据"]["根因文本"] == "表空间满"
    assert d["系统"]["in_vocab"] is True           # 车险核保系统在种子词表


def test_overlay_applied_in_dto(cases_file):
    overlay.save_edit("P0-1", {"类别": "DB"}, reviewed=True, reviewer="张三", base_version=None)
    d = _by_id(service.build_cases(cases_file))["P0-1"]
    assert d["类别"]["machine"] == "UNKNOWN" and d["类别"]["value"] == "DB"
    assert d["review"]["reviewed"] is True
    assert d["review"]["patched_fields"] == ["类别"]


def test_export_merges_overlay(cases_file):
    overlay.save_edit("P0-1", {"类别": "DB", "定位对象": "表空间"}, reviewed=True,
                      reviewer="张三", base_version=None)
    out = service.export_reviewed(cases_file)
    merged = {json.loads(l)["事件ID"]: json.loads(l) for l in out.splitlines()}
    assert merged["P0-1"]["回填"]["类别"] == "DB"
    assert merged["P0-1"]["回填"]["定位对象"] == "表空间"
    # 未改的保持原样
    assert merged["OK-1"]["回填"]["类别"] == "DB"


def test_export_roundtrips_through_casestore(cases_file, tmp_path):
    out = service.export_reviewed(cases_file)
    p = tmp_path / "merged.jsonl"
    p.write_text(out, encoding="utf-8")
    assert len(CaseStore(p).all()) == 4  # 合并版仍可被 CaseStore 回读


def test_validate_patch_rejects_bad_values():
    import pytest
    with pytest.raises(ValueError):
        service.validate_patch({"类别": "不存在的类"})
    with pytest.raises(ValueError):
        service.validate_patch({"有效性": "maybe"})
    with pytest.raises(ValueError):
        service.validate_patch({"乱塞字段": "x"})
    service.validate_patch({"类别": "DB", "有效性": "invalid", "描述": "任意文本"})
