"""FeatureBag extraction layer.

Parses a monitoring snapshot (the raw JSON returned by the company's monitoring
aggregator) into a typed, structured bag of features that downstream consumers
(deterministic renderers, LLM summarizer) can read uniformly.

Design principles:
- **Lossless**: every input field reachable from the bag. Each per-monitor
  feature object stores the original block under ``raw_block`` so nothing is
  lost in transformation.
- **Tri-state per monitor**: a monitor can be present-with-data, present-but-
  empty, interface-failed, or absent. Downstream consumers must handle all
  four; this module surfaces them explicitly.
- **Derived views are additive**: percentiles, top-N, cohorts, severity scores
  are computed on top of the raw values, never replacing them.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Callable, Optional

CN_TZ = timezone(timedelta(hours=8))

# -- thresholds / config ---------------------------------------------------

HOST_THRESHOLDS = {
    "cpu_high_pct": 80.0,
    "memory_high_pct": 98.0,
    "iowait_high_pct": 25.0,
    "disk_high_pct": 95.0,
}

NORMAL_LOG_PATTERNS = ("没有分析出异常", "无异常", "正常")

# -- low-level helpers ----------------------------------------------------


def _to_float(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip("%")
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _to_int(v: Any) -> int:
    if v is None or v == "":
        return 0
    if isinstance(v, int):
        return v
    s = str(v).strip().rstrip("%")
    try:
        return int(float(s)) if s else 0
    except ValueError:
        return 0


def _to_float_opt(v: Any) -> Optional[float]:
    """Like _to_float but returns None for empty / unparseable inputs.

    Used for BPC timepoint values where upstream sometimes emits an empty
    last bucket — collapsing that to 0 would falsely show a cliff in the chart.
    """
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip("%")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int_opt(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip().rstrip("%")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


def _stats(values: list[float]) -> Optional[dict]:
    if not values:
        return None
    s = sorted(values)
    return {
        "min": s[0],
        "p50": _percentile(s, 50),
        "p90": _percentile(s, 90),
        "p95": _percentile(s, 95),
        "max": s[-1],
        "mean": sum(s) / len(s),
    }


def _subnet(ip: str, octets: int) -> str:
    parts = ip.split(".")
    return ".".join(parts[:octets]) if len(parts) >= octets else ip


def _format_ts_ms(ts_ms: Optional[int]) -> Optional[str]:
    if ts_ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=CN_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(ts_ms)


# -- BPC -------------------------------------------------------------------


@dataclass
class BpcTimepoint:
    timestamp: str
    # Optional: upstream may emit an empty bucket (typically the trailing
    # window mid-collection). Keep that explicit instead of backfilling 0,
    # which would draw a spurious cliff on the chart.
    duration_ms: Optional[float]
    rr_rate_pct: Optional[float]
    succ_rate_pct: Optional[float]
    trans_count: Optional[int]


@dataclass
class BpcSpike:
    timestamp: str
    metric: str
    value: float
    baseline: float
    deviation_x: float


@dataclass
class BpcSystemFeatures:
    system_name: str
    timepoints: list[BpcTimepoint]
    point_count: int
    duration_baseline_ms: float
    duration_max_ms: float
    duration_max_ts: str
    duration_deviation_x: float
    rr_rate_baseline_pct: float
    rr_rate_min_pct: float
    rr_rate_min_ts: str
    succ_rate_baseline_pct: float
    succ_rate_min_pct: float
    succ_rate_min_ts: str
    trans_count_baseline: float
    trans_count_min: int
    trans_count_max: int
    trans_count_last: Optional[int]  # None when last bucket arrived empty
    spikes: list[BpcSpike]
    symptom_type: str
    severity_score: float


@dataclass
class BpcFeatures:
    present: bool
    code: str
    type_text: str
    systems: list[BpcSystemFeatures]
    severity_score: float
    raw_block: dict


def _classify_bpc_symptom(
    dur_dev: float,
    rr_drop: float,
    succ_drop: float,
    volume_drop_ratio: float,
) -> str:
    flags = []
    if dur_dev >= 2:
        flags.append("slow")
    if succ_drop > 0.5:
        flags.append("errors")
    if rr_drop > 1.0:
        flags.append("response_drop")
    if volume_drop_ratio < 0.5:
        flags.append("volume_drop")
    return "+".join(flags) if flags else "normal"


def _score_bpc(
    dur_dev: float, succ_min: float, rr_min: float
) -> float:
    score = 0.0
    if dur_dev > 1:
        score += min(60.0, math.log10(dur_dev) * 30.0)
    score += max(0.0, 100.0 - succ_min) * 20.0
    score += max(0.0, 100.0 - rr_min - 1.0) * 5.0
    return min(100.0, score)


def _extract_bpc(block: dict) -> BpcFeatures:
    msg = block.get("message") or {}
    sys_map = msg.get("bpcAlarmtypeMap") or {}
    systems: list[BpcSystemFeatures] = []
    overall = 0.0

    for sys_name, ts_map in sys_map.items():
        if not ts_map:
            continue
        points = [
            BpcTimepoint(
                timestamp=ts,
                duration_ms=_to_float_opt(ts_map[ts].get("duration")),
                rr_rate_pct=_to_float_opt(ts_map[ts].get("rr_rate")),
                succ_rate_pct=_to_float_opt(ts_map[ts].get("succ_rate")),
                trans_count=_to_int_opt(ts_map[ts].get("trans_count")),
            )
            for ts in sorted(ts_map.keys())
        ]
        # None means "no data for that bucket" — exclude from aggregates so a
        # missing tail bucket doesn't drag baselines/mins down to zero.
        dur_pts = [p for p in points if p.duration_ms is not None]
        rr_pts = [p for p in points if p.rr_rate_pct is not None]
        succ_pts = [p for p in points if p.succ_rate_pct is not None]
        trans_pts = [p for p in points if p.trans_count is not None]
        durations = [p.duration_ms for p in dur_pts]
        rr_rates = [p.rr_rate_pct for p in rr_pts]
        succ_rates = [p.succ_rate_pct for p in succ_pts]
        trans = [p.trans_count for p in trans_pts]

        dur_baseline = median(durations) if durations else 0.0
        dur_max_p = max(dur_pts, key=lambda p: p.duration_ms) if dur_pts else None
        rr_min_p = min(rr_pts, key=lambda p: p.rr_rate_pct) if rr_pts else None
        succ_min_p = (
            min(succ_pts, key=lambda p: p.succ_rate_pct) if succ_pts else None
        )
        # last point is often a partial window — exclude from baseline
        trans_baseline = median(trans[:-1]) if len(trans) > 1 else (
            median(trans) if trans else 0.0
        )

        spikes = [
            BpcSpike(
                timestamp=p.timestamp,
                metric="duration",
                value=p.duration_ms,
                baseline=dur_baseline,
                deviation_x=p.duration_ms / dur_baseline,
            )
            for p in dur_pts
            if dur_baseline > 0 and p.duration_ms / dur_baseline >= 3
        ]

        dur_max_val = dur_max_p.duration_ms if dur_max_p else 0.0
        dur_max_ts = dur_max_p.timestamp if dur_max_p else ""
        dur_dev = dur_max_val / dur_baseline if dur_baseline else 1.0
        rr_min_val = rr_min_p.rr_rate_pct if rr_min_p else 0.0
        rr_min_ts = rr_min_p.timestamp if rr_min_p else ""
        succ_min_val = succ_min_p.succ_rate_pct if succ_min_p else 0.0
        succ_min_ts = succ_min_p.timestamp if succ_min_p else ""

        rr_drop = median(rr_rates) - rr_min_val if rr_rates else 0.0
        succ_drop = (
            median(succ_rates) - succ_min_val if succ_rates else 0.0
        )
        volume_drop_ratio = (
            (min(trans[:-1]) / trans_baseline)
            if len(trans) >= 3 and trans_baseline > 0
            else 1.0
        )

        symptom = _classify_bpc_symptom(
            dur_dev, rr_drop, succ_drop, volume_drop_ratio
        )
        severity = _score_bpc(dur_dev, succ_min_val, rr_min_val)
        overall = max(overall, severity)

        # trans_count_last: keep None when the trailing bucket is empty so the
        # renderer can show "—" instead of an incorrect "0".
        trans_last = points[-1].trans_count if points else None

        systems.append(
            BpcSystemFeatures(
                system_name=sys_name,
                timepoints=points,
                point_count=len(points),
                duration_baseline_ms=dur_baseline,
                duration_max_ms=dur_max_val,
                duration_max_ts=dur_max_ts,
                duration_deviation_x=dur_dev,
                rr_rate_baseline_pct=median(rr_rates) if rr_rates else 0.0,
                rr_rate_min_pct=rr_min_val,
                rr_rate_min_ts=rr_min_ts,
                succ_rate_baseline_pct=median(succ_rates) if succ_rates else 0.0,
                succ_rate_min_pct=succ_min_val,
                succ_rate_min_ts=succ_min_ts,
                trans_count_baseline=trans_baseline,
                trans_count_min=min(trans) if trans else 0,
                trans_count_max=max(trans) if trans else 0,
                trans_count_last=trans_last,
                spikes=spikes,
                symptom_type=symptom,
                severity_score=severity,
            )
        )

    return BpcFeatures(
        present=bool(systems),
        code=str(block.get("code", "")),
        type_text=str(block.get("type", "")).strip(),
        systems=systems,
        severity_score=overall,
        raw_block=block,
    )


# -- Probe ----------------------------------------------------------------


@dataclass
class ProbeFeatures:
    present: bool
    code: str
    type_text: str
    tcp_total: int
    tcp_abnormal: int
    tcp_response_params: list
    http_total: int
    http_abnormal: int
    http_response_params: list
    has_anomaly: bool
    raw_block: dict


def _extract_probe(block: dict) -> ProbeFeatures:
    msg = block.get("message") or {}
    tcp_a = _to_int(msg.get("tcpAbnormalNodes"))
    http_a = _to_int(msg.get("httpAbnormalNodes"))
    return ProbeFeatures(
        present=True,
        code=str(block.get("code", "")),
        type_text=str(block.get("type", "")).strip(),
        tcp_total=_to_int(msg.get("tcpNodes")),
        tcp_abnormal=tcp_a,
        tcp_response_params=list(msg.get("tcpResponseParams") or []),
        http_total=_to_int(msg.get("httpNodes")),
        http_abnormal=http_a,
        http_response_params=list(msg.get("httpResponseParams") or []),
        has_anomaly=(tcp_a + http_a) > 0,
        raw_block=block,
    )


# -- Components -----------------------------------------------------------


@dataclass
class InstanceState:
    ip: str
    port: str
    role: Optional[str]
    state: str
    text: str
    value: str


@dataclass
class ComponentGroup:
    com_name: str
    sys_name: str
    component_name: str
    cluster_state: str
    memory_state: str
    role_state: str
    instances: list[InstanceState]
    instance_count: int
    role_breakdown: dict[str, int]
    state_breakdown: dict[str, int]
    abnormal_instances: list[InstanceState]
    all_running: bool
    is_empty: bool


@dataclass
class ComponentFeatures:
    present: bool
    code: str
    type_text: str
    components: list[ComponentGroup]
    total_instances: int
    total_abnormal: int
    raw_block: dict


def _extract_components(block: dict) -> ComponentFeatures:
    msg = block.get("message") or {}
    raw_groups = msg.get("componentVOList") or []
    groups: list[ComponentGroup] = []
    total_inst = 0
    total_abn = 0

    for g in raw_groups:
        instances: list[InstanceState] = []
        roles: dict[str, int] = {}
        states: dict[str, int] = {}
        abnormal: list[InstanceState] = []
        for inst in g.get("instanceStateVOS") or []:
            ist = InstanceState(
                ip=str(inst.get("ip", "")),
                port=str(inst.get("port", "")),
                role=inst.get("role"),
                state=str(inst.get("state", "")),
                text=str(inst.get("text", "")),
                value=str(inst.get("value", "")),
            )
            instances.append(ist)
            role_key = ist.role if ist.role else "none"
            roles[role_key] = roles.get(role_key, 0) + 1
            states[ist.state] = states.get(ist.state, 0) + 1
            if ist.state != "RUNNING":
                abnormal.append(ist)

        groups.append(
            ComponentGroup(
                com_name=str(g.get("comName", "")),
                sys_name=str(g.get("sysName", "")),
                component_name=str(g.get("componentName", "")),
                cluster_state=str(g.get("clusterState", "")),
                memory_state=str(g.get("memoryState", "")),
                role_state=str(g.get("roleState", "")),
                instances=instances,
                instance_count=len(instances),
                role_breakdown=roles,
                state_breakdown=states,
                abnormal_instances=abnormal,
                all_running=bool(instances) and not abnormal,
                is_empty=len(instances) == 0,
            )
        )
        total_inst += len(instances)
        total_abn += len(abnormal)

    return ComponentFeatures(
        present=True,
        code=str(block.get("code", "")),
        type_text=str(block.get("type", "")).strip(),
        components=groups,
        total_instances=total_inst,
        total_abnormal=total_abn,
        raw_block=block,
    )


# -- Log keywords ---------------------------------------------------------


@dataclass
class LogKeywordHit:
    """单条 msg 里被命中的一个关键词及其计数/波及面。"""
    keyword: str
    count: int
    ip_count: int
    ips: list[str]      # 源数据给的样例 IP（常被其自带的 '...' 截断）


@dataclass
class LogKeywordEntry:
    sys_name: str
    com_name: str
    msg: str            # 原始聚合串，无损保留
    is_anomalous: bool
    hits: list[LogKeywordHit]  # 从 msg 解析出的结构化命中；解析不出则为空


@dataclass
class LogKeywordFeatures:
    present: bool
    code: str
    type_text: str
    entries: list[LogKeywordEntry]
    has_anomaly: bool
    raw_block: dict


# msg 形如：关键词："X" 一共出现了：N次,涉及IP M个: ip;ip;ip...;关键词："Y" ...
# 容错：分隔逗号全/半角皆可，IP 段可缺省（兼容只报关键词+次数的简短形态）。
_LOG_HIT_RE = re.compile(
    r'关键词："(?P<kw>[^"]+)"\s*一共出现了：\s*(?P<count>\d+)\s*次'
    r'(?:[,，]\s*涉及IP\s*(?P<ipc>\d+)\s*个[:：]\s*(?P<ips>.*?))?'
    r'(?=关键词："|$)',
    re.S,
)


def _parse_log_hits(msg: str) -> list[LogKeywordHit]:
    hits: list[LogKeywordHit] = []
    for m in _LOG_HIT_RE.finditer(msg):
        ips_raw = (m.group("ips") or "").replace("...", "")
        ips = [x.strip() for x in re.split(r"[;；]", ips_raw) if x.strip()]
        ipc = m.group("ipc")
        hits.append(LogKeywordHit(
            keyword=m.group("kw").strip(),
            count=int(m.group("count")),
            ip_count=int(ipc) if ipc else len(ips),
            ips=ips,
        ))
    return hits


def _extract_log_keywords(block: dict) -> LogKeywordFeatures:
    msg = block.get("message") or {}
    rows = msg.get("logManagementVOList") or []
    entries: list[LogKeywordEntry] = []
    any_anom = False
    for r in rows:
        m = str(r.get("msg", ""))
        is_anom = bool(m) and not any(p in m for p in NORMAL_LOG_PATTERNS)
        entries.append(
            LogKeywordEntry(
                sys_name=str(r.get("sysName", "")),
                com_name=str(r.get("comName", "")),
                msg=m,
                is_anomalous=is_anom,
                hits=_parse_log_hits(m) if is_anom else [],
            )
        )
        any_anom = any_anom or is_anom

    return LogKeywordFeatures(
        present=True,
        code=str(block.get("code", "")),
        type_text=str(block.get("type", "")).strip(),
        entries=entries,
        has_anomaly=any_anom,
        raw_block=block,
    )


# -- South center ---------------------------------------------------------


@dataclass
class SouthCenterFeatures:
    present: bool
    code: str
    type_text: str
    urgent: list
    virtual: list
    urgent_count: int
    virtual_count: int
    has_alert: bool
    raw_block: dict


def _extract_south_center(block: dict) -> SouthCenterFeatures:
    msg = block.get("message") or {}
    vos = msg.get("southCenterVOS") or []
    urgent: list = []
    virtual: list = []
    for item in vos:
        if isinstance(item, dict):
            urgent.extend(item.get("urgent") or [])
            virtual.extend(item.get("virtual") or [])
    return SouthCenterFeatures(
        present=True,
        code=str(block.get("code", "")),
        type_text=str(block.get("type", "")).strip(),
        urgent=urgent,
        virtual=virtual,
        urgent_count=len(urgent),
        virtual_count=len(virtual),
        has_alert=bool(urgent or virtual),
        raw_block=block,
    )


# -- Hosts / Databases ----------------------------------------------------


@dataclass
class HostAlarm:
    host: str
    alert_name: str
    desc: str
    endtime: str
    state: str
    is_active: bool


@dataclass
class HostMetrics:
    host: str
    cpu_pct: float
    memory_pct: float
    iowait_pct: float  # CPU time spent waiting on I/O, already in percent (0-100)
    iowait_raw: float  # original raw value from upstream (same scale as iowait_pct)
    disk_pct: float
    running_days: int
    subnet24: str
    subnet16: str


@dataclass
class HostCohort:
    name: str
    hosts: list[str]
    host_count: int
    avg_cpu_pct: float
    avg_memory_pct: float
    avg_iowait_pct: float
    avg_disk_pct: float
    note: str


@dataclass
class HostFeatures:
    present: bool
    code: str
    type_text: str
    alarms: list[HostAlarm]
    active_alarm_count: int
    hosts: list[HostMetrics]
    host_count: int
    cpu_stats: dict
    memory_stats: dict
    iowait_stats: dict
    disk_stats: dict
    subnets: dict[str, list[str]]
    breaches: dict[str, list[str]]
    cohorts: list[HostCohort]
    breach_clusters: list[dict]
    top_iowait: list[HostMetrics]
    top_memory: list[HostMetrics]
    top_cpu: list[HostMetrics]
    top_disk: list[HostMetrics]
    longest_uptime: list[HostMetrics]
    raw_block: dict


def _build_alarms(rows: list[dict]) -> list[HostAlarm]:
    out: list[HostAlarm] = []
    for a in rows:
        endtime = str(a.get("endtime", ""))
        state = str(a.get("state", ""))
        out.append(
            HostAlarm(
                host=str(a.get("host", "")),
                alert_name=str(a.get("alertName", "")),
                desc=str(a.get("desc", "")),
                endtime=endtime,
                state=state,
                is_active=(not endtime) or state in ("未恢复", "active"),
            )
        )
    return out


def _extract_hosts(block: dict) -> HostFeatures:
    msg = block.get("message") or {}
    alarms = _build_alarms(msg.get("hostAlarmVO") or [])
    info_raw = msg.get("hostinfo") or []

    hosts: list[HostMetrics] = []
    for h in info_raw:
        ip = str(h.get("host", ""))
        iowait_raw = _to_float(h.get("iowait"))
        hosts.append(
            HostMetrics(
                host=ip,
                cpu_pct=_to_float(h.get("cpuUsed")),
                memory_pct=_to_float(h.get("memory")),
                iowait_pct=iowait_raw,
                iowait_raw=iowait_raw,
                disk_pct=_to_float(h.get("disk")),
                running_days=_to_int(h.get("running_days")),
                subnet24=_subnet(ip, 3),
                subnet16=_subnet(ip, 2),
            )
        )

    def metric_stats(getter: Callable[[HostMetrics], float]) -> dict:
        vals = [getter(h) for h in hosts]
        if not vals:
            return {}
        s = _stats(vals) or {}
        s["max_host"] = max(hosts, key=getter).host
        return s

    cpu_stats = metric_stats(lambda h: h.cpu_pct)
    mem_stats = metric_stats(lambda h: h.memory_pct)
    iow_stats = metric_stats(lambda h: h.iowait_pct)
    disk_stats = metric_stats(lambda h: h.disk_pct)

    subnets: dict[str, list[str]] = {}
    for h in hosts:
        subnets.setdefault(h.subnet24, []).append(h.host)

    breaches = {
        "cpu_high": [
            h.host for h in hosts if h.cpu_pct > HOST_THRESHOLDS["cpu_high_pct"]
        ],
        "memory_high": [
            h.host
            for h in hosts
            if h.memory_pct > HOST_THRESHOLDS["memory_high_pct"]
        ],
        "iowait_high": [
            h.host
            for h in hosts
            if h.iowait_pct > HOST_THRESHOLDS["iowait_high_pct"]
        ],
        "disk_high": [
            h.host for h in hosts if h.disk_pct > HOST_THRESHOLDS["disk_high_pct"]
        ],
    }

    cohorts: list[HostCohort] = []
    for sn, host_ips in subnets.items():
        sn_hosts = [h for h in hosts if h.subnet24 == sn]
        if len(sn_hosts) < 3:
            continue
        avg_cpu = sum(h.cpu_pct for h in sn_hosts) / len(sn_hosts)
        avg_mem = sum(h.memory_pct for h in sn_hosts) / len(sn_hosts)
        avg_iow = sum(h.iowait_pct for h in sn_hosts) / len(sn_hosts)
        avg_disk = sum(h.disk_pct for h in sn_hosts) / len(sn_hosts)
        notes = []
        if avg_iow > HOST_THRESHOLDS["iowait_high_pct"]:
            notes.append(f"高 IOwait 平均 {avg_iow:.1f}%")
        if avg_mem > HOST_THRESHOLDS["memory_high_pct"]:
            notes.append(f"高内存 平均 {avg_mem:.1f}%")
        if avg_cpu > 60:
            notes.append(f"高 CPU 平均 {avg_cpu:.1f}%")
        if avg_disk > 70:
            notes.append(f"高磁盘 平均 {avg_disk:.1f}%")
        if notes:
            cohorts.append(
                HostCohort(
                    name=sn + ".x",
                    hosts=[h.host for h in sn_hosts],
                    host_count=len(sn_hosts),
                    avg_cpu_pct=avg_cpu,
                    avg_memory_pct=avg_mem,
                    avg_iowait_pct=avg_iow,
                    avg_disk_pct=avg_disk,
                    note="; ".join(notes),
                )
            )
    cohorts.sort(
        key=lambda c: c.avg_iowait_pct + c.avg_memory_pct, reverse=True
    )

    # breach clusters: aggregate breach-hosts by /24 to surface which subnets
    # concentrate the badness. unlike `cohorts` (which averages over all hosts
    # in a subnet and gets diluted), this view counts only the offending hosts.
    breach_clusters: list[dict] = []
    for breach_name, ips in breaches.items():
        if not ips:
            continue
        by_subnet: dict[str, list[HostMetrics]] = {}
        for ip in ips:
            sub = _subnet(ip, 3)
            by_subnet.setdefault(sub, []).append(
                next(h for h in hosts if h.host == ip)
            )
        for sub, sub_hosts in by_subnet.items():
            total_in_sub = len(subnets.get(sub, []))
            metric_key = breach_name.replace("_high", "")
            getter = {
                "cpu": lambda h: h.cpu_pct,
                "memory": lambda h: h.memory_pct,
                "iowait": lambda h: h.iowait_pct,
                "disk": lambda h: h.disk_pct,
            }[metric_key]
            vals = [getter(h) for h in sub_hosts]
            breach_clusters.append(
                {
                    "breach": breach_name,
                    "subnet": sub + ".x",
                    "host_count": len(sub_hosts),
                    "total_in_subnet": total_in_sub,
                    "ratio": len(sub_hosts) / total_in_sub if total_in_sub else 0.0,
                    "avg_value_pct": sum(vals) / len(vals),
                    "max_value_pct": max(vals),
                    "host_octets": sorted(
                        int(h.host.split(".")[-1]) for h in sub_hosts
                    ),
                }
            )
    breach_clusters.sort(
        key=lambda b: (b["host_count"], b["avg_value_pct"]), reverse=True
    )

    return HostFeatures(
        present=True,
        code=str(block.get("code", "")),
        type_text=str(block.get("type", "")).strip(),
        alarms=alarms,
        active_alarm_count=sum(1 for a in alarms if a.is_active),
        hosts=hosts,
        host_count=len(hosts),
        cpu_stats=cpu_stats,
        memory_stats=mem_stats,
        iowait_stats=iow_stats,
        disk_stats=disk_stats,
        subnets=subnets,
        breaches=breaches,
        cohorts=cohorts,
        breach_clusters=breach_clusters,
        top_iowait=sorted(hosts, key=lambda h: h.iowait_pct, reverse=True)[:10],
        top_memory=sorted(hosts, key=lambda h: h.memory_pct, reverse=True)[:10],
        top_cpu=sorted(hosts, key=lambda h: h.cpu_pct, reverse=True)[:10],
        top_disk=sorted(hosts, key=lambda h: h.disk_pct, reverse=True)[:10],
        longest_uptime=sorted(
            hosts, key=lambda h: h.running_days, reverse=True
        )[:5],
        raw_block=block,
    )


@dataclass
class DbInstance:
    host: str
    db_type: str          # 'ora' | 'gaussdb' | ...
    db_status: int        # 1=running, 0=down/standby
    cpu_pct: float
    memory_pct: float
    iowait_pct: float     # already in percent (与主机 iowait 同口径)
    disk_pct: float
    active_conn: int
    ybp: str              # 原样保留：ora 一般为 '0'，gaussdb 一般为 ''
    running_days: int


@dataclass
class DatabaseFeatures:
    present: bool
    code: str
    type_text: str
    alarms: list[HostAlarm]
    active_alarm_count: int
    instances: list[DbInstance]
    instance_count: int
    normal_count: int        # db_status == 1 的实例数（探测正常）
    abnormal_count: int      # db_status != 1 的实例数（探测异常）
    raw_block: dict


def _extract_db_instance(d: dict) -> DbInstance:
    return DbInstance(
        host=str(d.get("host", "")),
        db_type=str(d.get("dbType", "")),
        db_status=_to_int(d.get("dbStatus")),
        cpu_pct=_to_float(d.get("cpuUsed")),
        memory_pct=_to_float(d.get("memory")),
        iowait_pct=_to_float(d.get("iowait")),
        disk_pct=_to_float(d.get("disk")),
        active_conn=_to_int(d.get("activeConn")),
        ybp=str(d.get("ybp", "")),
        running_days=_to_int(d.get("running_days")),
    )


def _extract_databases(block: dict) -> DatabaseFeatures:
    msg = block.get("message") or {}
    alarms = _build_alarms(msg.get("hostAlarmVO") or [])
    instances = [_extract_db_instance(d) for d in (msg.get("dbinfo") or [])]
    running = sum(1 for i in instances if i.db_status == 1)
    return DatabaseFeatures(
        present=True,
        code=str(block.get("code", "")),
        type_text=str(block.get("type", "")).strip(),
        alarms=alarms,
        active_alarm_count=sum(1 for a in alarms if a.is_active),
        instances=instances,
        instance_count=len(instances),
        normal_count=running,
        abnormal_count=len(instances) - running,
        raw_block=block,
    )


# -- Release rules (核保规则发布情况) -------------------------------------
#
# 该信号若出现且非空，几乎必然是当前事件的疑似根因——发布动作往往直接触发
# BPC/响应率/耗时异常。下游渲染层据此在速览图最顶部强提示。
#
# 但发布若发生在很久以前（默认 12h），引发当前事件的概率很低；此时将其
# 视为"陈旧线索"，不再 banner 置顶，也降低在 top_anomalies 的排名，仅在
# 现象简报里随 rules 字段一并提及即可。

RULE_RECENT_THRESHOLD_MIN = 12 * 60  # 超过 12h 视为陈旧，几乎不是当前事件根因

# 规则字符串末尾形如 "已发布:6分钟" / "已发布:1小时30分钟" / "已发布:3天"
_RULE_AGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(秒|分钟|分|小时|时|天)")
_RULE_AGE_UNIT_MIN = {
    "秒": 1.0 / 60.0,
    "分钟": 1.0,
    "分": 1.0,
    "小时": 60.0,
    "时": 60.0,
    "天": 1440.0,
}


def _rule_age_minutes(rule: str) -> Optional[float]:
    """解析 "已发布:X单位[Y单位...]" 形式的时长，返回分钟数。

    无法解析返回 None；调用方应把 None 视作"未知 → 保守按近期处理"，
    避免误把一条不规则字符串的发布规则当成陈旧线索过滤掉。
    """
    matches = _RULE_AGE_RE.findall(rule)
    if not matches:
        return None
    return sum(float(n) * _RULE_AGE_UNIT_MIN[u] for n, u in matches)


@dataclass
class ReleaseRuleFeatures:
    present: bool
    code: str
    type_text: str
    rules: list[str]  # 原样显示串，例: '"UnderwritePowerRule_51App"已发布:6分钟'
    raw_block: dict
    # 与 rules 平行的发布时长（分钟），未能解析时为 None
    rule_ages_min: list[Optional[float]] = field(default_factory=list)
    # 至少有一条规则发布于阈值窗内（或时长无法解析时保守为 True），
    # banner 仅在此为 True 时置顶
    is_recent: bool = True


def _extract_release_rules(block: dict) -> ReleaseRuleFeatures:
    msg = block.get("message") or {}
    raw = msg.get("riskRule")
    rules: list[str] = []
    if isinstance(raw, str):
        s = raw.strip()
        if s:
            rules.append(s)
    elif isinstance(raw, list):
        rules = [str(r).strip() for r in raw if str(r).strip()]
    elif isinstance(raw, dict):
        for k, v in raw.items():
            rules.append(f"{k}: {v}")
    ages = [_rule_age_minutes(r) for r in rules]
    # 无法解析的时长按"近期"处理（不抹掉信号）；只有所有规则都明确老于阈值时
    # 才整体降级为陈旧。
    is_recent = bool(rules) and any(
        a is None or a <= RULE_RECENT_THRESHOLD_MIN for a in ages
    )
    return ReleaseRuleFeatures(
        present=bool(rules),
        code=str(block.get("code", "")),
        type_text=str(block.get("type", "")).strip(),
        rules=rules,
        raw_block=block,
        rule_ages_min=ages,
        is_recent=is_recent,
    )


# -- Generic monitor categories -------------------------------------------


@dataclass
class MissingSignal:
    monitor: str
    code: str
    type_text: str
    reason: str  # "interface_failed" | "no_data"


@dataclass
class TextNote:
    monitor: str
    code: str
    type_text: str


# -- Cross-signal synthesis -----------------------------------------------


@dataclass
class CrossSignal:
    snapshot_time: Optional[str]
    monitors_present: list[str]
    monitors_anomalous: list[str]
    monitors_normal: list[str]
    monitors_failed: list[str]
    monitors_empty: list[str]
    timeline_anchors: list[dict]
    spatial_cohorts: list[dict]
    top_anomalies: list[dict]
    missing_signals: list[str]


@dataclass
class FeatureBag:
    raw_meta: dict
    bpc: Optional[BpcFeatures] = None
    probe: Optional[ProbeFeatures] = None
    components: Optional[ComponentFeatures] = None
    log_keywords: Optional[LogKeywordFeatures] = None
    call_chain: Optional[MissingSignal] = None
    change_orders: Optional[MissingSignal] = None
    upgrade_orders: Optional[MissingSignal] = None
    single_client_analysis: Optional[TextNote] = None
    south_center: Optional[SouthCenterFeatures] = None
    hosts: Optional[HostFeatures] = None
    databases: Optional[DatabaseFeatures] = None
    release_rules: Optional[ReleaseRuleFeatures] = None
    unknown_monitors: list[dict] = field(default_factory=list)
    cross: Optional[CrossSignal] = None

    def to_dict(self, include_raw: bool = True) -> dict:
        return _asdict(self, include_raw=include_raw)

    def to_llm_brief(self) -> dict:
        return _build_llm_brief(self)


# -- LLM brief ------------------------------------------------------------


def _hm(ts: Optional[str]) -> Optional[str]:
    if not ts or len(ts) < 5:
        return ts
    return ts[-8:-3] if len(ts) >= 8 else ts


def _bpc_brief(bpc: BpcFeatures) -> dict:
    systems = []
    for s in bpc.systems:
        systems.append({
            "system": s.system_name,
            "symptom": s.symptom_type,
            "severity": round(s.severity_score, 1),
            "duration_baseline_ms": round(s.duration_baseline_ms, 0),
            "duration_max_ms": round(s.duration_max_ms, 0),
            "duration_max_at": _hm(s.duration_max_ts),
            "duration_dev_x": round(s.duration_deviation_x, 1),
            "succ_rate_baseline_pct": round(s.succ_rate_baseline_pct, 2),
            "succ_rate_min_pct": round(s.succ_rate_min_pct, 2),
            "succ_rate_min_at": _hm(s.succ_rate_min_ts),
            "rr_rate_baseline_pct": round(s.rr_rate_baseline_pct, 2),
            "rr_rate_min_pct": round(s.rr_rate_min_pct, 2),
            "rr_rate_min_at": _hm(s.rr_rate_min_ts),
            "trans_count_baseline": round(s.trans_count_baseline, 0),
            "trans_count_last": s.trans_count_last,
            "spike_count": len(s.spikes),
        })
    return {"systems": systems, "severity": round(bpc.severity_score, 1)}


def _host_brief(hf: HostFeatures) -> dict:
    # 把每台主机的实测指标拼到 active_alarms 上：告警名里出现 "IO" 不等于
    # 这台主机 iowait 高，旧版只给 alert 名，LLM 容易把告警主机误标为
    # 该指标最高的主机。
    by_ip = {h.host: h for h in hf.hosts}

    def _alarm_entry(a) -> dict:
        d = {
            "host": a.host,
            "alert": a.alert_name,
            "desc": a.desc,
            "state": a.state,
        }
        h = by_ip.get(a.host)
        if h is not None:
            d["measured_pct"] = {
                "cpu": round(h.cpu_pct, 1),
                "memory": round(h.memory_pct, 1),
                "iowait": round(h.iowait_pct, 1),
                "disk": round(h.disk_pct, 1),
            }
        return d

    return {
        "host_count": hf.host_count,
        # 把阈值显式带上，避免 LLM 凭直觉判断"高"
        "thresholds_pct": dict(HOST_THRESHOLDS),
        "active_alarms": [_alarm_entry(a) for a in hf.alarms if a.is_active],
        "iowait_pct": {
            "p50": round(hf.iowait_stats.get("p50", 0), 1),
            "p90": round(hf.iowait_stats.get("p90", 0), 1),
            "max": round(hf.iowait_stats.get("max", 0), 1),
            "max_host": hf.iowait_stats.get("max_host"),
        },
        # 个体 Top — 让 LLM 描述"某主机 iowait 高"时只能从这里挑，
        # 不再从 alarm 名字凭空推断
        "top_iowait_hosts": [
            {"host": h.host, "iowait_pct": round(h.iowait_pct, 1)}
            for h in hf.top_iowait[:5]
        ],
        "memory_pct": {
            "p50": round(hf.memory_stats.get("p50", 0), 1),
            "p90": round(hf.memory_stats.get("p90", 0), 1),
            "max": round(hf.memory_stats.get("max", 0), 1),
            "max_host": hf.memory_stats.get("max_host"),
        },
        "top_memory_hosts": [
            {"host": h.host, "memory_pct": round(h.memory_pct, 1)}
            for h in hf.top_memory[:5]
        ],
        "breach_clusters": [
            {
                "breach": bc["breach"],
                "subnet": bc["subnet"],
                "host_count": bc["host_count"],
                "total_in_subnet": bc["total_in_subnet"],
                "avg_value_pct": round(bc["avg_value_pct"], 1),
                "max_value_pct": round(bc["max_value_pct"], 1),
                "host_octets_range": (
                    f"{min(bc['host_octets'])}-{max(bc['host_octets'])}"
                    if bc.get("host_octets") else ""
                ),
            }
            for bc in hf.breach_clusters
        ],
    }


def _component_brief(cf: ComponentFeatures) -> list[dict]:
    out = []
    for g in cf.components:
        if g.is_empty:
            status = "empty (no instances returned)"
        elif g.all_running:
            status = f"all RUNNING ({g.instance_count} instances)"
        else:
            status = (
                f"{g.instance_count - len(g.abnormal_instances)}/"
                f"{g.instance_count} RUNNING, "
                f"{len(g.abnormal_instances)} abnormal"
            )
        item = {
            "name": g.component_name or g.com_name,
            "system": g.sys_name,
            "cluster_state": g.cluster_state,
            "status": status,
        }
        if g.role_breakdown:
            item["roles"] = g.role_breakdown
        out.append(item)
    return out


def _build_llm_brief(bag: FeatureBag) -> dict:
    cross = bag.cross
    brief: dict = {
        "snapshot_time": cross.snapshot_time if cross else None,
        "monitors": {
            "anomalous": cross.monitors_anomalous if cross else [],
            "normal": cross.monitors_normal if cross else [],
            "interface_failed": cross.monitors_failed if cross else [],
            "empty": cross.monitors_empty if cross else [],
        },
        "top_anomalies": (cross.top_anomalies[:8] if cross else []),
    }

    if bag.bpc and bag.bpc.present:
        brief["bpc"] = _bpc_brief(bag.bpc)

    if bag.hosts and bag.hosts.present:
        brief["hosts"] = _host_brief(bag.hosts)

    if bag.components and bag.components.present:
        brief["components"] = _component_brief(bag.components)

    if bag.probe and bag.probe.present:
        brief["probe"] = {
            "tcp": f"{bag.probe.tcp_total - bag.probe.tcp_abnormal}/{bag.probe.tcp_total} OK",
            "http": f"{bag.probe.http_total - bag.probe.http_abnormal}/{bag.probe.http_total} OK",
            "has_anomaly": bag.probe.has_anomaly,
        }

    if bag.log_keywords and bag.log_keywords.present:
        brief["log_keywords"] = {
            "has_anomaly": bag.log_keywords.has_anomaly,
            "entries": [
                {
                    "sys": e.sys_name,
                    "keywords": [
                        {"kw": h.keyword, "count": h.count, "ip_count": h.ip_count}
                        for h in e.hits
                    ] or e.msg,
                }
                for e in bag.log_keywords.entries
            ],
        }

    if bag.databases and bag.databases.present:
        db_brief = {
            "instance_count": bag.databases.instance_count,
            "normal_count": bag.databases.normal_count,
            "abnormal_count": bag.databases.abnormal_count,
            "active_alarm_count": bag.databases.active_alarm_count,
        }
        if bag.databases.active_alarm_count > 0:
            db_brief["active_alarms"] = [
                {
                    "host": a.host,
                    "alert_name": a.alert_name,
                    "desc": a.desc,
                }
                for a in bag.databases.alarms
                if a.is_active
            ]
            db_brief["instances"] = [
                {
                    "host": i.host,
                    "type": i.db_type,
                    "status": "normal" if i.db_status == 1 else "probe_failed",
                    "cpu_pct": i.cpu_pct,
                    "memory_pct": i.memory_pct,
                    "iowait_pct": i.iowait_pct,
                    "disk_pct": i.disk_pct,
                    "active_conn": i.active_conn,
                }
                for i in bag.databases.instances
            ]
        brief["databases"] = db_brief

    if bag.south_center and bag.south_center.present:
        brief["south_center"] = {
            "urgent_count": bag.south_center.urgent_count,
            "virtual_count": bag.south_center.virtual_count,
        }

    if bag.single_client_analysis:
        brief["single_client_note"] = bag.single_client_analysis.type_text

    if bag.release_rules and bag.release_rules.present:
        brief["release_rules"] = {
            "type_text": bag.release_rules.type_text,
            "rules": list(bag.release_rules.rules),
        }

    failed = []
    for name, sig in (
        ("call_chain", bag.call_chain),
        ("change_orders", bag.change_orders),
        ("upgrade_orders", bag.upgrade_orders),
    ):
        if sig:
            failed.append({
                "monitor": sig.monitor,
                "key": name,
                "reason": sig.reason,
                "type_text": sig.type_text,
            })
    if failed:
        brief["missing_signals"] = failed

    if bag.unknown_monitors:
        brief["unknown_monitors"] = [
            m.get("monitor") for m in bag.unknown_monitors
        ]

    return brief


# -- Dispatch table -------------------------------------------------------

_STRUCTURED_DISPATCH: dict[str, tuple[str, Callable[[dict], Any]]] = {
    "BPC监控": ("bpc", _extract_bpc),
    "PROMETHEUS应用拨测结果": ("probe", _extract_probe),
    "组件状态指标": ("components", _extract_components),
    "日志关键字指标": ("log_keywords", _extract_log_keywords),
    "南中心告警": ("south_center", _extract_south_center),
    "设备-主机": ("hosts", _extract_hosts),
    "设备-数据库": ("databases", _extract_databases),
    "核保规则发布情况": ("release_rules", _extract_release_rules),
}

_MISSING_DISPATCH = {
    "调用链指标": "call_chain",
    "变更单信息": "change_orders",
    "升级单信息": "upgrade_orders",
}

_TEXT_NOTE_DISPATCH = {
    "单客户端异常访问分析": "single_client_analysis",
}


# -- Public extract -------------------------------------------------------


def extract(payload: dict) -> FeatureBag:
    raw_meta = {
        "status": payload.get("status"),
        "statusText": payload.get("statusText"),
        "message": payload.get("message"),
        "timestamp": payload.get("timestamp"),
        "timestamp_iso": _format_ts_ms(payload.get("timestamp")),
    }
    bag = FeatureBag(raw_meta=raw_meta)
    blocks = payload.get("data") or []

    for block in blocks:
        name = block.get("monitor")
        code = str(block.get("code", "")).strip()
        if name in _STRUCTURED_DISPATCH:
            attr, fn = _STRUCTURED_DISPATCH[name]
            setattr(bag, attr, fn(block))
        elif name in _MISSING_DISPATCH:
            reason = "interface_failed" if code == "-1" else "no_data"
            setattr(
                bag,
                _MISSING_DISPATCH[name],
                MissingSignal(
                    monitor=str(name),
                    code=code,
                    type_text=str(block.get("type", "")).strip(),
                    reason=reason,
                ),
            )
        elif name in _TEXT_NOTE_DISPATCH:
            setattr(
                bag,
                _TEXT_NOTE_DISPATCH[name],
                TextNote(
                    monitor=str(name),
                    code=code,
                    type_text=str(block.get("type", "")).strip(),
                ),
            )
        else:
            bag.unknown_monitors.append(block)

    bag.cross = _build_cross(bag)
    return bag


def _build_cross(bag: FeatureBag) -> CrossSignal:
    snapshot_time: Optional[str] = None
    if bag.bpc and bag.bpc.systems:
        latest = max(
            p.timestamp for sys in bag.bpc.systems for p in sys.timepoints
        )
        snapshot_time = latest
    if not snapshot_time:
        snapshot_time = bag.raw_meta.get("timestamp_iso")

    present: list[str] = []
    anomalous: list[str] = []
    normal: list[str] = []
    failed: list[str] = []
    empty: list[str] = []
    timeline: list[dict] = []
    cohorts_out: list[dict] = []
    anomalies: list[dict] = []
    missing: list[str] = []

    def classify(name: str, has_anom: bool) -> None:
        present.append(name)
        (anomalous if has_anom else normal).append(name)

    if bag.bpc and bag.bpc.present:
        has_anom = any(s.symptom_type != "normal" for s in bag.bpc.systems)
        classify("BPC监控", has_anom)
        for s in bag.bpc.systems:
            for sp in s.spikes:
                timeline.append(
                    {
                        "monitor": "BPC监控",
                        "system": s.system_name,
                        "timestamp": sp.timestamp,
                        "metric": sp.metric,
                        "value": sp.value,
                        "deviation_x": sp.deviation_x,
                    }
                )
                anomalies.append(
                    {
                        "source": "BPC监控",
                        "system": s.system_name,
                        "metric": sp.metric,
                        "value": sp.value,
                        "baseline": sp.baseline,
                        "deviation_x": sp.deviation_x,
                        "timestamp": sp.timestamp,
                        "severity": s.severity_score,
                    }
                )

    if bag.probe and bag.probe.present:
        classify("PROMETHEUS应用拨测结果", bag.probe.has_anomaly)

    if bag.components and bag.components.present:
        # an "anomaly" here is non-RUNNING instances; empty components do not count
        classify("组件状态指标", bag.components.total_abnormal > 0)

    if bag.log_keywords and bag.log_keywords.present:
        classify("日志关键字指标", bag.log_keywords.has_anomaly)

    if bag.south_center and bag.south_center.present:
        classify("南中心告警", bag.south_center.has_alert)

    if bag.hosts and bag.hosts.present:
        any_breach = any(v for v in bag.hosts.breaches.values())
        has_anom = bag.hosts.active_alarm_count > 0 or any_breach
        classify("设备-主机", has_anom)
        for a in bag.hosts.alarms:
            if a.is_active:
                timeline.append(
                    {
                        "monitor": "设备-主机",
                        "host": a.host,
                        "alert_name": a.alert_name,
                        "state": a.state,
                    }
                )
                anomalies.append(
                    {
                        "source": "设备-主机",
                        "host": a.host,
                        "alert_name": a.alert_name,
                        "desc": a.desc,
                        "severity": 70.0,
                    }
                )
        for bc in bag.hosts.breach_clusters:
            anomalies.append(
                {
                    "source": f"设备-主机/breach[{bc['breach']}]",
                    "subnet": bc["subnet"],
                    "host_count": bc["host_count"],
                    "total_in_subnet": bc["total_in_subnet"],
                    "ratio": bc["ratio"],
                    "avg_value_pct": bc["avg_value_pct"],
                    "max_value_pct": bc["max_value_pct"],
                    "severity": min(
                        85.0,
                        bc["host_count"] * 2.0 + bc["avg_value_pct"] * 0.5,
                    ),
                }
            )
        for c in bag.hosts.cohorts:
            cohort_dict = {
                "subnet": c.name,
                "host_count": c.host_count,
                "avg_iowait_pct": c.avg_iowait_pct,
                "avg_memory_pct": c.avg_memory_pct,
                "avg_cpu_pct": c.avg_cpu_pct,
                "avg_disk_pct": c.avg_disk_pct,
                "note": c.note,
            }
            cohorts_out.append(cohort_dict)
            anomalies.append(
                {
                    "source": "设备-主机/cohort",
                    **cohort_dict,
                    "severity": min(
                        80.0,
                        c.avg_iowait_pct + max(0.0, c.avg_memory_pct - 80.0) * 0.5,
                    ),
                }
            )

    if bag.databases and bag.databases.present:
        classify("设备-数据库", bag.databases.active_alarm_count > 0)

    if bag.release_rules and bag.release_rules.present:
        classify("核保规则发布情况", True)
        rrf = bag.release_rules
        ages = rrf.rule_ages_min or [None] * len(rrf.rules)
        for r, age in zip(rrf.rules, ages):
            # 陈旧发布（>12h）不太可能是当前事件根因，把它从 95 降到 30，
            # 让 host/db 等真正的现场告警自然冒出来；不可解析的 age 保守按近期。
            stale = age is not None and age > RULE_RECENT_THRESHOLD_MIN
            anomalies.append(
                {
                    "source": "核保规则发布情况",
                    "rule": r,
                    "age_min": age,
                    "stale": stale,
                    "severity": 30.0 if stale else 95.0,
                }
            )

    for ms_attr in ("call_chain", "change_orders", "upgrade_orders"):
        ms: Optional[MissingSignal] = getattr(bag, ms_attr)
        if ms is not None:
            failed.append(ms.monitor)
            missing.append(ms.monitor)

    anomalies.sort(key=lambda a: a.get("severity", 0.0), reverse=True)

    return CrossSignal(
        snapshot_time=snapshot_time,
        monitors_present=present,
        monitors_anomalous=anomalous,
        monitors_normal=normal,
        monitors_failed=failed,
        monitors_empty=empty,
        timeline_anchors=timeline,
        spatial_cohorts=cohorts_out,
        top_anomalies=anomalies[:10],
        missing_signals=missing,
    )


# -- Serialization --------------------------------------------------------


def _asdict(obj: Any, include_raw: bool = True) -> Any:
    if is_dataclass(obj):
        result = {}
        for f in fields(obj):
            if not include_raw and f.name == "raw_block":
                continue
            result[f.name] = _asdict(getattr(obj, f.name), include_raw)
        return result
    if isinstance(obj, list):
        return [_asdict(x, include_raw) for x in obj]
    if isinstance(obj, dict):
        return {k: _asdict(v, include_raw) for k, v in obj.items()}
    return obj
