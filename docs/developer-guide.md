# 开发者指南

本文档面向后续开发者，帮助你快速理解仓库的代码组织、模块职责、数据流转和扩展方式。

---

## 目录

1. [整体架构](#整体架构)
2. [目录结构与模块职责](#目录结构与模块职责)
3. [请求生命周期：一次巡检的完整数据流](#请求生命周期一次巡检的完整数据流)
4. [核心模块详解](#核心模块详解)
   - [数据模型 (models.py)](#数据模型-modelspy)
   - [配置管理 (config.py)](#配置管理-configpy)
   - [Adapter 层](#adapter-层)
   - [LLM 客户端](#llm-客户端)
   - [Agent 三阶段引擎](#agent-三阶段引擎)
   - [Prompt 与数据格式化](#prompt-与数据格式化)
   - [FastAPI 入口 (main.py)](#fastapi-入口-mainpy)
5. [依赖关系图](#依赖关系图)
6. [测试组织](#测试组织)
7. [常见扩展场景](#常见扩展场景)

---

## 整体架构

系统是一个三阶段串行管线，由 `Orchestrator` 编排：

```
HTTP 请求 → Orchestrator.run()
               │
               ├── Phase 1: BaselineScanner
               │     并行调用 7 个 Adapter，采集原始监控数据
               │     返回 BaselineScanResult
               │
               ├── Phase 2: DeepInvestigator
               │     prompts.py 将 Phase 1 数据格式化为文本
               │     LLM 通过 Tool Calling 自主决定是否补查
               │     最多 3 轮，返回 InvestigationResult
               │
               └── Phase 3: ReportGenerator
                     prompts.py 构建上下文
                     LLM 生成 Markdown 报告
                     失败时降级为模板报告
                     返回 report_markdown 字符串

Orchestrator 组装最终的 InspectionReport → HTTP 响应
```

核心设计原则：

- **Phase 1 纯代码驱动**，不依赖 LLM，保证数据一定能采集到
- **Phase 2/3 依赖 LLM 但有降级**，LLM 不可用时整条管线仍能跑通
- **每个 Adapter 独立超时**，单个数据源失败不阻塞其他

---

## 目录结构与模块职责

```
app/
├── __init__.py
├── main.py                 # FastAPI 应用入口，组件初始化和路由定义
├── config.py               # Settings 类，从环境变量读取所有配置
├── models.py               # 全部 Pydantic 数据模型，贯穿三个阶段
│
├── adapters/               # ── 数据采集层 ──
│   ├── __init__.py
│   ├── base.py             # BaseAdapter 抽象类 + AdapterRegistry 注册表
│   └── mock_adapters.py    # 7 个 mock 实现 + create_default_registry() 工厂
│
├── llm/                    # ── LLM 通信层 ──
│   ├── __init__.py
│   └── client.py           # LLMClient：chat() 和 chat_with_tools() 两个方法
│
└── agent/                  # ── 核心业务逻辑 ──
    ├── __init__.py
    ├── orchestrator.py     # Orchestrator：串联三个阶段，生成最终报告
    ├── phase1.py           # BaselineScanner：并行扫描所有 Adapter
    ├── phase2.py           # DeepInvestigator：LLM Tool Calling 调查循环
    ├── phase3.py           # ReportGenerator：LLM 报告生成 + 降级策略
    ├── tools.py            # Tool Calling 的工具定义和执行逻辑
    └── prompts.py          # Prompt 模板 + 7 种数据格式化函数

tests/
├── conftest.py             # 共享 fixture（Settings 等）
├── test_models.py          # 数据模型测试
├── test_adapters.py        # Adapter 注册和数据采集测试
├── test_llm_client.py      # LLM 客户端测试（全 mock）
├── test_phase1.py          # Phase 1 测试（含超时、失败场景）
├── test_prompts.py         # 格式化和 Prompt 构建测试
├── test_phase2.py          # Phase 2 测试（工具定义 + 调查循环）
├── test_phase3.py          # Phase 3 测试（LLM 正常 / 降级）
├── test_orchestrator.py    # 编排引擎测试（含 Phase 2 失败降级）
└── test_api.py             # HTTP 端点测试
```

---

## 请求生命周期：一次巡检的完整数据流

以 `POST /api/v1/incidents {"system_code":"SBYL","influence_area":"总公司"}` 为例：

### 1. HTTP 入口 (`main.py:46`)

FastAPI 将请求体解析为 `IncidentRequest`，调用 `orchestrator.run(request)`。

### 2. Orchestrator (`orchestrator.py:32`)

生成 `incident_id`，计算时间窗口（当前时间往前推 60 分钟），然后依次执行三个阶段。

### 3. Phase 1: 并行数据采集 (`phase1.py`)

```
BaselineScanner.scan()
  ├── asyncio.gather 并行调用 7 个 Adapter
  │     每个 Adapter 有独立的 asyncio.wait_for(timeout=15s)
  │     ├── 成功 → AdapterResult(data={...})
  │     └── 超时/异常 → AdapterResult(error="...")
  └── 返回 BaselineScanResult
        ├── results: 成功的 AdapterResult 列表
        └── errors: 失败的 AdapterResult 列表
```

### 4. Phase 2: LLM 深入调查 (`phase2.py`)

```
build_phase2_prompt()           # prompts.py 将 Phase 1 数据格式化为可读文本
  └── 返回 (system_prompt, user_message)

DeepInvestigator.investigate()
  ├── 构建 tool definitions     # tools.py: 每个 Adapter → query_<name> 工具
  │                              #           + finish_investigation 工具
  └── 循环（最多 3 轮）：
        ├── LLM 返回 tool_calls
        │     ├── finish_investigation → 记录 summary，终止循环
        │     └── query_<name> → execute_tool() 调用对应 Adapter，
        │                         结果作为 tool message 回传 LLM
        ├── LLM 返回纯文本（无 tool_calls）→ 记录为 finding，终止
        ├── 超时 → 终止
        └── LLM 异常 → 记录错误，终止
  返回 InvestigationResult
```

### 5. Phase 3: 报告生成 (`phase3.py`)

```
build_phase3_prompt()           # prompts.py 构建报告生成的 system prompt + context
  └── context 包含：Phase 1 数据 + Phase 2 发现

ReportGenerator.generate()
  ├── 调用 LLM chat()
  │     ├── 返回内容 > 50 字符 → 使用 LLM 报告
  │     └── 返回为空或太短 → 降级
  └── 降级 → _generate_fallback() 模板拼接原始数据
  返回 Markdown 字符串
```

### 6. 组装返回 (`orchestrator.py:79`)

Orchestrator 将三个阶段的结果组装为 `InspectionReport`，包含 `report_markdown`、`phases_summary`（各阶段统计）和 `duration_seconds`。

---

## 核心模块详解

### 数据模型 (`models.py`)

6 个 Pydantic 模型，是三个阶段之间的数据契约：

| 模型 | 用途 | 生产者 → 消费者 |
|------|------|-----------------|
| `IncidentRequest` | 巡检请求入参 | HTTP 请求 → Orchestrator |
| `AdapterResult` | 单个 Adapter 的采集结果 | Phase 1 → Phase 1 汇总 |
| `BaselineScanResult` | Phase 1 汇总结果 | Phase 1 → Phase 2, Phase 3 |
| `Finding` | 一条调查发现 | Phase 2 → Phase 3 |
| `InvestigationResult` | Phase 2 汇总结果 | Phase 2 → Phase 3, Orchestrator |
| `InspectionReport` | 最终巡检报告 | Orchestrator → HTTP 响应 |

关键字段说明：

- `AdapterResult.data`：各监控 API 返回的原始 dict，结构各不相同
- `InvestigationResult.terminated_by`：记录 Phase 2 的终止原因，可选值：`"llm"` / `"max_rounds"` / `"timeout"` / `"llm_error"` / `"llm_unavailable"` / `"llm_no_tools"` / `"not_started"`
- `InspectionReport.phases_summary`：各阶段的执行统计，用于监控和调试

### 配置管理 (`config.py`)

基于 `pydantic-settings`，所有配置通过 `AGENT_` 前缀的环境变量注入。主要分三组：

- **超时控制**：`timeout_total`、`timeout_adapter`、`timeout_phase2`、`phase2_max_rounds`
- **LLM 连接**：`llm_api_key`、`llm_base_url`、`llm_model`、`llm_temperature`
- **业务参数**：`default_time_window_minutes`

配置在 `main.py` 中实例化一次，通过构造函数注入到各组件。

### Adapter 层

**`base.py`** 定义了两个核心抽象：

- `BaseAdapter`（ABC）：每个监控数据源必须实现 `name`、`description`、`fetch_data()` 三个接口。`fetch_data()` 是 async 方法，V1 的 mock 实现虽然是同步的，但接口预留了异步扩展能力。
- `AdapterRegistry`：一个简单的 name → adapter 字典，提供 `register()`、`get()`、`all()`、`names()` 四个方法。

**`mock_adapters.py`** 包含 7 个具体 Adapter 类，每个只是薄薄的一层包装：

```python
class BPCAdapter(BaseAdapter):
    async def fetch_data(self, ...):
        return get_bpc_monitor_data(...)  # 直接调用 monitor_api_examples.py
```

`create_default_registry()` 是工厂函数，注册全部 7 个 Adapter 并返回 Registry 实例。

### LLM 客户端

`LLMClient` 封装 `openai.AsyncOpenAI`，提供两个方法：

- `chat(messages) → str`：普通对话，返回文本内容。Phase 3 使用。
- `chat_with_tools(messages, tools) → message`：带 Tool Calling 的对话，返回原始 message 对象（可能包含 `tool_calls`）。Phase 2 使用。

任何兼容 OpenAI Chat Completion API 的服务都可以直接使用（DeepSeek、通义千问、本地部署的 vLLM 等），只需修改 `AGENT_LLM_BASE_URL` 和 `AGENT_LLM_MODEL`。

### Agent 三阶段引擎

**`phase1.py` — BaselineScanner**

核心逻辑在 `_fetch_one()` 方法：用 `asyncio.wait_for()` 给每个 Adapter 包一层超时，然后用 `asyncio.gather()` 并行执行所有 Adapter。无论成功、超时还是异常，都会返回一个 `AdapterResult`，确保不会因为单个数据源卡死整个扫描。

**`phase2.py` — DeepInvestigator**

这是整个系统中逻辑最复杂的部分。核心是一个 for 循环（最多 `max_rounds` 轮），每轮：

1. 调用 `LLMClient.chat_with_tools()`，把当前消息历史和工具定义发给 LLM
2. 如果 LLM 返回 `tool_calls`，遍历执行每个工具调用：
   - `finish_investigation` → 记录 summary，标记结束
   - `query_<adapter_name>` → 通过 `execute_tool()` 调用对应 Adapter，结果作为 `tool` message 追加到消息历史
3. 如果 LLM 没有返回 tool_calls（纯文本回复），直接记录并终止

循环有三个终止条件：LLM 主动 finish、超时、轮次耗尽。还有一个异常终止：LLM 调用报错。

**`phase3.py` — ReportGenerator**

调用 `LLMClient.chat()` 生成报告。降级策略：如果 LLM 返回的内容长度不足 50 字符或抛出异常，调用 `_generate_fallback()` 用模板拼接原始数据。降级报告会在标题标注"模板生成"，正文提示"LLM 不可用"。

**`tools.py` — 工具定义与执行**

两个函数：

- `build_tool_definitions(registry)`：遍历 Registry，为每个 Adapter 生成一个 `query_<name>` 工具（OpenAI function calling 格式），加上一个 `finish_investigation` 工具。参数统一为 `system_code`、`influence_area`、`start_time`、`end_time`。
- `execute_tool(name, arguments, registry)`：根据工具名找到对应 Adapter 并调用 `fetch_data()`，返回 JSON 字符串。

### Prompt 与数据格式化

`prompts.py` 有两层职责：

**数据格式化**（上半部分）：将各 Adapter 返回的原始 dict 转为人类可读的文本。每种 Adapter 有独立的 formatter（`_format_bpc`、`_format_database` 等），因为各 API 的数据结构完全不同。`format_phase1_summary()` 将所有 Adapter 的格式化结果组合成完整的 Phase 1 摘要文本。

**Prompt 构建**（下半部分）：

- `build_phase2_prompt()`：构建 Phase 2 的 system prompt（角色定义、能力说明、约束）和 user message（Phase 1 数据摘要 + 指令）
- `build_phase3_prompt()`：构建 Phase 3 的 system prompt（报告格式要求）和 context（事件信息 + Phase 1 数据 + Phase 2 发现）

所有 Prompt 都是中文的，面向内部运维场景。

### FastAPI 入口 (`main.py`)

模块级代码完成所有组件的初始化：

```python
Settings → Registry → LLMClient → Scanner / Investigator / Reporter → Orchestrator
```

这是一个简单的依赖注入链。两个路由：

- `GET /health`：返回服务状态和 Adapter 列表
- `POST /api/v1/incidents`：调用 `orchestrator.run()`，同时在控制台打印报告

---

## 依赖关系图

```
main.py
  ├── config.py (Settings)
  ├── models.py (所有模型)
  ├── adapters/
  │     ├── base.py (BaseAdapter, AdapterRegistry)
  │     └── mock_adapters.py (7 个实现) → monitor_api_examples.py
  ├── llm/client.py (LLMClient) → openai SDK
  └── agent/
        ├── orchestrator.py → phase1, phase2, phase3, prompts
        ├── phase1.py → adapters/base (Registry)
        ├── phase2.py → llm/client, tools
        ├── phase3.py → llm/client, prompts
        ├── tools.py → adapters/base (Registry)
        └── prompts.py → models
```

关键依赖方向：`agent/` 依赖 `adapters/` 和 `llm/`，反过来不成立。`models.py` 被所有模块引用。`prompts.py` 是 `agent/` 内部的共享模块，被 phase2、phase3、orchestrator 引用。

---

## 测试组织

所有测试在 `tests/` 下，按模块一一对应：

| 测试文件 | 覆盖模块 | 测试策略 |
|---------|---------|---------|
| `test_models.py` | `models.py` | 直接实例化验证默认值和字段 |
| `test_adapters.py` | `adapters/` | 验证 Registry 注册/查询，验证 Adapter 返回数据结构 |
| `test_llm_client.py` | `llm/client.py` | mock `AsyncOpenAI`，验证方法签名和返回值 |
| `test_phase1.py` | `agent/phase1.py` | 用真实 mock adapter 测试成功路径；用 `SlowAdapter`/`FailingAdapter` 测试超时和异常 |
| `test_prompts.py` | `agent/prompts.py` | 构造各种数据 dict，验证格式化输出包含预期文本 |
| `test_phase2.py` | `agent/phase2.py` + `tools.py` | mock LLM 返回预设的 tool_calls，验证循环逻辑和终止条件 |
| `test_phase3.py` | `agent/phase3.py` | mock LLM 正常返回 / 抛异常 / 返回空，验证降级策略 |
| `test_orchestrator.py` | `agent/orchestrator.py` | mock 三个阶段组件，验证串联逻辑和 Phase 2 失败降级 |
| `test_api.py` | `main.py` | 用 FastAPI TestClient 测试 HTTP 端点 |

`conftest.py` 提供共享的 `settings` fixture。

测试**不依赖任何外部服务**，LLM 调用全部通过 `unittest.mock.AsyncMock` 模拟。

---

## 常见扩展场景

### 接入真实监控 API

1. 在 `app/adapters/` 下新建文件（如 `real_adapters.py`）
2. 继承 `BaseAdapter`，在 `fetch_data()` 中用 `httpx.AsyncClient` 发起真实 HTTP 请求
3. 创建新的 registry 工厂函数（或修改 `create_default_registry()`）注册新 Adapter
4. 在 `prompts.py` 的 `format_adapter_data()` 中为新数据格式添加 formatter（如果数据结构变了）

### 添加新的监控数据源

1. 新建 Adapter 类继承 `BaseAdapter`，实现 `name`、`description`、`fetch_data()`
2. 在 `create_default_registry()` 中注册
3. 在 `prompts.py` 中添加对应的 `_format_<name>()` 函数，并注册到 `format_adapter_data()` 的 formatters 字典
4. `tools.py` 的 `build_tool_definitions()` 会自动为新 Adapter 生成 Tool，**无需额外修改**

### 更换 LLM 服务

只需修改环境变量，无需改代码：

```
AGENT_LLM_BASE_URL=https://新服务地址/v1
AGENT_LLM_MODEL=新模型名
AGENT_LLM_API_KEY=新密钥
```

支持任何兼容 OpenAI Chat Completion API 的服务。

### 修改报告格式

编辑 `prompts.py` 中的 `build_phase3_prompt()` 函数，修改 system prompt 中的"报告格式要求"章节即可。降级报告的格式在 `phase3.py` 的 `_generate_fallback()` 方法中。

### 调整 Phase 2 行为

- 改变最大调查轮数：环境变量 `AGENT_PHASE2_MAX_ROUNDS`
- 改变超时：环境变量 `AGENT_TIMEOUT_PHASE2`
- 修改 LLM 的调查策略：编辑 `prompts.py` 中 `build_phase2_prompt()` 的 system prompt
- 增减可用工具：修改 `tools.py` 中的 `build_tool_definitions()`
