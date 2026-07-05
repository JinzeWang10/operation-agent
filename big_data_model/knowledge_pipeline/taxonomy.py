"""根因类别枚举 —— 与 pattern ID 前缀同一套分类法。

⚠️ 当前为**种子占位枚举**,由历史数据与 RCA 计划蒸馏而来。
   需求方给出正式固定枚举后,直接替换 ``ROOT_CAUSE_CATEGORIES`` 即可,
   或通过环境变量 ``AGENT_KP_TAXONOMY``(逗号分隔)覆盖,无需改代码。

用途:
- Stage 1 萃取时注入 prompt,约束 LLM 只能在枚举内选 ``回填.类别``;
- Stage 2 蒸馏出的 Pattern id 前缀应落在同一套类别里,保证两段一致。

⚠️ 类别代码建议用**纯大写字母/数字**(无下划线/空格),因其会作为 Pattern id
   前缀,而 pattern id 命名规则 ``PATTERN-XXX-NN`` 不含下划线;distill 侧另有
   防御性净化兜底,但源头规范能让 id 更可读。

设计约束:类别应"够缩小排查方向"即可,不要细到组件实例(那是"定位对象"的事)。
"""
from __future__ import annotations

import os

# 种子枚举:key=类别代码(大写,用作 pattern id 前缀),value=一句话说明供 LLM 归类
_SEED: dict[str, str] = {
    "DB": "数据库资源/连接/慢查询/锁/备份等相关",
    "RELEASE": "程序发布、规则发布、版本升级引入的问题",
    "BATCH": "批量作业/跑批/定时任务导致的资源占用或阻塞",
    "HOST": "主机资源(CPU/内存/IOwait/磁盘)或宿主机故障",
    "NET": "网络抖动/丢包/专线/DNS/防火墙等网络层问题",
    "MIDDLEWARE": "中间件(Redis/MQ/Consul/Zuul/网关等)异常",
    "APP": "应用自身缺陷/配置错误/线程池耗尽等",
    "CONFIG": "配置变更/参数错误",
    "DEPENDENCY": "上下游依赖系统/第三方接口异常传导",
    "CLIENT": "客户端/渠道侧异常访问,非系统本身故障",
    "NOISE": "误报或阈值抖动,实际无故障(常伴自动恢复)",
    "UNKNOWN": "证据不足,无法归类(需人审)",
}


def _load() -> dict[str, str]:
    override = os.getenv("AGENT_KP_TAXONOMY", "").strip()
    if not override:
        return dict(_SEED)
    # 覆盖时只给代码,说明留空;正式枚举建议直接改 _SEED 以带上说明
    return {code.strip().upper(): "" for code in override.split(",") if code.strip()}


ROOT_CAUSE_CATEGORIES: dict[str, str] = _load()


def valid_categories() -> list[str]:
    return list(ROOT_CAUSE_CATEGORIES)


def is_valid(category: str) -> bool:
    return category.strip().upper() in ROOT_CAUSE_CATEGORIES


def coerce(category: str) -> str:
    """归一到枚举:命中则返回大写标准值,否则回落 UNKNOWN。"""
    c = (category or "").strip().upper()
    return c if c in ROOT_CAUSE_CATEGORIES else "UNKNOWN"


def prompt_block() -> str:
    """渲染为注入 LLM 的类别清单。"""
    lines = ["可选根因类别(只能从下列代码中选一个,填代码本身):"]
    for code, desc in ROOT_CAUSE_CATEGORIES.items():
        lines.append(f"- {code}: {desc}" if desc else f"- {code}")
    return "\n".join(lines)
