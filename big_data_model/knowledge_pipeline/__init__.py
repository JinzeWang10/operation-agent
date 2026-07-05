"""历史事件批量转化为故障知识的灌注管线。

Stage 1：事件行 → Case（案例库，来源=历史导入）
Stage 2：案例 → 候选 Pattern（故障模式库，待人审）

设计见 docs/plans/2026-07-02-batch-knowledge-distill-design.md。
"""
