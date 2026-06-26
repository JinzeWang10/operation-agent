"""End-to-end: sample/text.txt -> FeatureBag -> LLM brief -> composite PNG.

Run from repo root:
    python -m big_data_model.incident.render_report
"""
from __future__ import annotations

import asyncio
import ast
import sys
from pathlib import Path

from big_data_model.incident.context import load_related_context
from big_data_model.incident.features import extract
from big_data_model.incident.render.dashboard import render_dashboard
from big_data_model.incident.summarizer import summarize, summarize_logs

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
SRC = HERE / "sample" / "text.txt"
RELATED_SRC = HERE / "sample" / "related_context.json"
OUT_DIR = HERE / "output"
OUT_PNG = OUT_DIR / "incident_report.png"
OUT_TXT = OUT_DIR / "incident_brief.txt"


async def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    payload = ast.literal_eval(SRC.read_text(encoding="utf-8"))
    bag = extract(payload)
    brief = bag.to_llm_brief()
    related = load_related_context(RELATED_SRC)

    print("calling LLM for phenomenon brief...", flush=True)
    try:
        text = await summarize(brief)
    except Exception as e:  # noqa: BLE001 — LLM 任意失败都降级，不挡渲染
        print(f"  LLM call failed ({type(e).__name__}: {e}); using fallback brief")
        text = "[LLM_ERROR]"
    OUT_TXT.write_text(text, encoding="utf-8")
    print(f"  brief saved -> {OUT_TXT.relative_to(HERE)}  ({len(text)} chars)")

    # 日志关键字：异常日志原文走确定性渲染，这里只额外为它取一句 LLM 研判。
    log_entries = []
    if bag.log_keywords and bag.log_keywords.present:
        log_entries = [
            {
                "sys": e.sys_name,
                "com": e.com_name,
                "keywords": [
                    {"kw": h.keyword, "count": h.count, "ip_count": h.ip_count}
                    for h in e.hits
                ],
                "msg": e.msg,
            }
            for e in bag.log_keywords.entries if e.is_anomalous
        ]
    log_text = ""
    if log_entries:
        print(f"calling LLM for log interpretation ({len(log_entries)} lines)...", flush=True)
        try:
            log_text = await summarize_logs(log_entries)
        except Exception as e:  # noqa: BLE001 — 研判失败只是少一句话，不挡渲染
            print(f"  log LLM call failed ({type(e).__name__}: {e}); 跳过研判")
            log_text = ""

    print("rendering composite PNG...", flush=True)
    await render_dashboard(bag, OUT_PNG, brief_text=text, related=related,
                           log_interpretation=log_text)
    print(f"  report saved -> {OUT_PNG.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
