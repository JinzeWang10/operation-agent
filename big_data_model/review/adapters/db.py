"""DB seam:复核台所有 SQL 都经这里。

- **本地/测试**(默认):sqlite(stdlib),首次使用自动建表,让全链路离线真跑。
- **内网**:设 ``AGENT_REVIEW_DB_BACKEND=intranet``,并把 ``_intranet_select`` /
  ``_intranet_execute`` 两个接线点改成现成的 ``select_sql`` / ``execute_sql`` 封装。

约定:上层(overlay.py)SQL 一律用 PostgreSQL 风格 ``%s`` 占位;sqlite 后端在此
翻译成 ``?``。表结构以 ``sql/schema.sql``(PG)为准,sqlite 后端内置等价 DDL。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Sequence

_BACKEND = os.getenv("AGENT_REVIEW_DB_BACKEND", "sqlite")
_SQLITE_PATH = os.getenv(
    "AGENT_REVIEW_DB_PATH",
    str(Path(__file__).resolve().parents[1] / "review_overlay.sqlite3"),
)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# sqlite 等价 DDL(与 sql/schema.sql 的 PG 版一一对应)
_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS kp_review_overlay (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id   TEXT NOT NULL,
  patch      TEXT NOT NULL,
  reviewed   INTEGER NOT NULL DEFAULT 1,
  reviewer   TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_overlay_event ON kp_review_overlay (event_id, id DESC);

CREATE TABLE IF NOT EXISTS kp_vocab_pending (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  system_name     TEXT NOT NULL,
  source_event_id TEXT,
  proposed_by     TEXT,
  status          TEXT NOT NULL DEFAULT 'pending',
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def use_sqlite(path: str | Path) -> None:
    """切到指定 sqlite 文件(测试用:每个用例一个 tmp 库)。"""
    global _BACKEND, _SQLITE_PATH, _conn
    _BACKEND = "sqlite"
    _SQLITE_PATH = str(path)
    if _conn is not None:
        _conn.close()
    _conn = None


def _sqlite_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_SQLITE_PATH, check_same_thread=False)
        _conn.executescript(_SQLITE_DDL)
        _conn.commit()
    return _conn


def _to_sqlite(sql: str) -> str:
    return sql.replace("%s", "?")


def select_sql(sql: str, params: Sequence[Any] = ()) -> list[tuple]:
    if _BACKEND == "intranet":
        return _intranet_select(sql, tuple(params))
    with _lock:
        cur = _sqlite_conn().execute(_to_sqlite(sql), tuple(params))
        return cur.fetchall()


def execute_sql(sql: str, params: Sequence[Any] = ()) -> None:
    if _BACKEND == "intranet":
        _intranet_execute(sql, tuple(params))
        return
    with _lock:
        conn = _sqlite_conn()
        conn.execute(_to_sqlite(sql), tuple(params))
        conn.commit()


# ── 内网接线点:把下面两个函数体换成现成封装 ────────────────────────────
# 现成封装:select_sql(sql[, params]) 查询、execute_sql(sql[, params]) 改数据。
# 若封装不吃 params(只收一条 SQL 字符串),在此做参数化到安全转义的适配。

def _intranet_select(sql: str, params: tuple) -> list[tuple]:
    from database import postgre  # 内网模块,本地不存在

    return postgre.select_sql(sql, params)


def _intranet_execute(sql: str, params: tuple) -> None:
    from database import postgre

    postgre.execute_sql(sql, params)
