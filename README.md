# Operation Agent — 运维巡检 AI Agent V1

接收系统代码和影响范围，自动从 7 个内部监控源并行采集数据，LLM 驱动深入调查，生成结构化巡检报告。

## 架构

```
POST /api/v1/incidents { system_code, influence_area }
                ↓
        ┌───────────────┐
        │   Phase 1     │  并行调用 7 个监控 Adapter，采集基础数据
        │  基础巡检扫描  │  单个 Adapter 超时/失败不阻塞整体
        └───────┬───────┘
                ↓
        ┌───────────────┐
        │   Phase 2     │  LLM 分析 Phase 1 数据，通过 Tool Calling
        │  深入调查      │  自主决定是否补充查询（最多 3 轮）
        └───────┬───────┘
                ↓
        ┌───────────────┐
        │   Phase 3     │  LLM 汇总所有数据，生成 Markdown 巡检报告
        │  报告生成      │  LLM 不可用时自动降级为模板报告
        └───────┬───────┘
                ↓
        返回 InspectionReport JSON
```

### 7 个监控数据源

| Adapter | 数据内容 |
|---------|---------|
| BPC | 业务交易监控：交易量、响应率、成功率、平均耗时 |
| Prometheus | 网络监控：TCP/HTTP 探测节点数、异常节点 |
| Database | 数据库监控：GaussDB/Oracle 告警及实例状态 |
| Host | 主机监控：服务器告警及资源使用情况 |
| Component | 中间件监控：Redis/Consul/Zuul 集群及实例状态 |
| Log | 日志监控：应用日志关键字匹配 |
| SouthCenter | 机房监控：数据中心基础设施告警 |

> V1 版本所有 Adapter 使用 mock 数据（`monitor_api_examples.py`），接口已预留异步扩展。

## 项目结构

```
app/
├── main.py                # FastAPI 入口 + 组件初始化
├── config.py              # Pydantic Settings（环境变量配置）
├── models.py              # 所有数据模型
├── adapters/
│   ├── base.py            # BaseAdapter ABC + AdapterRegistry
│   └── mock_adapters.py   # 7 个 mock adapter 实现
├── llm/
│   └── client.py          # OpenAI 兼容异步 LLM 客户端
└── agent/
    ├── orchestrator.py    # 三阶段编排引擎
    ├── phase1.py          # Phase 1: 并行基础扫描
    ├── phase2.py          # Phase 2: LLM Tool Calling 调查循环
    ├── phase3.py          # Phase 3: 报告生成 + 降级策略
    ├── tools.py           # Phase 2 工具定义
    └── prompts.py         # Prompt 模板 + 数据格式化
```

## 快速开始

### 环境要求

- Python 3.11+
- 一个 OpenAI 兼容的 LLM 服务（可选，没有也能跑，会降级为模板报告）

### 安装

```bash
git clone https://github.com/JinzeWang10/operation-agent.git
cd operation-agent
pip install -e ".[dev]"
```

### 配置

```bash
cp .env.example .env
```

编辑 `.env`：

```
AGENT_LLM_API_KEY=你的API密钥
AGENT_LLM_BASE_URL=https://你的LLM服务地址/v1
AGENT_LLM_MODEL=模型名称
AGENT_DEBUG=true
```

完整配置项：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `AGENT_LLM_API_KEY` | (空) | LLM API 密钥 |
| `AGENT_LLM_BASE_URL` | `http://localhost:8000/v1` | LLM 服务地址 |
| `AGENT_LLM_MODEL` | `gpt-4o` | 模型名称 |
| `AGENT_LLM_TEMPERATURE` | `0.1` | 生成温度 |
| `AGENT_TIMEOUT_TOTAL` | `120` | 总超时（秒） |
| `AGENT_TIMEOUT_ADAPTER` | `15` | 单个 Adapter 超时（秒） |
| `AGENT_TIMEOUT_PHASE2` | `60` | Phase 2 超时（秒） |
| `AGENT_PHASE2_MAX_ROUNDS` | `3` | Phase 2 最大调查轮数 |
| `AGENT_DEBUG` | `false` | 调试模式 |

### 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 使用

**健康检查：**

```bash
curl http://localhost:8000/health
```

返回：
```json
{"status": "ok", "adapters": ["bpc", "prometheus", "database", "host", "component", "log", "south_center"]}
```

**触发巡检：**

```bash
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{"system_code": "SBYL", "influence_area": "总公司"}'
```

可选参数 `time_window_minutes`（默认 60 分钟）：

```bash
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{"system_code": "SBYL", "influence_area": "总公司", "time_window_minutes": 30}'
```

返回示例：
```json
{
  "incident_id": "a1b2c3d4",
  "report_markdown": "# 巡检报告\n\n## 概览摘要\n...",
  "phases_summary": {
    "phase1": {"total_adapters": 7, "successful": 7, "errors": 0},
    "phase2": {"rounds_used": 1, "terminated_by": "llm", "findings_count": 3},
    "phase3": {"report_length": 1500}
  },
  "duration_seconds": 12.5
}
```

### 运行测试

```bash
pytest tests/ -v
```

测试全部使用 mock，不依赖真实 LLM 服务。

## 降级策略

当 LLM 服务不可用时：

- **Phase 2**：跳过深入调查，标记 `terminated_by: "llm_unavailable"`
- **Phase 3**：自动生成模板报告，直接展示 Phase 1 采集的原始数据

巡检流程不会因 LLM 故障而中断。

## V1 不包含

- Webhook 通知推送（钉钉/飞书/Slack）
- Docker 部署
- 真实 HTTP 监控 API 调用（仅 mock）
- API 鉴权
- 异步任务队列
