"""CLI 入口。

用法:
  # Stage 1:文件 → 案例库(离线桩验证)
  python -m big_data_model.knowledge_pipeline.run stage1 --file event_monitor_20260702.xlsx --stub

  # Stage 1:内网真实模型(先在 .env 配好 AGENT_LLM_*)
  python -m big_data_model.knowledge_pipeline.run stage1 --file data.xlsx

  # Stage 1:内网直连 DB 跑 example.sql
  python -m big_data_model.knowledge_pipeline.run stage1 --db-url "postgresql+psycopg://..."

  # Stage 2:案例库 → 候选故障模式(YAML,待人审)
  python -m big_data_model.knowledge_pipeline.run stage2 --min-size 3 --stub
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from big_data_model.knowledge_pipeline.batch import run_stage1
from big_data_model.knowledge_pipeline.loaders import make_source

DEFAULT_OUT = Path(__file__).resolve().parent / "out"


def _build_completer(use_stub: bool):
    if use_stub:
        from big_data_model.knowledge_pipeline.llm_stub import stub_complete

        return stub_complete, "stub(离线桩)"
    from big_data_model.config import Settings
    from big_data_model.llm.client import LLMClient

    settings = Settings()
    client = LLMClient(settings)
    return client.chat, f"{settings.llm_model} @ {settings.llm_base_url}"


async def _stage1(args) -> None:
    out = Path(args.out)
    source = make_source(file=args.file, db_url=args.db_url, sql_file=args.sql_file)
    complete, who = _build_completer(args.stub)
    print(f"[stage1] LLM={who} 并发={args.concurrency} limit={args.limit}")
    stats = await run_stage1(
        source,
        complete,
        case_store_path=out / "cases.jsonl",
        ledger_path=out / "_ledger.json",
        errors_path=out / "errors.jsonl",
        concurrency=args.concurrency,
        limit=args.limit,
        resume=not args.no_resume,
    )
    print(
        f"[stage1] 完成 total={stats.total} 成功={stats.processed} "
        f"跳过={stats.skipped} 失败={stats.failed} 用时={stats.elapsed_sec}s"
    )
    print(f"         案例库 → {out / 'cases.jsonl'}")
    if stats.failed:
        print(f"         失败明细 → {out / 'errors.jsonl'}")


async def _stage2(args) -> None:
    from big_data_model.incident.knowledge.case_store import CaseStore
    from big_data_model.knowledge_pipeline.distill import (
        cluster_cases,
        distill_pattern,
        write_candidate_yaml,
    )

    out = Path(args.out)
    store = CaseStore(out / "cases.jsonl")
    cases = store.all()
    clusters = cluster_cases(cases, min_size=args.min_size)
    complete, who = _build_completer(args.stub)
    print(f"[stage2] LLM={who} 案例={len(cases)} 达标簇={len(clusters)}(min_size={args.min_size})")

    pat_dir = out / "candidate_patterns"
    ok = fail = 0
    for cat, rep, members in clusters:
        res = await distill_pattern(cat, rep, members, complete)
        if res.ok and res.pattern is not None:
            path = write_candidate_yaml(res.pattern, pat_dir)
            ok += 1
            print(f"  [OK]   {res.pattern.id}  ({res.case_count} 例) -> {path.name}")
        else:
            fail += 1
            print(f"  [FAIL] {cat} ({res.case_count} 例) 蒸馏失败: {res.error}")
    print(f"[stage2] 完成 候选模式={ok} 失败={fail} → {pat_dir}")


def main() -> None:
    # Windows 控制台常为 GBK 码页,遇到不可编码字符会抛 UnicodeEncodeError;
    # 降级为 replace,保证批处理日志永不因打印崩溃。
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default=str(DEFAULT_OUT), help="产物目录(默认 knowledge_pipeline/out)")
    common.add_argument("--stub", action="store_true", help="用离线桩代替真实 LLM(无内网端点时验证)")

    p = argparse.ArgumentParser(description="历史事件批量转化为故障知识", parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("stage1", help="事件行 → 案例库", parents=[common])
    s1.add_argument("--file", help="xlsx/csv 导出文件")
    s1.add_argument("--db-url", help="SQLAlchemy 连接串(内网直连跑 example.sql)")
    s1.add_argument("--sql-file", help="自定义 SQL 文件(默认仓库根 example.sql)")
    s1.add_argument("--concurrency", type=int, default=4)
    s1.add_argument("--limit", type=int, default=None, help="只处理前 N 行(小批验证)")
    s1.add_argument("--no-resume", action="store_true", help="忽略断点台账,全量重跑")

    s2 = sub.add_parser("stage2", help="案例库 → 候选故障模式", parents=[common])
    s2.add_argument("--min-size", type=int, default=3, help="簇内最少案例数,达标才蒸馏")

    args = p.parse_args()
    if args.cmd == "stage1":
        asyncio.run(_stage1(args))
    elif args.cmd == "stage2":
        asyncio.run(_stage2(args))


if __name__ == "__main__":
    main()
