"""离线确定性 LLM 桩 —— 无内网端点时跑通全链路 plumbing。

不做真实推理:Stage 1 用关键词把根因文本粗归类,Stage 2 按类别回一条最小合法
Pattern。目的只是让 extract/distill/batch 全链路在真实数据上端到端跑通并产出
可校验的结构;真实萃取质量需接内网模型后评估。
"""
from __future__ import annotations

import json
import re

_CATEGORY_KEYWORDS = [
    ("BATCH", ("批量", "跑批", "定时任务", "作业")),
    ("RELEASE", ("发布", "升级", "版本", "上线")),
    ("DB", ("数据库", "备份", "慢查询", "连接数", "长事务", "sinodb", "gauss", "页锁")),
    ("NET", ("网络", "丢包", "专线", "抖动", "超时", "timeout")),
    ("MIDDLEWARE", ("redis", "mq", "consul", "zuul", "网关", "中间件")),
    ("HOST", ("主机", "cpu", "内存", "磁盘", "iowait")),
    ("CLIENT", ("客户端", "渠道")),
]


def _guess_category(text: str) -> str:
    low = text.lower()
    for cat, kws in _CATEGORY_KEYWORDS:
        if any(k.lower() in low for k in kws):
            return cat
    return "UNKNOWN"


def _field(text: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}:\s*(.*)", text)
    return m.group(1).strip() if m else ""


async def stub_complete(messages: list[dict]) -> str:
    system = messages[0]["content"] if messages else ""
    user = messages[-1]["content"] if messages else ""

    if "故障模式提炼" in system:  # Stage 2
        m = re.search(r"根因类别=([A-Z_]+)", user)
        category = m.group(1) if m else "UNKNOWN"
        probe = {
            "DB": "db_instance_status",
            "RELEASE": "release_rules_recent",
            "HOST": "host_metric_breaches",
            "MIDDLEWARE": "component_status",
            "NET": "app_probe_status",
        }.get(category, "bpc_system_metrics")
        return json.dumps(
            {
                "名称": f"{category} 类故障模式(桩)",
                "适用条件": "联机交易类系统(桩生成,待人审)",
                "现象": "BPC 耗时/响应率出现偏离基线的波动(桩)",
                "候选根因": [f"{category} 相关根因(桩)"],
                "验证": [{"probe": probe, "判定": "对应 probe 指标越限或异常", "区分": []}],
                "排除": "对应指标全部正常时不成立",
                "症状标签": ["slow"],
                "备注": "stub",
            },
            ensure_ascii=False,
        )

    # Stage 1
    fault = _field(user, "人工填写-根因")
    solution = _field(user, "人工填写-处置/结论")
    title = _field(user, "标题")
    category = _guess_category(fault + " " + solution + " " + title)
    is_invalid = "1(疑似无效/误报)" in user
    return json.dumps(
        {
            "现场摘要": f"(桩)标题: {title[:40]};根因文本: {fault[:60]}",
            "回填": {
                "类别": "NOISE" if (is_invalid and category == "UNKNOWN") else category,
                "定位对象": _field(user, "受影响系统") or "(未定位)",
                "描述": fault[:80] or "(桩:无根因文本)",
            },
            "有效性": "invalid" if is_invalid else "valid",
            "低置信": category == "UNKNOWN",
            "备注": "stub",
        },
        ensure_ascii=False,
    )
