"""One-shot smoke render for the host-table change.

Renders the dashboard from sample/text.txt without calling the LLM.

Output: big_data_model/incident/output/incident_report_smoke.png
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


async def _async_main() -> int:
    from big_data_model.incident.context import load_related_context
    from big_data_model.incident.features import extract
    from big_data_model.incident.render.dashboard import render_dashboard

    here = REPO / "big_data_model" / "incident"
    src = here / "sample" / "text.txt"
    related_src = here / "sample" / "related_context.json"
    out_dir = here / "output"
    out_dir.mkdir(exist_ok=True)
    out_png = out_dir / "incident_report_smoke.png"

    payload = ast.literal_eval(src.read_text(encoding="utf-8"))
    bag = extract(payload)
    related = load_related_context(related_src)

    brief = (
        "【烟雾测试占位简报】快照：14:38–14:47。BPC duration 在 14:45 出现尖峰 "
        "13172ms，rr_rate 同步下探至 98.51%。主机层：1 台告警（172.216.51.155，"
        "磁盘 IOPS 读写超阈值），多台 IOwait 与内存接近阈值。"
    )

    await render_dashboard(
        bag, out_png,
        brief_text=brief,
        related=related,
        incident_id="SMOKE-HOST-TABLE",
    )
    print(f"saved -> {out_png}")
    return 0


def main() -> int:
    import asyncio
    return asyncio.run(_async_main())


if __name__ == "__main__":
    sys.exit(main())
