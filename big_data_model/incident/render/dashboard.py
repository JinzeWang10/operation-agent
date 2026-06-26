"""HTML 渲染总入口：prepare → charts → Jinja → png。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from big_data_model.incident.context import RelatedContext
from big_data_model.incident.features import FeatureBag
from big_data_model.incident.render.charts import bpc_legend, render_bpc_svg
from big_data_model.incident.render.png import html_to_png
from big_data_model.incident.render.prepare import build_view_model

_HERE = Path(__file__).parent
_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_html(
    bag: FeatureBag,
    brief_text: Optional[str],
    related: Optional[RelatedContext],
    incident_id: Optional[str] = None,
    order_number: Optional[str] = None,
    log_interpretation: Optional[str] = None,
) -> str:
    """生成完整 HTML 字符串。无副作用，便于 snapshot 测试。"""
    bpc_svg = render_bpc_svg(bag)
    vm = build_view_model(
        bag=bag,
        brief_text=brief_text,
        related=related,
        bpc_svg=bpc_svg,
        bpc_legend=bpc_legend(bag),
        log_interpretation=log_interpretation,
        incident_id=incident_id,
        order_number=order_number,
    )
    css = (_STATIC / "dashboard.css").read_text(encoding="utf-8")
    env = _make_env()
    template = env.get_template("dashboard.html.j2")
    return template.render(vm=vm, css=css)


async def render_dashboard(
    bag: FeatureBag,
    out_path: Path,
    brief_text: Optional[str] = None,
    related: Optional[RelatedContext] = None,
    incident_id: Optional[str] = None,
    order_number: Optional[str] = None,
    log_interpretation: Optional[str] = None,
) -> Path:
    """端到端：FeatureBag → PNG。签名与旧 charts.render_dashboard 保持一致
    （但是 async）。便于在 render_report.py 用 --engine 切换。"""
    html = render_html(bag, brief_text, related, incident_id, order_number,
                       log_interpretation=log_interpretation)
    return await html_to_png(html, out_path)
