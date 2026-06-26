"""字体探针：确认 headless Chromium 能用 SimHei 渲染中文。

运行：python -m big_data_model.incident.render._probe_font
产物：big_data_model/incident/output/_probe_font.png  应能看到清晰中文，无方框。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  body { background: #0d1117; color: #e6edf3; padding: 24px;
         font-family: "SimHei", "Microsoft YaHei", sans-serif; }
  h1 { font-size: 32px; }
  p  { font-size: 16px; line-height: 1.8; }
  .num { color: #fb8500; font-weight: bold; }
  .pct { color: #d29922; font-weight: bold; }
</style></head>
<body>
  <h1>事件会诊速览 · 中文字体探针</h1>
  <p>核保规则发布触发疑似异常：交易耗时峰值 <span class="num">2179ms</span>，
     成功率最低 <span class="pct">96.43%</span>，主机 172.20.31.x /24 子网集中超阈值。</p>
  <p>常用标点：，。、；：？！「」『』（）—— …… 测试粗体 <b>加粗中文</b>。</p>
</body></html>
"""

OUT = Path(__file__).parent.parent / "output" / "_probe_font.png"


async def main() -> int:
    OUT.parent.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(
                viewport={"width": 800, "height": 400},
                device_scale_factor=2,
            )
            await page.set_content(HTML, wait_until="load")
            await page.screenshot(path=str(OUT), full_page=True, type="png")
        finally:
            await browser.close()
    print(f"probe png -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
