"""HTML snapshot 测试。

不做像素级比对（字体/Chromium 版本会导致 flakiness）。改为：
- 断言 render_html() 返回的 HTML 包含关键字段
- 断言模板正确处理空/异常分支
- escape 由 Jinja autoescape 处理，确保 <script> 不会原样进入
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from big_data_model.incident.context import (
    ChangeTicket,
    IncidentTicket,
    RelatedContext,
    load_related_context,
)
from big_data_model.incident.features import FeatureBag, extract
from big_data_model.incident.render.dashboard import render_html

SAMPLE_DIR = Path(__file__).parents[2] / "big_data_model" / "incident" / "sample"


@pytest.fixture
def real_bag() -> FeatureBag:
    payload = ast.literal_eval((SAMPLE_DIR / "text.txt").read_text(encoding="utf-8"))
    return extract(payload)


@pytest.fixture
def real_related() -> RelatedContext:
    return load_related_context(SAMPLE_DIR / "related_context.json")


def test_html_contains_title_and_core_sections(real_bag, real_related):
    html = render_html(real_bag, brief_text="测试简报 100ms",
                      related=real_related, incident_id="INC-X")
    assert "事件会诊速览" in html
    assert "INC-X" in html
    # sample 的规则发布均早于近期窗口（is_recent=False），banner 有意不渲染；
    # banner 渲染路径由 test_html_banner_html_in_rule_escaped 覆盖。
    assert 'class="banner"' not in html
    assert 'class="brief"' in html
    assert "panel hosts" in html
    assert 'class="related"' in html
    assert "<svg" in html  # BPC inline svg


def test_html_brief_highlight_spans_present(real_bag):
    html = render_html(
        real_bag,
        brief_text="耗时 1234ms 成功率 99.50% @14:38 子网 10.0.0.x 偏离 ×3",
        related=None, incident_id=None,
    )
    assert 'class="hl-ms"' in html
    assert 'class="hl-pct"' in html
    assert 'class="hl-time"' in html
    assert 'class="hl-ip"' in html
    assert 'class="hl-dev"' in html


def test_html_escapes_brief_special_chars(real_bag):
    html = render_html(
        real_bag,
        brief_text="<script>alert(1)</script>",
        related=None, incident_id=None,
    )
    # autoescape 后尖括号被替换
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_top_solo_when_related_absent(real_bag):
    html = render_html(real_bag, brief_text="x", related=None, incident_id=None)
    assert "top solo" in html


def test_html_truncated_count_message(real_bag):
    """sample 数据真实地触发 truncated_count > 0，确认渲染出 +N 提示。"""
    html = render_html(real_bag, brief_text="x", related=None, incident_id=None)
    # 旧 sample 有 100 台、12 行展示，预期 truncated_count > 0
    assert "未展示" in html


def test_html_banner_html_in_rule_escaped():
    """规则字符串若含 HTML 特殊字符，模板应 escape。"""
    from big_data_model.incident.features import ReleaseRuleFeatures
    bag = FeatureBag(raw_meta={})
    bag.release_rules = ReleaseRuleFeatures(
        present=True, code="0", type_text="核保规则发布情况",
        rules=["<b>UnderwritePowerRule_51App</b>已发布:6分钟"],
        raw_block={},
    )
    html = render_html(bag, brief_text=None, related=None, incident_id=None)
    assert "<b>UnderwritePowerRule" not in html
    assert "&lt;b&gt;UnderwritePowerRule" in html


def test_html_omits_sections_with_no_data():
    """空 FeatureBag：只渲染标题，brief/banner/bpc/hosts/related 全部消失。"""
    bag = FeatureBag(raw_meta={})
    html = render_html(bag, brief_text=None, related=None, incident_id=None)
    assert "事件会诊速览" in html
    # 没有任何 section 元素被渲染
    assert '<section class="banner"' not in html
    assert '<section class="brief"' not in html
    assert '<aside class="related"' not in html
    assert '<section class="panel hosts"' not in html
    assert "<svg" not in html
    assert '<div class="top' not in html


def test_html_top_solo_when_brief_absent_but_related_present(real_bag, real_related):
    """只有 related 没有 brief：top 也应单列。"""
    # 清掉异常日志，否则日志小节会让 brief 面板出现（其行为见 test_log_keywords）。
    real_bag.log_keywords = None
    html = render_html(real_bag, brief_text=None, related=real_related, incident_id=None)
    assert "top solo" in html
    assert 'class="brief"' not in html
    assert 'class="related"' in html


def test_html_related_change_kinds_apply_class(real_bag):
    ctx = RelatedContext(
        incidents_header="H",
        incidents=[IncidentTicket(ticket_id="A", severity="严重", text="t")],
        changes_header="H2",
        changes=[
            ChangeTicket(ticket_id="B", type_text="变更",
                         title="t2", time_range="1h"),
            ChangeTicket(ticket_id="C", type_text="升级发布",
                         title="t3", time_range="2h"),
        ],
    )
    html = render_html(real_bag, brief_text="x", related=ctx, incident_id=None)
    assert 'class="tag sev-high"' in html
    assert 'class="tag change"' in html
    assert 'class="tag release"' in html
