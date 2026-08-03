"""Stage 1:事件行 → Case(案例库,来源=历史导入)。

流程:确定性解析(parse_row)→ LLM 萃取根因/摘要 → 组装 Case 并按 schema 校验。
LLM 只负责"读文本+快照写根因",结构与校验归代码。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from big_data_model.incident.knowledge.case_store import Case, RootCause
from big_data_model.knowledge_pipeline import taxonomy
from big_data_model.knowledge_pipeline.parse import ParsedRow, parse_row

# 异步补全契约:LLMClient.chat 即符合(messages -> content 字符串)
Completer = Callable[[list[dict]], Awaitable[str]]

_JSON_RE = re.compile(r"\{.*\}", re.S)


def extract_json(text: str) -> dict:
    """从 LLM 回复里抠出 JSON 对象(容忍 ```json 代码块与前后噪声)。"""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = _JSON_RE.search(s)
        if not m:
            raise
        return json.loads(m.group(0))


@dataclass
class ExtractResult:
    order_number: str
    case: Optional[Case]
    ok: bool
    error: Optional[str] = None


def _build_case(row: ParsedRow, parsed_llm: dict) -> Case:
    rc_in = parsed_llm.get("回填") or {}
    root = RootCause(
        类别=taxonomy.coerce(str(rc_in.get("类别", ""))),
        定位对象=str(rc_in.get("定位对象", "") or "").strip() or "(未定位)",
        描述=str(rc_in.get("描述", "") or "").strip(),
    )
    validity = str(parsed_llm.get("有效性", "")).strip().lower()
    meta = {
        "有效性": validity or ("invalid" if row.is_invalid else "valid"),
        "is_invalid_flag": row.is_invalid,
        "影响范围": row.affected_business,  # 与"故障系统"分开的维度(原并入 system 造脏键)
        "症状标签": row.symptom_tags,
        "低置信": bool(parsed_llm.get("低置信", False)) or bool(row.parse_error),
        "备注": str(parsed_llm.get("备注", "") or ""),
        "parse_error": row.parse_error,
    }
    return Case(
        事件ID=row.order_number,
        系统=row.system,
        发生时间=row.occurred_iso,
        来源="历史导入",
        现场摘要=str(parsed_llm.get("现场摘要", "") or "").strip(),
        假设轨迹="",
        Top3=[],
        未命中已知模式=False,
        回填=root,
        回填时间=row.closed_iso,
        原始={**row.raw, "_kp_meta": meta},
    )


async def extract_case(
    row: ParsedRow, complete: Completer, *, retries: int = 2, transport_retries: int = 4
) -> ExtractResult:
    """萃取一行。两类重试分开计数:

    - JSON 解析/校验失败 → 追加纠偏提示重试(retries 次);
    - 连接/限流等传输层错误 → 指数退避重试(transport_retries 次),
      公有云端点(如 DashScope)在并发下常见瞬时断连,一次抖动不应废掉整行。
    """
    import asyncio

    from big_data_model.knowledge_pipeline.prompts import build_stage1_messages

    messages = build_stage1_messages(row)
    last_err: Optional[str] = None
    json_attempts = 0
    transport_attempts = 0
    while json_attempts <= retries and transport_attempts <= transport_retries:
        try:
            reply = await complete(messages)
            parsed = extract_json(reply)
            case = _build_case(row, parsed)
            return ExtractResult(row.order_number, case, ok=True)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = f"{type(e).__name__}: {e}"
            json_attempts += 1
            # 纠偏:追加一条"只输出 JSON"的提示后重试
            messages = messages + [
                {"role": "user", "content": "上次回复无法解析为合法 JSON,请严格只输出一个 JSON 对象。"}
            ]
        except Exception as e:  # 连接/限流/超时等传输层错误
            last_err = f"{type(e).__name__}: {e}"
            transport_attempts += 1
            if transport_attempts > transport_retries:
                break
            await asyncio.sleep(min(2 ** transport_attempts, 30))  # 2/4/8/16s 退避
    return ExtractResult(row.order_number, None, ok=False, error=last_err)


async def extract_case_from_raw(raw_row: dict, complete: Completer, **kw) -> ExtractResult:
    return await extract_case(parse_row(raw_row), complete, **kw)
