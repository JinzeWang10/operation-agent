"""ViewModel 单元测试：覆盖坏数据形状。

目标：当数据异常（爆量、含 HTML 特殊字符、IPv6、长 URL）时，prepare 层
不崩、不静默丢数据，截断协议生效。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from big_data_model.incident.context import (
    ChangeTicket,
    IncidentTicket,
    RelatedContext,
)
from big_data_model.incident.features import (
    FeatureBag,
    HostAlarm,
    HostFeatures,
    HostMetrics,
    ReleaseRuleFeatures,
    extract,
)
from big_data_model.incident.render.prepare import build_view_model


SAMPLE_DIR = Path(__file__).parents[2] / "big_data_model" / "incident" / "sample"


@pytest.fixture
def real_bag() -> FeatureBag:
    payload = ast.literal_eval((SAMPLE_DIR / "text.txt").read_text(encoding="utf-8"))
    return extract(payload)


# ---- Brief 分词 -------------------------------------------------------

def test_brief_segments_classify_numbers_and_times(real_bag):
    brief = ("耗时峰值 2179ms，成功率 96.43%@14:38，"
             "子网 172.20.31.x，偏离 ×8.4。")
    vm = build_view_model(real_bag, brief_text=brief, related=None, bpc_svg=None)
    kinds = [s.kind for sec in vm.brief.sections for line in sec.lines for s in line.segments]
    assert "ms" in kinds and "pct" in kinds and "time" in kinds
    assert "ip" in kinds and "dev" in kinds


def test_brief_with_long_url_does_not_break(real_bag):
    """长 URL 不应该破坏分词或抛错。"""
    brief = "参考 https://example.com/very/long/path?a=1&b=2#frag 耗时 100ms"
    vm = build_view_model(real_bag, brief_text=brief, related=None, bpc_svg=None)
    flat = "".join(s.text for sec in vm.brief.sections for line in sec.lines for s in line.segments)
    assert "100ms" in flat
    assert "https://example.com" in flat


def test_brief_html_special_chars_escaped_at_render_time(real_bag):
    """prepare 层不做 escape（autoescape 由 Jinja 在模板渲染时执行）。
    这里只验证文本原样进入 segment，不被 prepare 误处理。"""
    brief = "异常告警 <script>alert(1)</script> 出现"
    vm = build_view_model(real_bag, brief_text=brief, related=None, bpc_svg=None)
    flat = "".join(s.text for sec in vm.brief.sections for line in sec.lines for s in line.segments)
    assert "<script>" in flat
    assert "</script>" in flat


def test_brief_empty_returns_not_present(real_bag):
    # 隔离日志小节：本测试只验证"空简报文本 → 无 LLM 小节、面板不出现"。
    # （异常日志会单独让面板出现，那条路径由 test_log_keywords 覆盖。）
    real_bag.log_keywords = None
    vm = build_view_model(real_bag, brief_text="", related=None, bpc_svg=None)
    assert vm.brief.present is False
    assert vm.brief.sections == []


def test_brief_parses_markdown_subtitles(real_bag):
    brief = ("## 业务指标\n"
             "BPC 耗时峰值 1234ms。\n"
             "\n"
             "## 主机与告警\n"
             "172.20.31.x 集中告警。\n"
             "活跃告警 4 起。\n")
    vm = build_view_model(real_bag, brief_text=brief, related=None, bpc_svg=None)
    titles = [s.title for s in vm.brief.sections]
    assert titles == ["业务指标", "主机与告警"]
    assert len(vm.brief.sections[1].lines) == 2


def test_brief_llm_error_content_renders_fallback(real_bag):
    """LLM 返回内容含'模型存在问题'，应替换为降级文案。"""
    vm = build_view_model(real_bag, brief_text="模型存在问题",
                          related=None, bpc_svg=None)
    assert vm.brief.present is True
    assert len(vm.brief.sections) == 1
    assert vm.brief.sections[0].kind == "error"
    text = vm.brief.sections[0].lines[0].segments[0].text
    assert "Qwen" in text and "暂无法生成" in text


def test_brief_llm_error_sentinel_renders_fallback(real_bag):
    """render_report 在异常时塞入的 [LLM_ERROR] 哨兵也走降级。"""
    vm = build_view_model(real_bag, brief_text="[LLM_ERROR]",
                          related=None, bpc_svg=None)
    assert vm.brief.sections[0].kind == "error"


def test_brief_without_subtitles_falls_back_to_single_section(real_bag):
    """LLM 漏写 ## 的兜底：整段归入 title='' 的单 section，仍然渲染。"""
    brief = "一段没有任何小标题的简报，含 100ms。"
    vm = build_view_model(real_bag, brief_text=brief, related=None, bpc_svg=None)
    assert len(vm.brief.sections) == 1
    assert vm.brief.sections[0].title == ""
    assert len(vm.brief.sections[0].lines) == 1


# ---- 主机表截断 -------------------------------------------------------

def _make_host(ip: str, cpu=10.0, mem=10.0, iow=0.0, disk=10.0, days=100):
    return HostMetrics(
        host=ip, cpu_pct=cpu, memory_pct=mem,
        iowait_pct=iow, iowait_raw=iow / 100, disk_pct=disk,
        running_days=days, subnet24=ip.rsplit(".", 1)[0],
        subnet16=".".join(ip.split(".")[:2]),
    )


def _bag_with_hosts(hosts, alarms=()):
    bag = FeatureBag(raw_meta={})
    breaches = {
        "cpu_high": [h.host for h in hosts if h.cpu_pct > 80],
        "memory_high": [h.host for h in hosts if h.memory_pct > 85],
        "iowait_high": [h.host for h in hosts if h.iowait_pct > 30],
        "disk_high": [h.host for h in hosts if h.disk_pct > 80],
    }
    bag.hosts = HostFeatures(
        present=True, code="0", type_text="设备-主机",
        alarms=list(alarms),
        active_alarm_count=sum(1 for a in alarms if a.is_active),
        hosts=hosts, host_count=len(hosts),
        cpu_stats={}, memory_stats={}, iowait_stats={}, disk_stats={},
        subnets={}, breaches=breaches, cohorts=[], breach_clusters=[],
        top_iowait=[], top_memory=[], top_cpu=[], top_disk=[],
        longest_uptime=[], raw_block={},
    )
    return bag


def test_hosts_truncate_excess_with_count():
    # 50 台全部超 iowait 阈值，表格上限 20 行（_TABLE_MAX_ROWS）
    hosts = [_make_host(f"10.0.0.{i}", iow=50.0) for i in range(1, 51)]
    bag = _bag_with_hosts(hosts)
    vm = build_view_model(bag, brief_text=None, related=None, bpc_svg=None)
    assert len(vm.hosts.rows) == 20
    assert vm.hosts.truncated_count == 30
    assert vm.hosts.total_count == 50
    assert vm.hosts.breach_total == 50


def test_hosts_no_breach_still_all_shown():
    """无越限也全量展示（告警 → 越限 → 其余 三层排序的第三层）。"""
    hosts = [_make_host(f"10.0.0.{i}", cpu=5.0, mem=10.0) for i in range(1, 6)]
    bag = _bag_with_hosts(hosts)
    vm = build_view_model(bag, brief_text=None, related=None, bpc_svg=None)
    assert len(vm.hosts.rows) == 5
    assert vm.hosts.truncated_count == 0
    assert vm.hosts.total_count == 5
    assert vm.hosts.breach_total == 0
    assert all(not r.is_alarming for r in vm.hosts.rows)


def test_hosts_breach_cell_flag():
    hosts = [_make_host("10.0.0.1", cpu=95.0, iow=50.0)]
    bag = _bag_with_hosts(hosts)
    vm = build_view_model(bag, brief_text=None, related=None, bpc_svg=None)
    row = vm.hosts.rows[0]
    assert row.cpu.breach is True
    assert row.iow.breach is True
    assert row.mem.breach is False
    assert row.disk.breach is False


def test_hosts_ipv6_preserved():
    hosts = [_make_host("fe80::1234:abcd:5678:90ef", cpu=95.0)]
    hosts[0] = HostMetrics(
        host="fe80::1234:abcd:5678:90ef",
        cpu_pct=95.0, memory_pct=10.0, iowait_pct=0.0, iowait_raw=0.0,
        disk_pct=10.0, running_days=10, subnet24="fe80::", subnet16="fe80",
    )
    bag = _bag_with_hosts(hosts)
    # 手动注入 breaches（_bag_with_hosts 的 breach 判断基于 IPv4 阈值，但
    # IPv6 主机 cpu>80 会被 cpu_high 收集）
    bag.hosts.breaches["cpu_high"] = ["fe80::1234:abcd:5678:90ef"]
    vm = build_view_model(bag, brief_text=None, related=None, bpc_svg=None)
    assert vm.hosts.rows[0].ip == "fe80::1234:abcd:5678:90ef"


def test_hosts_long_alarm_becomes_card_full_text():
    """告警不再挂在行内 alarm_text，改为表格上方的告警卡片；
    卡片文本不做字符硬截断（溢出由 CSS 处理），行上保留 is_alarming 标记。"""
    long_alarm = "这是一个非常非常长的告警名称，长到旧版本会被字符截断到 22 字" * 2
    hosts = [_make_host("10.0.0.1", cpu=95.0)]
    alarms = [
        HostAlarm(
            host="10.0.0.1", alert_name=long_alarm, desc="",
            endtime="", state="未恢复", is_active=True,
        )
    ]
    bag = _bag_with_hosts(hosts, alarms=alarms)
    bag.hosts.breaches["cpu_high"] = ["10.0.0.1"]
    vm = build_view_model(bag, brief_text=None, related=None, bpc_svg=None)
    assert vm.hosts.cards[0].alert_name == long_alarm
    assert vm.hosts.cards[0].is_active is True
    assert vm.hosts.rows[0].is_alarming is True
    assert vm.hosts.alarm_count == 1


# ---- Banner 不截断 ----------------------------------------------------

def test_banner_many_rules_all_kept():
    rules = [f"RuleNumber{i}已发布:{i}分钟" for i in range(1, 21)]
    bag = FeatureBag(raw_meta={})
    bag.release_rules = ReleaseRuleFeatures(
        present=True, code="0", type_text="核保规则发布情况",
        rules=rules, raw_block={},
    )
    vm = build_view_model(bag, brief_text=None, related=None, bpc_svg=None)
    assert vm.banner.present is True
    assert len(vm.banner.rules) == 20
    assert vm.banner.rules[-1] == "RuleNumber20已发布:20分钟"


def test_banner_absent_when_no_rules():
    bag = FeatureBag(raw_meta={})
    vm = build_view_model(bag, brief_text=None, related=None, bpc_svg=None)
    assert vm.banner.present is False


# ---- Related ---------------------------------------------------------

def test_related_kinds_correctly_classified():
    ctx = RelatedContext(
        incidents_header="关联事件",
        incidents=[IncidentTicket(ticket_id="INM-1", severity="严重", text="x")],
        changes_header="关联变更",
        changes=[
            ChangeTicket(ticket_id="CHM-1", type_text="变更",
                         title="t1", time_range="1h"),
            ChangeTicket(ticket_id="DRM-1", type_text="升级发布",
                         title="t2", time_range="2h"),
        ],
    )
    bag = FeatureBag(raw_meta={})
    vm = build_view_model(bag, brief_text=None, related=ctx, bpc_svg=None)
    assert vm.related.present is True
    assert vm.related.incidents[0].severity_kind == "sev-high"
    assert vm.related.changes[0].type_kind == "change"
    assert vm.related.changes[1].type_kind == "release"


def test_related_none_returns_absent():
    bag = FeatureBag(raw_meta={})
    vm = build_view_model(bag, brief_text=None, related=None, bpc_svg=None)
    assert vm.related.present is False
