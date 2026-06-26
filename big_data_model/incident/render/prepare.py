"""FeatureBag + brief + related → ViewModel.

所有"形状决策"（截断、escape、分词、超长拆行）集中在此层。
模板内零业务逻辑，只取字段渲染。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from big_data_model.incident.context import RelatedContext
from big_data_model.incident.features import (
    HOST_THRESHOLDS,
    DatabaseFeatures,
    DbInstance,
    FeatureBag,
    HostFeatures,
    HostMetrics,
    LogKeywordFeatures,
    ReleaseRuleFeatures,
)


# ---- Brief 现象简报 ------------------------------------------------------

@dataclass
class BriefSegment:
    text: str
    kind: str  # "plain" | "ms" | "pct" | "time" | "ip" | "dev"


@dataclass
class BriefLine:
    segments: list[BriefSegment]


@dataclass
class BriefSection:
    title: str             # 可能为 ""（无标题，兜底情况）
    lines: list[BriefLine]
    kind: str = ""         # "" | "error"（LLM 失败时的降级段）


@dataclass
class LogHitVM:
    keyword: str                   # 被命中的关键词，高亮主体
    count: str                     # 出现次数
    ip_count: str                  # 波及 IP 数


@dataclass
class LogEntryVM:
    src: str                       # "系统/机构"
    hits: list[LogHitVM]           # 解析出的关键词命中（高亮 + 次数/IP）
    raw_msg: str                   # 解析不出 hits 时的兜底原文（自由文本日志）


@dataclass
class LogSectionVM:
    present: bool                  # 是否渲染该小节（有任何日志条目即 True）
    title: str
    entries: list[LogEntryVM]      # 异常日志（按关键词逐行）；全正常时为空
    interpretation: str            # LLM 一句话研判；可为空
    normal_note: str               # 全正常时的灰字折叠；有异常时为 ""


@dataclass
class BriefVM:
    present: bool
    sections: list[BriefSection]
    log: LogSectionVM


# ---- Banner 疑似根因 ----------------------------------------------------

@dataclass
class BannerVM:
    present: bool
    title: str
    note: str
    rules: list[str]


# ---- 主机表 -------------------------------------------------------------

@dataclass
class HostCellVM:
    text: str
    breach: bool


@dataclass
class HostRowVM:
    ip: str
    is_alarming: bool
    cpu: HostCellVM
    mem: HostCellVM
    iow: HostCellVM
    disk: HostCellVM
    days: str


@dataclass
class HostTableVM:
    present: bool
    cards: list["AlarmCardVM"]  # 主机告警，置于表格上方；与数据库面板同形
    cards_truncated: int        # 实际告警数 - cards 长度
    rows: list[HostRowVM]
    truncated_count: int
    total_count: int
    breach_total: int           # 超阈值 ∪ 告警 去重后的台数
    alarm_count: int            # 告警台数
    breach_only_count: int      # 超阈值但未告警的台数


# ---- 共用告警卡片（主机告警与数据库告警都用此结构） --------------------

@dataclass
class AlarmCardVM:
    host: str
    alert_name: str
    desc: str
    state: str
    is_active: bool


# ---- 数据库板块（告警卡片 + 实例表） ------------------------------------


@dataclass
class DbInstanceRowVM:
    host: str
    db_type: str          # 'ora' / 'gaussdb' 原样
    status_text: str      # '正常' / '探测异常'
    is_normal: bool       # dbStatus == 1
    is_alarming: bool     # host 命中 active 告警，红底置顶
    cpu: HostCellVM
    mem: HostCellVM
    iow: HostCellVM
    disk: HostCellVM
    active_conn: str
    ybp: str              # 原样展示
    days: str


@dataclass
class DbPanelVM:
    present: bool
    cards: list[AlarmCardVM]
    cards_truncated: int
    instances: list[DbInstanceRowVM]
    instance_count: int
    normal_count: int
    abnormal_count: int
    truncated_count: int  # 实际实例数 - instances 长度
    breach_total: int     # 超阈值 ∪ 告警 去重后的实例数


# ---- Related sidecar ----------------------------------------------------

@dataclass
class RelatedIncidentVM:
    severity: str
    severity_kind: str
    ticket_id: str
    body: str


@dataclass
class RelatedChangeVM:
    type_text: str
    type_kind: str
    ticket_id: str
    body: str
    time_range: str


@dataclass
class RelatedVM:
    present: bool
    incidents_header: str
    incidents: list[RelatedIncidentVM]
    changes_header: str
    changes: list[RelatedChangeVM]


# ---- BPC 图块 -----------------------------------------------------------

@dataclass
class BpcLegendItem:
    name: str
    color: str


@dataclass
class BpcVM:
    present: bool
    header: str
    svg: str
    legend: list[BpcLegendItem]  # 多系统时 "系统→颜色" 映射，单系统为空


# ---- Dashboard 顶层 -----------------------------------------------------

@dataclass
class DashboardVM:
    title: str
    incident_id: Optional[str]
    snapshot_time: Optional[str]
    brief: BriefVM
    banner: BannerVM
    bpc: BpcVM
    hosts: HostTableVM
    related: RelatedVM
    db_panel: DbPanelVM


# ===== 实现 ==============================================================

_TABLE_MAX_ROWS = 20
_ALARM_CARDS_MAX = 20

# 高亮规则（顺序即优先级，非重叠匹配）
_BRIEF_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\d+(?:\.\d+)?ms"),                              "ms"),
    (re.compile(r"\d+(?:\.\d+)?%"),                               "pct"),
    (re.compile(r"\d{1,2}:\d{2}(?::\d{2})?"),                     "time"),
    (re.compile(r"\d{1,3}(?:\.\d{1,3}){2,3}(?:\.x)?"),            "ip"),
    (re.compile(r"×\d+(?:\.\d+)?"),                               "dev"),
]


def _segment_line(line: str) -> list[BriefSegment]:
    spans: list[tuple[int, int, str]] = []
    for pat, kind in _BRIEF_RULES:
        for m in pat.finditer(line):
            spans.append((m.start(), m.end(), kind))
    spans.sort()

    cleaned: list[tuple[int, int, str]] = []
    last_end = -1
    for s, e, k in spans:
        if s >= last_end:
            cleaned.append((s, e, k))
            last_end = e

    out: list[BriefSegment] = []
    pos = 0
    for s, e, k in cleaned:
        if s > pos:
            out.append(BriefSegment(line[pos:s], "plain"))
        out.append(BriefSegment(line[s:e], k))
        pos = e
    if pos < len(line):
        out.append(BriefSegment(line[pos:], "plain"))
    return out


_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")

# LLM 返回内容里出现这些关键词，视为 LLM 自身不可用——不是真正的故障简报。
_LLM_ERROR_MARKERS = ("模型存在问题", "[LLM_ERROR]")
_LLM_FALLBACK_TEXT = "Qwen 大模型接口异常，暂无法生成现象简报"


def _is_llm_error(text: str) -> bool:
    return any(m in text for m in _LLM_ERROR_MARKERS)


def _empty_log() -> LogSectionVM:
    return LogSectionVM(present=False, title="", entries=[],
                        interpretation="", normal_note="")


def _build_log(
    lk: Optional[LogKeywordFeatures], interpretation: Optional[str]
) -> LogSectionVM:
    """异常日志按关键词确定性渲染 + LLM 一句话研判挂在旁边。

    - 有异常日志：每个命中关键词单独成行（关键词高亮、次数/IP 作次要信息）；
      解析不出结构的自由文本日志，兜底展示原始 msg。
    - 全部正常：折叠成一句灰字，不展开。
    - 无日志信号：present=False，整块消失。
    """
    if not lk or not lk.present or not lk.entries:
        return _empty_log()
    entries = [
        LogEntryVM(
            src=f"{e.sys_name}/{e.com_name}".strip("/"),
            hits=[
                LogHitVM(keyword=h.keyword, count=str(h.count), ip_count=str(h.ip_count))
                for h in e.hits
            ],
            raw_msg="" if e.hits else e.msg,
        )
        for e in lk.entries if e.is_anomalous
    ]
    if entries:
        return LogSectionVM(
            present=True, title="日志关键字", entries=entries,
            interpretation=(interpretation or "").strip(), normal_note="",
        )
    return LogSectionVM(
        present=True, title="日志关键字", entries=[],
        interpretation="", normal_note="日志关键字未分析出异常",
    )


def _error_brief(log: LogSectionVM) -> BriefVM:
    return BriefVM(present=True, log=log, sections=[
        BriefSection(
            title="", kind="error",
            lines=[BriefLine(segments=[BriefSegment(_LLM_FALLBACK_TEXT, "plain")])],
        ),
    ])


def _build_brief(brief_text: Optional[str], log: LogSectionVM) -> BriefVM:
    """把 LLM 输出按 `## 标题` 切成小节，并挂上日志小节。

    若文本里没有任何 `## ` 行（旧 brief 或 LLM 漏写），全部归入一个无标题 section。
    面板是否出现由"有 LLM 小节 或 有异常日志"决定——全正常的日志不会单独撑出面板。
    """
    has_anom_log = bool(log.entries)
    if not brief_text or not brief_text.strip():
        return BriefVM(present=has_anom_log, sections=[], log=log)
    if _is_llm_error(brief_text):
        return _error_brief(log)

    sections: list[BriefSection] = []
    current_title = ""
    current_lines: list[BriefLine] = []

    def flush() -> None:
        if current_title or current_lines:
            sections.append(BriefSection(title=current_title, lines=list(current_lines)))

    for raw in brief_text.strip().split("\n"):
        m = _HEADING_RE.match(raw)
        if m:
            flush()
            current_title = m.group(1).strip()
            current_lines = []
        else:
            if not raw.strip() and not current_lines:
                continue  # 标题后空行跳过
            current_lines.append(BriefLine(segments=_segment_line(raw)))
    flush()

    return BriefVM(present=bool(sections) or has_anom_log, sections=sections, log=log)


def _build_banner(rrf: Optional[ReleaseRuleFeatures]) -> BannerVM:
    # 仅当存在"近期"发布（默认 12h 内）时才置顶 banner。
    # 陈旧的发布几乎不是当前事件触发源，让位给主机/数据库等现场告警；
    # 简报里会照常带上 rules 字段，LLM 仍可在现象段提及它。
    if not rrf or not rrf.present or not rrf.is_recent:
        return BannerVM(present=False, title="", note="", rules=[])
    n = len(rrf.rules)
    title = "疑似事件根因 · 核保规则发布" + (f"（{n} 条）" if n > 1 else "")
    return BannerVM(
        present=True,
        title=title,
        note="发布动作往往直接触发当前异常，请优先核查",
        rules=list(rrf.rules),
    )


def _cell(value: str, breach: bool) -> HostCellVM:
    return HostCellVM(text=value, breach=breach)


def _host_severity_key(h: HostMetrics, alarm_hosts: set[str]) -> tuple[int, float]:
    """与旧 charts.py _host_severity 保持一致：(违例数, 综合分)。"""
    breaches = 0
    if h.cpu_pct > HOST_THRESHOLDS["cpu_high_pct"]:
        breaches += 1
    if h.memory_pct > HOST_THRESHOLDS["memory_high_pct"]:
        breaches += 1
    if h.iowait_pct > HOST_THRESHOLDS["iowait_high_pct"]:
        breaches += 1
    if h.disk_pct > HOST_THRESHOLDS["disk_high_pct"]:
        breaches += 1
    if h.host in alarm_hosts:
        breaches += 1
    composite = (
        max(0.0, h.cpu_pct - HOST_THRESHOLDS["cpu_high_pct"])
        + max(0.0, h.memory_pct - HOST_THRESHOLDS["memory_high_pct"])
        + max(0.0, h.iowait_pct - HOST_THRESHOLDS["iowait_high_pct"]) * 1.5
        + max(0.0, h.disk_pct - HOST_THRESHOLDS["disk_high_pct"])
    )
    return (breaches, composite)


def _alarm_cards(alarms, limit: int = _ALARM_CARDS_MAX) -> tuple[list[AlarmCardVM], int]:
    """主机告警与数据库告警共用的卡片构建。

    排序：active 在前、resolved 在后。
    截断：最多 ``limit`` 条，返回 (cards, truncated_count)。
    """
    ordered = sorted(alarms, key=lambda a: not a.is_active)
    shown = ordered[:limit]
    truncated = max(0, len(ordered) - len(shown))
    cards = [
        AlarmCardVM(
            host=a.host,
            alert_name=a.alert_name or "（未命名告警）",
            desc=a.desc,
            state=a.state or ("未恢复" if a.is_active else "已恢复"),
            is_active=a.is_active,
        )
        for a in shown
    ]
    return cards, truncated


def _build_hosts(hf: Optional[HostFeatures]) -> HostTableVM:
    if not hf or not hf.present or not hf.hosts:
        return HostTableVM(present=False, cards=[], cards_truncated=0,
                           rows=[], truncated_count=0,
                           total_count=0, breach_total=0, alarm_count=0,
                           breach_only_count=0)

    alarm_hosts: set[str] = {a.host for a in hf.alarms if a.is_active}
    breach_ips: set[str] = set()
    for ips in hf.breaches.values():
        breach_ips.update(ips)
    breach_total = len(breach_ips | alarm_hosts)

    def _breach_count(h: HostMetrics) -> int:
        n = 0
        if h.cpu_pct    > HOST_THRESHOLDS["cpu_high_pct"]:    n += 1
        if h.memory_pct > HOST_THRESHOLDS["memory_high_pct"]: n += 1
        if h.iowait_pct > HOST_THRESHOLDS["iowait_high_pct"]: n += 1
        if h.disk_pct   > HOST_THRESHOLDS["disk_high_pct"]:   n += 1
        return n

    # 三层排序：告警优先，其次超阈值（按超阈值数 desc），其余按 CPU+IOwait desc。
    # 同层内 fallback 都用 CPU+IOwait desc 做二级排序。
    alarm_rows = [h for h in hf.hosts if h.host in alarm_hosts]
    alarm_rows.sort(key=lambda h: _host_severity_key(h, alarm_hosts), reverse=True)
    breach_rows = [
        h for h in hf.hosts
        if h.host not in alarm_hosts and h.host in breach_ips
    ]
    breach_rows.sort(key=lambda h: (_breach_count(h), h.cpu_pct + h.iowait_pct), reverse=True)
    other_rows = [
        h for h in hf.hosts
        if h.host not in alarm_hosts and h.host not in breach_ips
    ]
    other_rows.sort(key=lambda h: h.cpu_pct + h.iowait_pct, reverse=True)
    ordered = alarm_rows + breach_rows + other_rows

    shown = ordered[:_TABLE_MAX_ROWS]
    truncated = max(0, len(ordered) - len(shown))

    rows: list[HostRowVM] = []
    for h in shown:
        rows.append(HostRowVM(
            ip=h.host,
            is_alarming=h.host in alarm_hosts,
            cpu=_cell(f"{h.cpu_pct:.0f}%",
                     h.cpu_pct > HOST_THRESHOLDS["cpu_high_pct"]),
            mem=_cell(f"{h.memory_pct:.0f}%",
                     h.memory_pct > HOST_THRESHOLDS["memory_high_pct"]),
            iow=_cell(f"{h.iowait_pct:.1f}%",
                     h.iowait_pct > HOST_THRESHOLDS["iowait_high_pct"]),
            disk=_cell(f"{h.disk_pct:.0f}%",
                      h.disk_pct > HOST_THRESHOLDS["disk_high_pct"]),
            days=str(h.running_days),
        ))

    host_cards, host_cards_truncated = _alarm_cards(hf.alarms)
    return HostTableVM(
        present=True,
        cards=host_cards,
        cards_truncated=host_cards_truncated,
        rows=rows,
        truncated_count=truncated,
        total_count=hf.host_count,
        breach_total=breach_total,
        alarm_count=len(alarm_rows),
        breach_only_count=len(breach_rows),
    )


_SEV_KIND = {"严重": "sev-high", "重要": "sev-mid", "一般": "sev-low"}


def _build_related(ctx: Optional[RelatedContext]) -> RelatedVM:
    if ctx is None or ctx.is_empty:
        return RelatedVM(present=False, incidents_header="", incidents=[],
                         changes_header="", changes=[])

    incidents = [
        RelatedIncidentVM(
            severity=i.severity,
            severity_kind=_SEV_KIND.get(i.severity, "sev-low"),
            ticket_id=i.ticket_id,
            body=i.text,
        )
        for i in ctx.incidents
    ]
    changes = [
        RelatedChangeVM(
            type_text=c.type_text,
            type_kind="change" if "变更" in c.type_text else "release",
            ticket_id=c.ticket_id,
            body=c.title,
            time_range=c.time_range,
        )
        for c in ctx.changes
    ]
    return RelatedVM(
        present=True,
        incidents_header=ctx.incidents_header,
        incidents=incidents,
        changes_header=ctx.changes_header,
        changes=changes,
    )


def _bpc_header(bag: FeatureBag) -> str:
    if not bag.bpc or not bag.bpc.systems:
        return "BPC 监控"
    names = [s.system_name for s in bag.bpc.systems]
    if len(names) == 1:
        return f"BPC 监控 · {names[0]}"
    if len(names) <= 3:
        return f"BPC 监控 · {len(names)} 个系统：" + "、".join(names)
    return f"BPC 监控 · {len(names)} 个系统：" + "、".join(names[:3]) + " 等"


def _build_bpc(
    bag: FeatureBag,
    svg: Optional[str],
    legend: Optional[list[tuple[str, str]]] = None,
) -> BpcVM:
    if not (bag.bpc and bag.bpc.systems and svg):
        return BpcVM(present=False, header="", svg="", legend=[])
    items = [BpcLegendItem(name=name, color=color) for name, color in (legend or [])]
    return BpcVM(present=True, header=_bpc_header(bag), svg=svg, legend=items)


def _build_db_instance_row(i: DbInstance, alarm_hosts: set[str]) -> DbInstanceRowVM:
    is_normal = i.db_status == 1
    return DbInstanceRowVM(
        host=i.host,
        db_type=i.db_type,
        status_text="正常" if is_normal else "探测异常",
        is_normal=is_normal,
        is_alarming=i.host in alarm_hosts,
        cpu=_cell(f"{i.cpu_pct:.0f}%",
                  i.cpu_pct > HOST_THRESHOLDS["cpu_high_pct"]),
        mem=_cell(f"{i.memory_pct:.0f}%",
                  i.memory_pct > HOST_THRESHOLDS["memory_high_pct"]),
        iow=_cell(f"{i.iowait_pct:.1f}%",
                  i.iowait_pct > HOST_THRESHOLDS["iowait_high_pct"]),
        disk=_cell(f"{i.disk_pct:.0f}%",
                   i.disk_pct > HOST_THRESHOLDS["disk_high_pct"]),
        active_conn=str(i.active_conn),
        ybp=i.ybp,
        days=str(i.running_days),
    )


def _db_breach_count(i: DbInstance) -> int:
    n = 0
    if i.cpu_pct    > HOST_THRESHOLDS["cpu_high_pct"]:    n += 1
    if i.memory_pct > HOST_THRESHOLDS["memory_high_pct"]: n += 1
    if i.iowait_pct > HOST_THRESHOLDS["iowait_high_pct"]: n += 1
    if i.disk_pct   > HOST_THRESHOLDS["disk_high_pct"]:   n += 1
    return n


def _build_db_panel(db: Optional[DatabaseFeatures]) -> DbPanelVM:
    """只要上游回了数据库信号且至少有 1 个实例就画面板；告警只决定置顶高亮。

    面板内含两个子区块：
    1. 告警卡片（仅当存在告警时显示；active 在前、resolved 在后视觉降权）
    2. 实例概览表，与主机表同形：
       - 告警实例红底置顶（按 severity 排）
       - 超阈值未告警的次之（按超阈值数、CPU+IOwait 排）
       - 其余按 CPU+IOwait 排
       - 探测异常的实例（probe failed）落到对应层级末尾，视觉降权
       - 截断到 _TABLE_MAX_ROWS
    """
    empty = DbPanelVM(
        present=False, cards=[], cards_truncated=0, instances=[],
        instance_count=0, normal_count=0, abnormal_count=0,
        truncated_count=0, breach_total=0,
    )
    if not db or not db.present or not db.instances:
        return empty

    cards, cards_truncated = _alarm_cards(db.alarms)

    alarm_hosts: set[str] = {a.host for a in db.alarms if a.is_active}
    breach_ips: set[str] = {
        i.host for i in db.instances if _db_breach_count(i) > 0
    }
    breach_total = len(breach_ips | alarm_hosts)

    # 三层排序：告警优先，其次超阈值（按超阈值数 desc），其余按 CPU+IOwait desc。
    # 在每一层内部，探测异常的实例再落到末尾——保留旧行为里"probe 失败降权"的语义。
    def _probe_rank(i: DbInstance) -> int:
        return 0 if i.db_status == 1 else 1

    alarm_inst = [i for i in db.instances if i.host in alarm_hosts]
    alarm_inst.sort(
        key=lambda i: (
            _probe_rank(i),
            -_host_severity_key(i, alarm_hosts)[0],
            -_host_severity_key(i, alarm_hosts)[1],
        )
    )
    breach_inst = [
        i for i in db.instances
        if i.host not in alarm_hosts and i.host in breach_ips
    ]
    breach_inst.sort(
        key=lambda i: (
            _probe_rank(i),
            -_db_breach_count(i),
            -(i.cpu_pct + i.iowait_pct),
        )
    )
    other_inst = [
        i for i in db.instances
        if i.host not in alarm_hosts and i.host not in breach_ips
    ]
    other_inst.sort(key=lambda i: (_probe_rank(i), -(i.cpu_pct + i.iowait_pct)))
    ordered = alarm_inst + breach_inst + other_inst

    shown = ordered[:_TABLE_MAX_ROWS]
    truncated = max(0, len(ordered) - len(shown))
    instances = [_build_db_instance_row(i, alarm_hosts) for i in shown]

    return DbPanelVM(
        present=True,
        cards=cards,
        cards_truncated=cards_truncated,
        instances=instances,
        instance_count=db.instance_count,
        normal_count=db.normal_count,
        abnormal_count=db.abnormal_count,
        truncated_count=truncated,
        breach_total=breach_total,
    )


def build_view_model(
    bag: FeatureBag,
    brief_text: Optional[str],
    related: Optional[RelatedContext],
    bpc_svg: Optional[str],
    bpc_legend: Optional[list[tuple[str, str]]] = None,
    log_interpretation: Optional[str] = None,
    incident_id: Optional[str] = None,
    order_number: Optional[str] = None,
) -> DashboardVM:
    snapshot = bag.cross.snapshot_time if bag.cross else None
    title_parts = ["事件会诊速览"]
    if incident_id:
        title_parts.append(str(incident_id))
    if snapshot:
        title_parts.append(snapshot)
    if order_number:
        title_parts.append(order_number)
    title = "   ·   ".join(title_parts)

    return DashboardVM(
        title=title,
        incident_id=incident_id,
        snapshot_time=snapshot,
        brief=_build_brief(brief_text, _build_log(bag.log_keywords, log_interpretation)),
        banner=_build_banner(bag.release_rules),
        bpc=_build_bpc(bag, bpc_svg, bpc_legend),
        hosts=_build_hosts(bag.hosts),
        related=_build_related(related),
        db_panel=_build_db_panel(bag.databases),
    )
