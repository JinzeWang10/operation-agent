"""Related context sidecar.

ITSM 事件单 (INM) 和 变更/发布 (CHM/DRM) 来自不同上游系统，与监控聚合快照
分开传入。本模块只做加载与结构化，不参与 LLM brief，仅供渲染层透传展示。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class IncidentTicket:
    ticket_id: str
    severity: str
    text: str


@dataclass
class ChangeTicket:
    ticket_id: str
    type_text: str
    title: str
    time_range: str


@dataclass
class RelatedContext:
    incidents_header: str = ""
    incidents: list[IncidentTicket] = field(default_factory=list)
    changes_header: str = ""
    changes: list[ChangeTicket] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.incidents and not self.changes


def load_related_context(path: Path) -> Optional[RelatedContext]:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return RelatedContext(
        incidents_header=data.get("incidents_header", ""),
        incidents=[IncidentTicket(**i) for i in data.get("incidents", [])],
        changes_header=data.get("changes_header", ""),
        changes=[ChangeTicket(**c) for c in data.get("changes", [])],
    )
