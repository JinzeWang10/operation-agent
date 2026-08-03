"""案例台账:append-only JSONL,每事件一条(可追加新版本,读取时按事件 ID 取最新)。

设计约束:
- **字段由系统反向定义**:运行期字段对应 Agent 输出与复盘回填口径;历史工单
  导入时缺的字段留空,多的字段原样存入 ``原始``(lossless,沿用 FeatureBag 原则)。
- **根因粒度 = 类别 × 定位对象**:具体到能缩小排查范围即可。``类别`` 分类法
  与 pattern ID 前缀同源,待事件单聚类后定稿,当前不做枚举校验。
- **命中不存储、只计算**:命中可由 Top3 + 回填推出,按"可算的不入库"原则用
  :func:`hit_rank` 现算,口径变更无需刷历史数据。
- **append-only**:回填等后到信息以"追加新版本"方式写入,保留完整审计轨迹;
  读取时同一事件 ID 取最后一条。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from big_data_model.incident.knowledge import normalize


class RootCause(BaseModel):
    """一个根因表达:类别 × 定位对象,可附一句话描述。"""

    model_config = ConfigDict(extra="forbid")

    类别: str  # 如 DB / RELEASE / HOST / NET,与 pattern ID 前缀同一套分类法
    定位对象: str  # 如 "DB1"、"核保规则"、"Redis-Cluster-A"
    描述: str = ""

    def same_target(self, other: "RootCause") -> bool:
        return (
            self.类别.strip().casefold() == other.类别.strip().casefold()
            and self.定位对象.strip().casefold() == other.定位对象.strip().casefold()
        )


class Hypothesis(RootCause):
    """Agent 输出的一条嫌疑根因。"""

    置信度: Literal["高", "中", "低"]
    引用模式: list[str] = Field(default_factory=list)


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    事件ID: str
    系统: str
    发生时间: str  # ISO 格式,如 2026-06-11T10:32:00
    来源: Literal["agent", "历史导入", "人工复盘"]
    现场摘要: str = ""
    假设轨迹: str = ""  # 思考轨迹全文,附件级,可长
    Top3: list[Hypothesis] = Field(default_factory=list)
    未命中已知模式: bool = False
    回填: Optional[RootCause] = None
    回填时间: str = ""
    原始: dict = Field(default_factory=dict)  # 原始工单字段原样保留

    @field_validator("发生时间", "回填时间", mode="before")
    @classmethod
    def _datetime_to_iso(cls, v):
        # YAML 会把未加引号的时间戳解析成 datetime;人填模板必然忘加引号,
        # 在这里兼容而不是要求人记住
        if isinstance(v, datetime):
            return v.isoformat()
        return v


def load_case_yaml(path: Path) -> Case:
    """加载人工复盘记录(按 case_template.yaml 填写的 YAML)。"""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"{path.name}: YAML 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: 顶层必须是映射,实际为 {type(data).__name__}")
    try:
        return Case.model_validate(data)
    except Exception as e:
        raise ValueError(f"{path.name}: {e}") from e


def hit_rank(case: Case) -> Optional[int]:
    """命中名次:回填根因与 Top N 中第几条一致(1 起);未回填或未命中返回 None。

    命中口径走 ``normalize.same_root_cause``(系统+实例token,可降级,兜底不弱于
    旧精确匹配),让"UnderwritePowerRule_32App"的多种写法能对齐,评估命中率才可信。
    """
    if case.回填 is None:
        return None
    for rank, hypo in enumerate(case.Top3, start=1):
        if normalize.same_root_cause(hypo, case.回填):
            return rank
    return None


class CaseStore:
    """JSONL 案例台账。只有追加与按 ID/系统读取,没有检索。"""

    def __init__(self, path: Path):
        self.path = path

    def append(self, case: Case) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(case.model_dump(), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def all(self) -> list[Case]:
        """全部案例,同一事件 ID 取最后一条(后写的版本覆盖先写的)。"""
        if not self.path.exists():
            return []
        latest: dict[str, Case] = {}
        with self.path.open("r", encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    latest_case = Case.model_validate(json.loads(line))
                except Exception as e:
                    raise ValueError(f"{self.path.name} 第 {n} 行: {e}") from e
                latest[latest_case.事件ID] = latest_case
        return list(latest.values())

    def get(self, incident_id: str) -> Optional[Case]:
        for case in self.all():
            if case.事件ID == incident_id:
                return case
        return None

    def recent_by_system(
        self, system: str, days: int = 90, now: Optional[datetime] = None
    ) -> list[Case]:
        """同系统近 N 天案例(确定性查询,V1 注入 Layer 1 的就是它)。

        发生时间无法解析的案例不纳入(历史导入数据可能缺时间,宁可漏不可错)。
        """
        now = now or datetime.now()
        cutoff = now - timedelta(days=days)
        target = normalize.canonical_system(system)  # 两侧都规范化,消除 fault_system 拼接脏键
        out: list[Case] = []
        for case in self.all():
            if normalize.canonical_system(case.系统) != target:
                continue
            try:
                occurred = datetime.fromisoformat(case.发生时间)
            except ValueError:
                continue
            if occurred >= cutoff:
                out.append(case)
        out.sort(key=lambda c: c.发生时间, reverse=True)
        return out

    def hit_stats(self) -> dict:
        """命中率统计(命中口径的唯一实现处)。"""
        filled = [c for c in self.all() if c.回填 is not None]
        ranks = [hit_rank(c) for c in filled]
        return {
            "已回填": len(filled),
            "top1": sum(1 for r in ranks if r == 1),
            "top3": sum(1 for r in ranks if r is not None and r <= 3),
            "未命中": sum(1 for r in ranks if r is None),
        }
