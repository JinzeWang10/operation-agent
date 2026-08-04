"""复核优先级分诊(纯函数,对齐 DEPLOY.md「三点六」)。

在**机器原值**上算优先级(=它为什么被标出来);是否已复核由 overlay 的 reviewed
控制,两者正交。只排序、不改类别、不替模型猜。

- P0 高:类别=UNKNOWN 且(描述或定位非空)—— 信息齐全却错挂,人工一眼可改对
- P1 中:低置信 / 有效性与工单标记冲突 / 系统名未入词表 —— 需核对
- P2 低:UNKNOWN 空壳(描述+定位皆空);其中 invalid 的多为无异常噪声,可跳过
- None:已归类、无异常信号 —— 默认免审
"""
from __future__ import annotations

from big_data_model.incident.knowledge import normalize


def _has_loc(定位对象: str) -> bool:
    loc = (定位对象 or "").strip()
    return bool(loc) and loc != "(未定位)"


def review_priority(
    *,
    系统: str,
    类别: str,
    定位对象: str,
    描述: str,
    有效性: str,
    is_invalid_flag: bool,
    低置信: bool,
) -> tuple[str | None, list[str]]:
    """返回 (优先级 P0/P1/P2/None, 原因列表)。"""
    cat = (类别 or "").strip().upper()
    val = (有效性 or "").strip().lower()
    has_desc = bool((描述 or "").strip())
    has_loc = _has_loc(定位对象)

    # P0:UNKNOWN 但信息齐全 —— 错挂,最高优先
    if cat == "UNKNOWN" and (has_desc or has_loc):
        return "P0", ["UNKNOWN 但描述/定位非空,疑似错挂"]

    # P1:需核对的信号(可叠加)
    reasons: list[str] = []
    if 低置信:
        reasons.append("低置信")
    # is_invalid_flag=工单标无效;LLM 判 valid → 冲突,值得核
    if is_invalid_flag and val == "valid":
        reasons.append("有效性与工单标记冲突")
    if (系统 or "").strip() and not normalize.resolve_system(系统).resolved:
        reasons.append("系统名未入词表")
    if reasons:
        return "P1", reasons

    # P2:UNKNOWN 空壳
    if cat == "UNKNOWN":
        if val == "invalid":
            return "P2", ["无异常噪声(UNKNOWN 空壳 + invalid)"]
        return "P2", ["UNKNOWN 空壳待确认"]

    return None, []
