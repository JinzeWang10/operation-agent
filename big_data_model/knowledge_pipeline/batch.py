"""批处理基建:限并发 + 断点续跑台账 + 单行失败不阻断 + 统计。

LLM JSON 纠偏重试在 extract/distill 内部完成;这里只管调度、落盘与幂等。
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from big_data_model.incident.knowledge.case_store import CaseStore
from big_data_model.knowledge_pipeline.extract import Completer, extract_case
from big_data_model.knowledge_pipeline.loaders import RowSource
from big_data_model.knowledge_pipeline.parse import parse_row


@dataclass
class Stage1Stats:
    total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed_sec: float = 0.0
    errors: list[dict] = field(default_factory=list)


def _load_ledger(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_ledger(path: Path, done: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=2), encoding="utf-8")


async def run_stage1(
    source: RowSource,
    complete: Completer,
    *,
    case_store_path: Path,
    ledger_path: Path,
    errors_path: Path,
    concurrency: int = 4,
    limit: Optional[int] = None,
    resume: bool = True,
) -> Stage1Stats:
    store = CaseStore(case_store_path)
    done = _load_ledger(ledger_path) if resume else set()
    stats = Stage1Stats()
    start = time.monotonic()

    rows = list(source.iter_rows())
    if limit is not None:
        rows = rows[:limit]
    stats.total = len(rows)

    sem = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    errors_path.parent.mkdir(parents=True, exist_ok=True)

    async def worker(raw: dict) -> None:
        parsed = parse_row(raw)
        oid = parsed.order_number or "(无单号)"
        if resume and oid in done:
            stats.skipped += 1
            return
        async with sem:
            result = await extract_case(parsed, complete)
        async with write_lock:
            if result.ok and result.case is not None:
                store.append(result.case)
                done.add(oid)
                stats.processed += 1
            else:
                stats.failed += 1
                err = {"order_number": oid, "error": result.error, "parse_error": parsed.parse_error}
                stats.errors.append(err)
                with errors_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(err, ensure_ascii=False) + "\n")

    await asyncio.gather(*(worker(r) for r in rows))

    _save_ledger(ledger_path, done)
    stats.elapsed_sec = round(time.monotonic() - start, 2)
    return stats
