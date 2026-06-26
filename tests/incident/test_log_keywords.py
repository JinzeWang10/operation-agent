"""日志关键字：解析 (features) + VM 构建 (prepare) + HTML 渲染 (dashboard)。

覆盖三件事：
- 聚合 msg 串被拆成结构化 LogKeywordHit（关键词 / 次数 / IP 数）
- 全正常日志折叠成一句灰字，不撑出面板
- 异常日志在简报面板里成 `日志关键字` 小节，关键词高亮 + 研判挂旁
"""
from __future__ import annotations

from big_data_model.incident.features import (
    FeatureBag,
    LogKeywordEntry,
    LogKeywordFeatures,
    _parse_log_hits,
)
from big_data_model.incident.render.dashboard import render_html
from big_data_model.incident.render.prepare import build_view_model

# 真实形态：一条 msg 里多个关键词，各带次数 + 涉及 IP 数 + 样例 IP。
REAL_MSG = (
    '关键词："org.springframework.jdbc.CannotGetJdbcConnectionException" '
    "一共出现了：22次,涉及IP10个: 10.28.11.151;10.28.11.152;10.28.11.153...;"
    '关键词："does not exist" 一共出现了：28次,涉及IP10个: '
    "10.28.11.151;10.28.11.152;10.28.11.153...;"
    '关键词："org.springframework.dao.DuplicateKeyException" '
    "一共出现了：9次,涉及IP10个: 10.28.11.151;10.28.11.152;10.28.11.153...;"
)


def _bag_with_log(entries: list[LogKeywordEntry]) -> FeatureBag:
    bag = FeatureBag(raw_meta={})
    bag.log_keywords = LogKeywordFeatures(
        present=True, code="2", type_text="返回日志关键字指标",
        entries=entries, has_anomaly=any(e.is_anomalous for e in entries),
        raw_block={},
    )
    return bag


# ---- 解析 ---------------------------------------------------------------

def test_parse_hits_extracts_keyword_count_ipcount():
    hits = _parse_log_hits(REAL_MSG)
    assert [h.keyword for h in hits] == [
        "org.springframework.jdbc.CannotGetJdbcConnectionException",
        "does not exist",
        "org.springframework.dao.DuplicateKeyException",
    ]
    assert [h.count for h in hits] == [22, 28, 9]
    assert all(h.ip_count == 10 for h in hits)
    # 样例 IP 被解析、去掉源串自带的 '...'
    assert hits[0].ips[:3] == ["10.28.11.151", "10.28.11.152", "10.28.11.153"]


def test_parse_hits_freeform_msg_yields_no_hits():
    # 不符合"关键词：..."结构的自由文本 → 解析不出，交由兜底原文展示。
    assert _parse_log_hits("connection reset by peer") == []


# ---- VM ----------------------------------------------------------------

def test_anomalous_log_builds_section_with_hits():
    entry = LogKeywordEntry(
        sys_name="财务报销系统", com_name="总公司", msg=REAL_MSG,
        is_anomalous=True, hits=_parse_log_hits(REAL_MSG),
    )
    vm = build_view_model(_bag_with_log([entry]), brief_text="", related=None,
                          bpc_svg=None, log_interpretation="疑似数据库连接与表结构异常。")
    log = vm.brief.log
    assert log.present and vm.brief.present  # 异常日志独立撑出面板
    assert log.entries[0].src == "财务报销系统/总公司"
    assert [h.keyword for h in log.entries[0].hits][0].endswith("CannotGetJdbcConnectionException")
    assert log.entries[0].hits[1].count == "28"
    assert log.interpretation == "疑似数据库连接与表结构异常。"


def test_normal_log_folds_to_note_without_panel():
    entry = LogKeywordEntry(
        sys_name="系统名称2", com_name="总公司",
        msg="日志关键字没有分析出异常", is_anomalous=False, hits=[],
    )
    vm = build_view_model(_bag_with_log([entry]), brief_text="", related=None,
                          bpc_svg=None)
    # 全正常：present 标记在，但无异常条目，且不单独撑出 brief 面板
    assert vm.brief.log.present and vm.brief.log.entries == []
    assert vm.brief.log.normal_note == "日志关键字未分析出异常"
    assert vm.brief.present is False


# ---- HTML --------------------------------------------------------------

def test_html_renders_keyword_highlight_and_interp():
    entry = LogKeywordEntry(
        sys_name="财务报销系统", com_name="总公司", msg=REAL_MSG,
        is_anomalous=True, hits=_parse_log_hits(REAL_MSG),
    )
    html = render_html(_bag_with_log([entry]), brief_text="",
                       related=None, log_interpretation="疑似数据库连接异常。")
    assert 'class="log-kw"' in html                       # 关键词高亮
    assert "does not exist" in html                       # 逐字保真
    assert "28 次 · 10 IP" in html                        # 次数/IP 配料
    assert 'class="log-interp"' in html and "疑似数据库连接异常" in html
