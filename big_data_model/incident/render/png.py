"""HTML → PNG via headless Chromium (Playwright)。

设计要点：
- viewport 宽度固定 1280px，与 dashboard.css 的 .dashboard 宽度对齐。
- device_scale_factor=2，避免 IM 缩略图压缩后中文糊。
- full_page=True：浏览器先按内容自然排版决定高度，再整页截图——
  这是 HTML 方案最大的红利：永远不会"画布不够大"。
"""
from __future__ import annotations

from pathlib import Path

from playwright.async_api import async_playwright


async def html_to_png(html: str, out: Path, width: int = 1280) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(
                viewport={"width": width, "height": 800},
                device_scale_factor=2,
            )
            await page.set_content(html, wait_until="load")
            await page.screenshot(path=str(out), full_page=True, type="png")
        finally:
            await browser.close()
    return out
