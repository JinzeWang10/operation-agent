import json
from big_data_model.models import IncidentRequest, BaselineScanResult, InvestigationResult


# ── Data Formatters ──────────────────────────────────────────────────

def format_adapter_data(adapter_name: str, data: dict) -> str:
    """Convert raw adapter data to readable text for LLM context."""
    formatters = {
        "bpc": _format_bpc,
        "prometheus": _format_prometheus,
        "database": _format_database,
        "host": _format_host,
        "component": _format_component,
        "log": _format_log,
        "south_center": _format_south_center,
    }
    formatter = formatters.get(adapter_name)
    if formatter:
        return formatter(data)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _format_bpc(data: dict) -> str:
    lines = []
    for sys_name, time_data in data.get("bpcAlarmtypeMap", {}).items():
        lines.append(f"系统: {sys_name}")
        for ts, m in time_data.items():
            if m.get("duration"):
                lines.append(
                    f"  {ts} | 耗时:{m['duration']}ms "
                    f"响应率:{m['rr_rate']}% 成功率:{m['succ_rate']}% "
                    f"交易量:{m['trans_count']}"
                )
            else:
                lines.append(f"  {ts} | 无数据 (交易量:0)")
    return "\n".join(lines) if lines else "无数据"


def _format_prometheus(data: dict) -> str:
    lines = [
        f"TCP 探测节点: {data.get('tcpNodes', 'N/A')} (异常: {data.get('tcpAbnormalNodes', 'N/A')})",
        f"HTTP 探测节点: {data.get('httpNodes', 'N/A')} (异常: {data.get('httpAbnormalNodes', 'N/A')})",
    ]
    for p in data.get("tcpResponseParams", []):
        lines.append(f"  TCP 响应: {p}")
    for p in data.get("httpResponseParams", []):
        lines.append(f"  HTTP 响应: {p}")
    return "\n".join(lines)


def _format_database(data: dict) -> str:
    lines = []
    alerts = data.get("hostAlarmVO", [])
    if alerts:
        lines.append(f"活跃告警 ({len(alerts)}):")
        for a in alerts:
            lines.append(f"  [{a.get('state', '')}] {a.get('host', '')} - {a.get('alertName', '')}: {a.get('desc', '')}")
    else:
        lines.append("无活跃告警")
    dbinfo = data.get("dbinfo", [])
    if dbinfo:
        lines.append(f"\n实例状态 ({len(dbinfo)}):")
        for d in dbinfo:
            status = "运行中" if d.get("dbStatus") == "1" else "停止"
            lines.append(
                f"  {d.get('host', '')} ({d.get('dbType', '')}) [{status}] "
                f"CPU:{d.get('cpuUsed', 'N/A')} 内存:{d.get('memory', 'N/A')} "
                f"IO:{d.get('iowait', 'N/A')} 磁盘:{d.get('disk', 'N/A')} "
                f"活跃连接:{d.get('activeConn', 'N/A')} 运行天数:{d.get('running_days', 'N/A')}"
            )
    return "\n".join(lines)


def _format_host(data: dict) -> str:
    lines = []
    alerts = data.get("hostAlarmVO", [])
    if alerts:
        lines.append(f"主机告警 ({len(alerts)}):")
        for a in alerts:
            lines.append(f"  [{a.get('state', '')}] {a.get('host', '')} - {a.get('alertName', '')}")
    else:
        lines.append("无主机告警")
    hosts = data.get("hostinfo", [])
    if hosts:
        lines.append(f"\n主机状态 ({len(hosts)}):")
        for h in hosts:
            lines.append(
                f"  {h.get('host', '')} CPU:{h.get('cpuUsed', 'N/A')} "
                f"内存:{h.get('memory', 'N/A')} IO:{h.get('iowait', 'N/A')} "
                f"磁盘:{h.get('disk', 'N/A')} 运行天数:{h.get('running_days', 'N/A')}"
            )
    return "\n".join(lines)


def _format_component(data: dict) -> str:
    lines = []
    for comp in data.get("componentVOList", []):
        name = comp.get("componentName", "unknown")
        cluster = comp.get("clusterState", "N/A")
        instances = comp.get("instanceStateVOS", [])
        running = sum(1 for i in instances if i.get("state") == "RUNNING")
        failed = sum(1 for i in instances if i.get("state") == "FAILED")
        lines.append(f"{name} (集群状态:{cluster}) — 实例: {running} 运行中, {failed} 故障")
        if failed > 0:
            for i in instances:
                if i.get("state") == "FAILED":
                    lines.append(f"  [FAILED] {i.get('ip', '')}:{i.get('port', '')} ({i.get('role', '')})")
    return "\n".join(lines) if lines else "无组件数据"


def _format_log(data: dict) -> str:
    lines = []
    for log in data.get("logManagementVOList", []):
        lines.append(f"{log.get('sysName', '')} ({log.get('comName', '')}): {log.get('msg', '')}")
    return "\n".join(lines) if lines else "无日志数据"


def _format_south_center(data: dict) -> str:
    lines = []
    for item in data.get("southCenterVOS", []):
        urgent = item.get("urgent", [])
        virtual = item.get("virtual", [])
        if urgent:
            lines.append(f"紧急告警 ({len(urgent)}):")
            for u in urgent:
                text = u[:200] + "..." if len(u) > 200 else u
                lines.append(f"  {text}")
        if virtual:
            lines.append(f"虚拟化告警 ({len(virtual)}):")
            for v in virtual:
                lines.append(f"  {v}")
    if not lines:
        lines.append("无机房告警")
    return "\n".join(lines)


# ── Prompt Builders ──────────────────────────────────────────────────

def format_phase1_summary(result: BaselineScanResult) -> str:
    """Format Phase 1 results into readable text for LLM."""
    sections = []
    adapter_labels = {
        "bpc": "BPC 业务交易监控",
        "prometheus": "Prometheus 网络监控",
        "database": "数据库监控",
        "host": "主机监控",
        "component": "中间件组件监控",
        "log": "日志监控",
        "south_center": "南方中心机房监控",
    }
    for r in result.results:
        label = adapter_labels.get(r.adapter_name, r.adapter_name)
        formatted = format_adapter_data(r.adapter_name, r.data or {})
        sections.append(f"=== {label} ===\n{formatted}")

    if result.errors:
        error_lines = [f"  - {e.adapter_name}: {e.error}" for e in result.errors]
        sections.append(f"=== 不可达系统 ===\n" + "\n".join(error_lines))

    return "\n\n".join(sections)


def build_phase2_prompt(
    request: IncidentRequest,
    phase1_result: BaselineScanResult,
    start_time: str,
    end_time: str,
) -> tuple[str, str]:
    """Build system prompt and user message for Phase 2."""
    system_prompt = f"""你是一个运维巡检 AI Agent。你的任务是根据事件信息和基础巡检数据，判断是否需要深入调查。

## 当前事件
- 系统代码：{request.system_code}
- 影响范围：{request.influence_area}
- 回溯窗口：{start_time} ~ {end_time}

## 你的能力
你可以调用监控系统查询工具来获取更多数据。每个工具需要 system_code、influence_area、start_time、end_time 四个参数。

你可以：
1. 调整时间窗口重新查询（如缩小到最近 15 分钟查看趋势变化）
2. 查询关联系统的数据
3. 当信息充足时调用 finish_investigation 结束调查

## 约束
- 最多 3 轮查询
- 只做异常发现，不做根因推测
- 信息充足时尽快结束调查"""

    phase1_summary = format_phase1_summary(phase1_result)
    user_message = f"""基础巡检已完成，以下是各监控系统的数据：

{phase1_summary}

请分析以上数据，判断是否需要进一步查询来补充信息。如果数据已经足够说明异常情况，请直接调用 finish_investigation 结束调查并给出发现摘要。"""

    return system_prompt, user_message


def build_phase3_prompt(
    request: IncidentRequest,
    phase1_result: BaselineScanResult,
    phase2_result: InvestigationResult,
) -> tuple[str, str]:
    """Build system prompt and context for Phase 3 report generation."""
    system_prompt = """你是一个运维巡检报告生成器。请根据提供的巡检数据生成一份结构化的巡检报告。

## 报告格式要求
1. 使用 Markdown 格式
2. 包含以下章节（按需，无异常的章节可以简要说明"正常"即可）：
   - 概览摘要（一句话总结巡检发现）
   - 告警详情（数据库告警、主机告警、机房告警等，按严重级排列）
   - 业务指标（BPC 交易数据是否有异常波动）
   - 基础设施状态（数据库、主机、组件运行状态概览）
   - 日志摘要
   - 数据缺失说明（如有不可达的系统）
3. 语言简洁，适合运维人员快速阅读
4. 不做根因推测，只陈述发现的异常事实"""

    phase1_summary = format_phase1_summary(phase1_result)

    findings_text = ""
    if phase2_result.findings:
        finding_lines = []
        for f in phase2_result.findings:
            finding_lines.append(f"- [{f.source}] {f.description}")
        findings_text = "\n".join(finding_lines)
    else:
        findings_text = "无额外调查发现"

    context = f"""## 事件信息
- 系统代码：{request.system_code}
- 影响范围：{request.influence_area}

## 基础巡检数据
{phase1_summary}

## 深入调查发现（Phase 2: {phase2_result.terminated_by}, 共 {phase2_result.rounds_used} 轮）
{findings_text}"""

    return system_prompt, context
