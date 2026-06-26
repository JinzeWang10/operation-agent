"""端到端：sample 数据 → PNG。

Playwright 启动较慢，这是慢测试。CI 可用 -m slow 排除。
"""
from __future__ import annotations

import ast
import struct
from pathlib import Path

import pytest

from big_data_model.incident.context import load_related_context
from big_data_model.incident.features import extract
from big_data_model.incident.render.dashboard import render_dashboard

SAMPLE_DIR = Path(__file__).parents[2] / "big_data_model" / "incident" / "sample"


def _png_dimensions(path: Path) -> tuple[int, int]:
    """读 PNG IHDR chunk 得到宽高。"""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


@pytest.mark.asyncio
async def test_end_to_end_png_renders(tmp_path):
    payload = ast.literal_eval((SAMPLE_DIR / "text.txt").read_text(encoding="utf-8"))
    bag = extract(payload)
    related = load_related_context(SAMPLE_DIR / "related_context.json")

    brief = "测试简报：耗时峰值 1234ms 成功率 99.5% @14:38"

    out = tmp_path / "report.png"
    await render_dashboard(bag, out, brief_text=brief,
                           related=related, incident_id="INC-TEST")

    assert out.exists()
    assert out.stat().st_size > 10_000  # 不是空 PNG
    w, h = _png_dimensions(out)
    # device_scale_factor=2 × 1280 width = 2560
    assert w == 2560, f"expected width 2560, got {w}"
    assert h > 500, f"expected reasonable height, got {h}"
