"""Stage 2:案例聚类 → LLM 蒸馏候选 Pattern(YAML,待人审)。

聚类是确定性的(按根因类别),蒸馏由 LLM 做;产物按 Pattern schema 校验后落盘到
候选目录,**不自动进库**。probe 名、症状标签、区分引用都在代码侧做合法性收敛,
LLM 给错不会污染库。
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from big_data_model.incident.knowledge.case_store import Case
from big_data_model.incident.knowledge.probes import PROBES
from big_data_model.incident.knowledge.schema import (
    PATTERN_ID_RE,
    SYMPTOM_TAGS,
    Pattern,
    Verification,
)
from big_data_model.knowledge_pipeline.extract import Completer, extract_json
from big_data_model.knowledge_pipeline.prompts import build_stage2_messages


def _case_meta(case: Case) -> dict:
    return (case.原始 or {}).get("_kp_meta", {}) if isinstance(case.原始, dict) else {}


def cluster_cases(
    cases: list[Case], *, min_size: int = 3
) -> list[tuple[str, str, list[Case]]]:
    """按根因类别聚类。返回 [(类别, 代表定位对象, cases)],仅保留 >= min_size 的簇。

    UNKNOWN 不参与蒸馏:它是"未能归类/无根因信息"的兜底桶,聚在一起提炼不出可用模式,
    只会产出垃圾 pattern,故直接排除。
    """
    groups: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        if c.回填 is None or (c.回填.类别 or "").strip().upper() == "UNKNOWN":
            continue
        groups[c.回填.类别].append(c)

    out: list[tuple[str, str, list[Case]]] = []
    for cat, members in sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True):
        if len(members) < min_size:
            continue
        # 代表定位对象:簇内出现最多的定位对象,仅用于提示,不参与命名
        targets: dict[str, int] = defaultdict(int)
        for m in members:
            targets[m.回填.定位对象] += 1
        rep = max(targets.items(), key=lambda kv: kv[1])[0]
        out.append((cat, rep, members))
    return out


def _case_to_prompt_dict(case: Case) -> dict:
    return {
        "事件ID": case.事件ID,
        "系统": case.系统,
        "现场摘要": case.现场摘要,
        "回填": case.回填.model_dump() if case.回填 else {},
        "症状标签": _case_meta(case).get("症状标签", []),
    }


def _coerce_verifications(raw: list) -> list[Verification]:
    out: list[Verification] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        probe = str(item.get("probe", "")).strip()
        if probe not in PROBES:  # 丢弃非法 probe,不让 schema 直接炸
            continue
        区分 = [
            r for r in (item.get("区分") or []) if isinstance(r, str) and PATTERN_ID_RE.match(r)
        ]
        out.append(Verification(probe=probe, 判定=str(item.get("判定", "")).strip(), 区分=区分))
    return out


@dataclass
class DistillResult:
    category: str
    pattern: Optional[Pattern]
    case_count: int
    ok: bool
    error: Optional[str] = None


def _id_prefix(category: str) -> str:
    """把类别代码净化为合法 pattern id 前缀(仅大写字母数字);兜底 UNKNOWN。"""
    p = re.sub(r"[^A-Z0-9]+", "", (category or "").upper())
    return p or "UNKNOWN"


def _build_pattern(category: str, members: list[Case], parsed: dict, seq: int) -> Pattern:
    verifs = _coerce_verifications(parsed.get("验证", []))
    if not verifs:
        raise ValueError("LLM 未给出任何合法 probe 的验证步骤")
    tags = [t for t in (parsed.get("症状标签") or []) if t in SYMPTOM_TAGS]
    src = [c.事件ID for c in members]
    return Pattern(
        id=f"PATTERN-{_id_prefix(category)}-{seq:02d}",
        名称=str(parsed.get("名称", "") or f"{category} 类故障模式").strip(),
        适用条件=str(parsed.get("适用条件", "") or "").strip(),
        现象=str(parsed.get("现象", "") or "").strip(),
        候选根因=[str(x).strip() for x in (parsed.get("候选根因") or []) if str(x).strip()]
        or ["(待人工补充)"],
        验证=verifs,
        排除=str(parsed.get("排除", "") or "").strip(),
        症状标签=tags,
        来源案例=src,
        备注=(str(parsed.get("备注", "") or "").strip() + f" [由 {len(members)} 例历史案例蒸馏,待人审]").strip(),
    )


async def distill_pattern(
    category: str,
    rep_target: str,
    members: list[Case],
    complete: Completer,
    *,
    seq: int = 1,
    retries: int = 2,
    transport_retries: int = 4,
) -> DistillResult:
    import asyncio

    case_dicts = [_case_to_prompt_dict(c) for c in members]
    messages = build_stage2_messages(category, rep_target, case_dicts)
    last_err: Optional[str] = None
    json_attempts = 0
    transport_attempts = 0
    while json_attempts <= retries and transport_attempts <= transport_retries:
        try:
            reply = await complete(messages)
            parsed = extract_json(reply)
            pattern = _build_pattern(category, members, parsed, seq)
            return DistillResult(category, pattern, len(members), ok=True)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = f"{type(e).__name__}: {e}"
            json_attempts += 1
            messages = messages + [
                {"role": "user", "content": "上次回复无法解析或不合法,请严格只输出一个符合结构的 JSON 对象,验证步骤的 probe 必须来自给定清单。"}
            ]
        except Exception as e:  # 连接/限流等传输层错误,退避重试
            last_err = f"{type(e).__name__}: {e}"
            transport_attempts += 1
            if transport_attempts > transport_retries:
                break
            await asyncio.sleep(min(2 ** transport_attempts, 30))
    return DistillResult(category, None, len(members), ok=False, error=last_err)


def write_candidate_yaml(pattern: Pattern, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{pattern.id}.yaml"
    data = pattern.model_dump()
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    return path
