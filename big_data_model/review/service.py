"""复核台业务组装:机器案例(只读) + overlay(人工) → 前端 DTO / 导出合并版。

机器抽取来自 CaseStore(cases.jsonl);overlay 来自 PG。DTO 里每个可编辑字段都给
``machine``(机器原值)与 ``value``(叠加人工后的现值),前端并排显示。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from big_data_model.incident.knowledge import normalize
from big_data_model.incident.knowledge.case_store import Case, CaseStore
from big_data_model.knowledge_pipeline import taxonomy
from big_data_model.review import overlay as overlay_mod
from big_data_model.review.overlay import EDITABLE_FIELDS, OverlayEntry
from big_data_model.review.priority import review_priority

DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parents[1] / "knowledge_pipeline" / "out" / "cases.jsonl"
)


def _first(raw: dict, *keys: str) -> str:
    for k in keys:
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _meta(case: Case) -> dict:
    return (case.原始 or {}).get("_kp_meta", {}) if isinstance(case.原始, dict) else {}


def _machine_fields(case: Case) -> dict:
    rc = case.回填
    m = _meta(case)
    return {
        "系统": case.系统 or "",
        "类别": (rc.类别 if rc else "") or "",
        "定位对象": (rc.定位对象 if rc else "") or "",
        "描述": (rc.描述 if rc else "") or "",
        "有效性": str(m.get("有效性", "") or ""),
        "is_invalid_flag": bool(m.get("is_invalid_flag", False)),
        "低置信": bool(m.get("低置信", False)),
    }


def _evidence(case: Case) -> dict:
    raw = case.原始 or {}
    return {
        "标题": _first(raw, "event_title"),
        "工单描述": _first(raw, "event_describe"),
        "根因文本": _first(raw, "fault_reason", "fault_reason.1"),
        "处置文本": _first(raw, "solution_conclusion", "solution_details", "solution_record", "solution_record.1"),
        "现场摘要": case.现场摘要 or "",
        "症状标签": _meta(case).get("症状标签", []) or [],
        "影响范围": str(_meta(case).get("影响范围", "") or ""),
        "发生时间": case.发生时间 or "",
    }


def _case_dto(case: Case, entry: Optional[OverlayEntry]) -> dict:
    mf = _machine_fields(case)
    patch = entry.patch if entry else {}

    def fld(key: str) -> dict:
        machine = mf[key]
        return {"machine": machine, "value": patch.get(key, machine)}

    prio, reasons = review_priority(
        系统=mf["系统"], 类别=mf["类别"], 定位对象=mf["定位对象"], 描述=mf["描述"],
        有效性=mf["有效性"], is_invalid_flag=mf["is_invalid_flag"], 低置信=mf["低置信"],
    )
    sys_res = normalize.resolve_system(mf["系统"])
    return {
        "event_id": case.事件ID,
        "系统": {**fld("系统"), "canonical": sys_res.canonical, "in_vocab": sys_res.resolved},
        "类别": fld("类别"),
        "定位对象": fld("定位对象"),
        "描述": fld("描述"),
        "有效性": fld("有效性"),
        "证据": _evidence(case),
        "review": {
            "priority": prio,
            "reasons": reasons,
            "reviewed": bool(entry.reviewed) if entry else False,
            "reviewer": entry.reviewer if entry else None,
            "patched_fields": [k for k in EDITABLE_FIELDS if k in patch],
            "version": entry.version if entry else None,
        },
    }


def build_cases(
    cases_path: Path | str = DEFAULT_CASES_PATH,
    overlay_map: Optional[dict[str, OverlayEntry]] = None,
) -> list[dict]:
    """全量 DTO(机器 + overlay 叠加 + 优先级)。"""
    if overlay_map is None:
        overlay_map = overlay_mod.latest_by_event()
    cases = CaseStore(Path(cases_path)).all()
    return [_case_dto(c, overlay_map.get(c.事件ID)) for c in cases]


def categories() -> list[dict]:
    """类别下拉源(代码 + 说明)。"""
    return [{"code": c, "desc": d} for c, d in taxonomy.ROOT_CAUSE_CATEGORIES.items()]


def _apply_patch(case_dict: dict, patch: dict) -> dict:
    d = json.loads(json.dumps(case_dict, ensure_ascii=False))  # 深拷贝
    if "系统" in patch:
        d["系统"] = patch["系统"]
    rc_keys = {"类别", "定位对象", "描述"} & set(patch)
    if rc_keys:
        rc = d.get("回填") or {"类别": "", "定位对象": "", "描述": ""}
        for k in rc_keys:
            rc[k] = patch[k]
        d["回填"] = rc
    if "有效性" in patch:
        d.setdefault("原始", {}).setdefault("_kp_meta", {})["有效性"] = patch["有效性"]
    return d


def export_reviewed(
    cases_path: Path | str = DEFAULT_CASES_PATH,
    overlay_map: Optional[dict[str, OverlayEntry]] = None,
) -> str:
    """机器 + overlay 合并后的干净 JSONL(下游可直接 CaseStore 回读)。"""
    if overlay_map is None:
        overlay_map = overlay_mod.latest_by_event()
    lines: list[str] = []
    for case in CaseStore(Path(cases_path)).all():
        d = case.model_dump()
        entry = overlay_map.get(case.事件ID)
        if entry and entry.patch:
            d = _apply_patch(d, entry.patch)
        lines.append(json.dumps(d, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def validate_patch(patch: dict) -> None:
    """服务端校验:枚举字段只允许合法值;非法直接拒(ValueError)。"""
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是对象")
    for k in patch:
        if k not in EDITABLE_FIELDS:
            raise ValueError(f"不可编辑字段: {k}")
    if "类别" in patch and not taxonomy.is_valid(str(patch["类别"])):
        raise ValueError(f"非法类别: {patch['类别']}")
    if "有效性" in patch and str(patch["有效性"]).strip().lower() not in ("valid", "invalid"):
        raise ValueError(f"非法有效性: {patch['有效性']}")
