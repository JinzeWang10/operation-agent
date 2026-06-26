"""故障模式(pattern)schema 与 YAML 加载器。

设计约束:
- **字段名用中文**:pattern 由值班/复盘人手写与评审,YAML 面向人;Python
  标识符支持中文,pydantic 直接建模,无映射层。
- **``验证[].probe`` 必须在 probe 注册表内**:自检环节的覆盖度对比由代码
  完成,机器可读的锚点只有 probe 名;``判定`` 刻意保留自由文本,由 LLM 在
  调查中执行(内容认知归 LLM,覆盖度核对归代码)。
- **派生数据不入库**:命中统计、近期命中等一切可从案例台账算出的字段不在
  schema 中,pattern 文件只存人写人审的判别知识。
- **``extra="forbid"``**:手写 YAML 的字段名打错直接报错,不静默忽略。

``症状标签`` 取值对齐 features._classify_bpc_symptom 的输出,供代码侧按
BPC 症状预筛模式;V1 模式全量注入,该字段仅作 LLM 自我过滤的提示。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from big_data_model.incident.knowledge.probes import PROBES

PATTERN_ID_RE = re.compile(r"^PATTERN-[A-Z0-9]+(-[A-Z0-9]+)*$")

# 与 features._classify_bpc_symptom 的 flag 集合保持一致
SYMPTOM_TAGS = ("slow", "errors", "response_drop", "volume_drop")


class Verification(BaseModel):
    """一条验证方法:用哪个 probe 看什么,以及它能与哪些竞争模式区分。"""

    model_config = ConfigDict(extra="forbid")

    probe: str
    判定: str
    区分: list[str] = Field(default_factory=list)

    @field_validator("probe")
    @classmethod
    def _probe_registered(cls, v: str) -> str:
        if v not in PROBES:
            known = ", ".join(sorted(PROBES))
            raise ValueError(f"probe '{v}' 未注册;可用: {known}")
        return v

    @field_validator("区分")
    @classmethod
    def _refs_look_like_pattern_ids(cls, v: list[str]) -> list[str]:
        for ref in v:
            if not PATTERN_ID_RE.match(ref):
                raise ValueError(f"区分目标 '{ref}' 不是合法的 pattern id")
        return v


class Pattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    名称: str
    适用条件: str
    现象: str
    候选根因: list[str] = Field(min_length=1)
    验证: list[Verification] = Field(min_length=1)
    排除: str
    版本: int = 1
    状态: Literal["启用", "废止"] = "启用"
    症状标签: list[Literal["slow", "errors", "response_drop", "volume_drop"]] = Field(
        default_factory=list
    )
    来源案例: list[str] = Field(default_factory=list)
    备注: str = ""

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not PATTERN_ID_RE.match(v):
            raise ValueError(
                f"id '{v}' 不符合 PATTERN-XXX-NN 命名(大写字母/数字,连字符分段)"
            )
        return v

    def to_prompt(self) -> str:
        """渲染为注入 LLM 上下文的紧凑文本块。"""
        lines = [f"[{self.id} v{self.版本}] {self.名称}"]
        lines.append(f"适用: {self.适用条件}")
        if self.症状标签:
            lines.append(f"症状标签: {', '.join(self.症状标签)}")
        lines.append(f"现象: {self.现象.strip()}")
        lines.append("候选根因: " + " / ".join(self.候选根因))
        for v in self.验证:
            seg = f"验证: {v.probe} — {v.判定}"
            if v.区分:
                seg += f"(区分: {', '.join(v.区分)})"
            lines.append(seg)
        lines.append(f"排除: {self.排除}")
        return "\n".join(lines)


class PatternLibrary(BaseModel):
    """一个目录下全部 pattern 的集合,含交叉引用检查结果。"""

    patterns: list[Pattern]
    warnings: list[str] = Field(default_factory=list)

    def active(self) -> list[Pattern]:
        return [p for p in self.patterns if p.状态 == "启用"]

    def get(self, pattern_id: str) -> Pattern | None:
        return next((p for p in self.patterns if p.id == pattern_id), None)

    def to_prompt(self) -> str:
        """全量注入文本:V1 模式总量 20–50 条,不做检索,一次性给 LLM。"""
        return "\n\n".join(p.to_prompt() for p in self.active())


def load_pattern(path: Path) -> Pattern:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"{path.name}: YAML 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: 顶层必须是映射,实际为 {type(data).__name__}")
    try:
        return Pattern.model_validate(data)
    except Exception as e:
        raise ValueError(f"{path.name}: {e}") from e


def load_library(directory: Path) -> PatternLibrary:
    """加载目录下全部 ``*.yaml`` pattern。

    - id 重复 → 直接报错(两个文件声明同一 pattern 必须当场解决)
    - ``区分`` 引用了库中不存在的 id → 记入 warnings(允许先写引用后补条目,
      但月度回顾时 warnings 应清零)
    """
    patterns: list[Pattern] = []
    for path in sorted(directory.glob("*.yaml")):
        patterns.append(load_pattern(path))

    seen: dict[str, str] = {}
    for p in patterns:
        if p.id in seen:
            raise ValueError(f"pattern id 重复: {p.id}")
        seen[p.id] = p.id

    warnings: list[str] = []
    known = set(seen)
    for p in patterns:
        for v in p.验证:
            for ref in v.区分:
                if ref not in known:
                    warnings.append(f"{p.id}: 区分目标 {ref} 不在库中")

    return PatternLibrary(patterns=patterns, warnings=warnings)
