"""overlay 修订层的 PG 读写(经 adapters.db seam)。

append-only:每次保存插一行,同 event_id 取最新(id 最大)为当前修订;version=该 id。
乐观锁:save_edit 校验 base_version==当前最新 id,不等则冲突(防多人互相覆盖)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from big_data_model.review.adapters import db

# 可编辑字段白名单 —— patch 只接受这些键
EDITABLE_FIELDS = ("系统", "类别", "定位对象", "描述", "有效性")


class VersionConflict(Exception):
    """base_version 已过期(别人先改了)。``latest`` 为当前最新 version。"""

    def __init__(self, latest: Optional[int]):
        super().__init__(f"version conflict, latest={latest}")
        self.latest = latest


@dataclass
class OverlayEntry:
    patch: dict
    reviewed: bool
    reviewer: Optional[str]
    version: int  # 该 event 最新 overlay 行 id


def latest_by_event() -> dict[str, OverlayEntry]:
    """每个 event 的当前修订(同 ID 取最新)。"""
    rows = db.select_sql(
        "SELECT event_id, patch, reviewed, reviewer, id FROM kp_review_overlay ORDER BY id ASC"
    )
    out: dict[str, OverlayEntry] = {}
    for event_id, patch, reviewed, reviewer, _id in rows:  # 升序遍历 → 后者(更大 id)覆盖
        out[event_id] = OverlayEntry(
            patch=json.loads(patch) if isinstance(patch, str) else (patch or {}),
            reviewed=bool(reviewed),
            reviewer=reviewer,
            version=int(_id),
        )
    return out


def current_version(event_id: str) -> Optional[int]:
    rows = db.select_sql("SELECT max(id) FROM kp_review_overlay WHERE event_id = %s", (event_id,))
    return int(rows[0][0]) if rows and rows[0][0] is not None else None


def save_edit(
    event_id: str,
    patch: dict,
    reviewed: bool,
    reviewer: str,
    base_version: Optional[int],
) -> int:
    """存一次修订,返回新 version。base_version 过期抛 VersionConflict。"""
    cur = current_version(event_id)
    if cur != base_version:
        raise VersionConflict(cur)
    clean = {k: v for k, v in (patch or {}).items() if k in EDITABLE_FIELDS}
    db.execute_sql(
        "INSERT INTO kp_review_overlay (event_id, patch, reviewed, reviewer) VALUES (%s, %s, %s, %s)",
        (event_id, json.dumps(clean, ensure_ascii=False), bool(reviewed), reviewer),
    )
    new_v = current_version(event_id)
    assert new_v is not None
    return new_v


def add_pending_system(system_name: str, source_event_id: Optional[str], proposed_by: str) -> None:
    db.execute_sql(
        "INSERT INTO kp_vocab_pending (system_name, source_event_id, proposed_by) VALUES (%s, %s, %s)",
        (system_name.strip(), source_event_id, proposed_by),
    )
