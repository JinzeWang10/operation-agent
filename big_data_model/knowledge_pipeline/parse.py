"""确定性解析层:事件行 → 结构化视图(现场摘要 + 症状标签 + 关键字段)。

不调用 LLM。``monitor_data`` 复用 incident.features.extract,与线上 Agent 的
现场快照同一套口径。解析失败不致命:brief 置空、记 parse_error,LLM 仍可只凭
工单文本萃取根因。
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from big_data_model.incident import features
from big_data_model.incident.knowledge.schema import SYMPTOM_TAGS


def _first_str(row: dict, *keys: str) -> str:
    """按优先级取第一个非空字符串字段(兼容重名列的 .1 后缀)。"""
    parts: list[str] = []
    for k in keys:
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return "\n".join(dict.fromkeys(parts))  # 去重保序


def _as_bool_invalid(v: Any) -> bool:
    # is_invalid: 1 表示无效事件(误报/自动恢复)
    try:
        return int(v) == 1
    except (TypeError, ValueError):
        return False


def parse_monitor_data(raw: Any) -> tuple[Optional[dict], Optional[str]]:
    """把 monitor_data(Python dict repr 字符串或已是 dict)解析为 payload。

    返回 (payload, error)。payload 为 features.extract 期望的 {'data': [...]} 结构。
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "monitor_data 为空"
    if isinstance(raw, dict):
        return raw, None
    if not isinstance(raw, str):
        return None, f"monitor_data 类型异常: {type(raw).__name__}"
    try:
        # 上游是 Python dict 的 repr(单引号、None/True/False),用 literal_eval 而非 json
        obj = ast.literal_eval(raw)
    except (ValueError, SyntaxError) as e:
        # 兜底尝试 JSON
        try:
            obj = json.loads(raw)
        except Exception:
            return None, f"monitor_data 解析失败: {e}"
    if not isinstance(obj, dict):
        return None, "monitor_data 顶层不是对象"
    return obj, None


def _symptom_tags(bag: features.FeatureBag) -> list[str]:
    """聚合 BPC 各系统 symptom_type → 事件级症状标签(仅取合法标签集)。"""
    tags: set[str] = set()
    if bag.bpc and bag.bpc.present:
        for s in bag.bpc.systems:
            for flag in s.symptom_type.split("+"):
                if flag in SYMPTOM_TAGS:
                    tags.add(flag)
    # 按 SYMPTOM_TAGS 固定顺序输出
    return [t for t in SYMPTOM_TAGS if t in tags]


@dataclass
class ParsedRow:
    order_number: str
    system: str
    occurred_iso: str
    closed_iso: str
    is_invalid: bool
    title: str
    describe: str
    fault_text: str      # tna + tasi 两处 fault_reason 合并
    solution_text: str   # tna + tasi 两处 solution_record + solution_details 合并
    brief: dict          # features.to_llm_brief(),解析失败为 {}
    symptom_tags: list[str]
    parse_error: Optional[str] = None
    raw: dict = field(default_factory=dict)

    def brief_json(self) -> str:
        return json.dumps(self.brief, ensure_ascii=False, indent=2) if self.brief else "(现场快照解析失败或为空)"


def parse_row(row: dict) -> ParsedRow:
    order_number = str(row.get("order_number") or "").strip()
    system = _first_str(row, "fault_system", "affected_business") or "(未知系统)"
    occurred = str(row.get("happen_time") or row.get("order_create_time") or "").strip()
    closed = str(row.get("order_end_time") or row.get("recovery_time") or "").strip()

    payload, err = parse_monitor_data(row.get("monitor_data"))
    brief: dict = {}
    symptom_tags: list[str] = []
    if payload is not None:
        try:
            bag = features.extract(payload)
            brief = bag.to_llm_brief()
            symptom_tags = _symptom_tags(bag)
        except Exception as e:  # 现场解析永不阻断萃取
            err = f"features.extract 失败: {e}"

    return ParsedRow(
        order_number=order_number,
        system=system,
        occurred_iso=occurred,
        closed_iso=closed,
        is_invalid=_as_bool_invalid(row.get("is_invalid")),
        title=_first_str(row, "event_title"),
        describe=_first_str(row, "event_describe"),
        fault_text=_first_str(row, "fault_reason", "fault_reason.1"),
        solution_text=_first_str(
            row, "solution_conclusion", "solution_details", "solution_record", "solution_record.1"
        ),
        brief=brief,
        symptom_tags=symptom_tags,
        parse_error=err,
        raw=row,
    )
