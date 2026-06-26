"""Probe 注册表:pattern「验证」步骤可引用的探测的唯一合法清单。

pattern YAML 的 ``验证[].probe`` 字段只能引用这里注册的名字,加载时强制校验。
这是自检环节"PATTERN.验证方法 覆盖度对比"可由代码执行的前提:代码拿
pattern 声明的 probe 名与调查中实际执行的 probe 名做字典对比,不解析自由文本。

V1 没有按需二次查询接口——监控聚合器一次性返回快照,"探测"即"从已采集的
现场(FeatureBag)或关联上下文 sidecar(RelatedContext)里取出特定视角的数据"。
后续若聚合器开放按需查询(如 DB 长事务列表),在此追加注册即可,schema 不变。

probe 命名即 LLM tool calling 时的 tool 名,新增条目前先确认 FeatureBag
中确有对应数据(对照 features._STRUCTURED_DISPATCH)。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Probe:
    name: str
    source: str  # FeatureBag 属性路径,或 "sidecar"(RelatedContext)
    monitor: str  # 上游监控/数据源名称
    returns: str  # 返回内容描述,直接用作 LLM tool 描述


_ALL_PROBES: tuple[Probe, ...] = (
    Probe(
        name="bpc_system_metrics",
        source="bpc.systems",
        monitor="BPC监控",
        returns="指定系统的耗时/响应率/成功率/交易量时间线,含基线、最值时刻与尖刺列表",
    ),
    Probe(
        name="host_alarms",
        source="hosts.alarms",
        monitor="设备-主机",
        returns="未恢复的主机告警列表(主机 IP、告警名、描述、该主机实测指标)",
    ),
    Probe(
        name="host_metric_breaches",
        source="hosts.breaches",
        monitor="设备-主机",
        returns="CPU/内存/IOwait/磁盘越限主机清单,含阈值口径与网段聚集情况",
    ),
    Probe(
        name="db_instance_status",
        source="databases.instances",
        monitor="设备-数据库",
        returns="数据库实例探测状态(正常/失败)、active_conn 与 CPU/内存/IOwait/磁盘指标",
    ),
    Probe(
        name="db_alarms",
        source="databases.alarms",
        monitor="设备-数据库",
        returns="未恢复的数据库告警列表",
    ),
    Probe(
        name="component_status",
        source="components",
        monitor="组件状态指标",
        returns="各组件实例运行状态,非 RUNNING 实例清单与角色分布",
    ),
    Probe(
        name="log_keyword_hits",
        source="log_keywords.entries",
        monitor="日志关键字指标",
        returns="命中异常关键字的日志条目(按系统/组件,含原始消息)",
    ),
    Probe(
        name="app_probe_status",
        source="probe",
        monitor="PROMETHEUS应用拨测结果",
        returns="TCP/HTTP 拨测节点总数与异常数量、异常节点响应明细",
    ),
    Probe(
        name="south_center_alerts",
        source="south_center",
        monitor="南中心告警",
        returns="南中心 urgent/virtual 告警清单",
    ),
    Probe(
        name="release_rules_recent",
        source="release_rules",
        monitor="核保规则发布情况",
        returns="规则发布记录与已发布时长(12 小时内视为近期,可能为当前事件诱因)",
    ),
    Probe(
        name="related_changes",
        source="sidecar",
        monitor="变更/升级单(CHM/DRM)",
        returns="24 小时内与受影响系统关联的变更单与版本升级单(标题、时间窗)",
    ),
    Probe(
        name="related_incidents",
        source="sidecar",
        monitor="事件单(INM)",
        returns="2 小时内的关联事件单(等级、描述)",
    ),
)

PROBES: dict[str, Probe] = {p.name: p for p in _ALL_PROBES}
