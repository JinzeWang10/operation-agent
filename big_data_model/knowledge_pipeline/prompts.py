"""LLM prompt:Stage 1 根因萃取 / Stage 2 模式蒸馏。

两处均要求**只输出 JSON**(受约束输出),由 extract/distill 侧解析+schema 校验;
解析失败触发 batch 层的纠偏重试。
"""
from __future__ import annotations

import json

from big_data_model.incident.knowledge.probes import PROBES
from big_data_model.knowledge_pipeline import taxonomy
from big_data_model.knowledge_pipeline.parse import ParsedRow

# ── Stage 1:根因萃取 ────────────────────────────────────────────────

STAGE1_SYSTEM = """你是运维故障知识萃取助手。给你一条历史事件工单(含人工填写的根因/处置文本,
以及事发时的多源监控现场快照),请把它萃取成结构化的"故障案例知识"。

要点:
- 根因来自工单已有的"根因/处置"文本,不要凭空推断;文本与现场快照矛盾时以文本为准,并在低置信里说明。
- "定位对象"要具体到能缩小排查范围(系统/组件/实例/作业名),但不必到代码行。
- 现场快照可能为空或部分缺失,那就只依据文本萃取,并把低置信置为 true。
- 【描述必填,且与现场摘要分工不同】:"回填.描述"是**一句话根因结论**(为什么坏),
  "现场摘要"是**当时的现场现象**(看到什么);不要把根因只写进摘要而让描述留空。
  只要"根因/处置"文本里有任何指向原因的信息,"回填.描述"就必须写出来。
- 【禁止无根据的 UNKNOWN 空壳】:只要"根因/处置"文本含明确技术信息(如某表字段、某版本
  发布、某配置、某接口/作业报错),就必须归到具体类别并给出定位对象与描述,**不得**
  返回"类别=UNKNOWN、定位对象/描述留空"。仅当文本确为"经核查无异常/无根因信息"时,才用
  UNKNOWN 空壳。
- 严格只输出一个 JSON 对象,不要解释、不要 markdown 代码块。"""

STAGE1_OUTPUT_SCHEMA = """输出 JSON 结构(字段名用中文):
{
  "现场摘要": "一段话·现场现象:当时看到什么异常、什么是正常的(结合快照与工单)",
  "回填": {
    "类别": "从下方枚举里选一个代码",
    "定位对象": "根因落在的系统/组件/实例/作业,如 DB1、核保规则、夜间跑批",
    "描述": "【必填】一句话根因结论(为什么坏,可含触发因素);与现场摘要不同,不得留空"
  },
  "有效性": "valid 或 invalid(invalid=误报/阈值抖动/自动恢复、非真实故障)",
  "低置信": true 或 false,
  "备注": "低置信原因或补充说明,可留空"
}"""


def build_stage1_messages(row: ParsedRow) -> list[dict]:
    user = f"""{taxonomy.prompt_block()}

{STAGE1_OUTPUT_SCHEMA}

========== 事件工单 ==========
事件单号: {row.order_number}
受影响系统: {row.system}
发生时间: {row.occurred_iso}
工单标记 is_invalid: {"1(疑似无效/误报)" if row.is_invalid else "0"}
标题: {row.title or "(空)"}
描述: {row.describe or "(空)"}
人工填写-根因: {row.fault_text or "(空)"}
人工填写-处置/结论: {row.solution_text or "(空)"}
代码侧识别的症状标签: {", ".join(row.symptom_tags) or "(无)"}

========== 事发时监控现场快照(brief) ==========
{row.brief_json()}

请输出 JSON。"""
    return [
        {"role": "system", "content": STAGE1_SYSTEM},
        {"role": "user", "content": user},
    ]


# ── Stage 2:模式蒸馏 ────────────────────────────────────────────────

STAGE2_SYSTEM = """你是运维故障模式提炼专家。给你一组"根因同类"的历史案例,请从中提炼出一条
可复用的"故障模式(pattern)",供未来事件调查时作为优先验证假设。

要点:
- 提炼共性:现象要写这类故障的典型可观测信号,不要照抄单个案例的具体数值。
- "验证"里每条必须选用给定的 probe 清单中的一个 probe 名,并写清"判定"(看到什么算命中)。
- 若这些案例其实不构成一个清晰模式(过于杂糅),在备注里说明,仍尽力给出最合理的一条。
- 严格只输出一个 JSON 对象,不要解释、不要 markdown 代码块。"""


def _probe_catalog() -> str:
    lines = ["可用 probe(验证步骤只能从中选 probe 名):"]
    for name, p in PROBES.items():
        lines.append(f"- {name}: {p.returns}")
    return "\n".join(lines)


STAGE2_OUTPUT_SCHEMA = """输出 JSON 结构(字段名用中文):
{
  "名称": "简短模式名",
  "适用条件": "什么样的系统/场景适用",
  "现象": "这类故障的典型可观测现象(跨案例共性)",
  "候选根因": ["根因1", "根因2"],
  "验证": [
    {"probe": "从 probe 清单选名字", "判定": "看到什么算命中", "区分": []}
  ],
  "排除": "什么情况下本模式不成立",
  "症状标签": ["slow/errors/response_drop/volume_drop 里的子集,可空"],
  "备注": "可留空"
}"""


def build_stage2_messages(category: str, target: str, cases: list[dict]) -> list[dict]:
    case_lines = []
    for c in cases:
        rc = c.get("回填") or {}
        case_lines.append(
            f"- [{c.get('事件ID')}] 系统={c.get('系统')} "
            f"症状={','.join(c.get('症状标签') or []) or '无'} "
            f"根因={rc.get('类别')}/{rc.get('定位对象')}: {rc.get('描述')}\n"
            f"  现场: {c.get('现场摘要')}"
        )
    user = f"""{_probe_catalog()}

{STAGE2_OUTPUT_SCHEMA}

========== 案例簇(根因类别={category}, 定位对象≈{target}, 共 {len(cases)} 例) ==========
{chr(10).join(case_lines)}

请输出 JSON。"""
    return [
        {"role": "system", "content": STAGE2_SYSTEM},
        {"role": "user", "content": user},
    ]
