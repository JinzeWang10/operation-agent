# Operation Agent — 运维 AI 工具集

面向封闭内网运维场景的一组 LLM 驱动工具，共用一个 OpenAI 兼容的 LLM 客户端（`big_data_model/llm/client.py`）和统一配置（`big_data_model/config.py`）。

## 模块总览

| 模块 | 功能 | 说明文档 |
|------|------|---------|
| `big_data_model/incident/` | **事件会诊速览**：把监控聚合快照加工成中文现象简报 + 会诊速览 PNG（HTML + 无头 Chromium 渲染） | [README](big_data_model/incident/README.md) · [DEPLOY](big_data_model/incident/DEPLOY.md) |
| `big_data_model/knowledge_pipeline/` | **故障知识蒸馏**：把历史事件工单批量转成案例库（Case JSONL）和候选故障模式（Pattern YAML，人审后入库） | [DEPLOY](big_data_model/knowledge_pipeline/DEPLOY.md) |
| `big_data_model/pull_agent/` | **拉人 Agent**：解析自然语言（如"请拉 Linux 和 GaussDB 的运维经理"），调用接口把对应运维经理拉入群 | [设计文档](docs/plans/2026-04-21-pull-manager-agent.md) |

依赖关系：`knowledge_pipeline` 复用 `incident` 的特征抽取和知识 schema；`incident` 与 `pull_agent` 互不依赖；三者都通过 `config.py` + `llm/client.py` 访问 LLM。

## 项目结构

```
big_data_model/
├── config.py              # Pydantic Settings（环境变量配置，AGENT_ 前缀）
├── llm/
│   └── client.py          # OpenAI 兼容异步 LLM 客户端
├── incident/              # 事件会诊速览（抽取 / 解读 / 渲染三层分离）
│   ├── features.py        #   特征抽取
│   ├── summarizer.py      #   LLM 现象简报
│   ├── render/            #   Jinja + CSS + Playwright 渲染
│   └── knowledge/         #   故障知识 schema / 案例库 / 探针
├── knowledge_pipeline/    # 历史工单 → 故障知识 批处理管线
└── pull_agent/            # 单轮 NLU 拉人 agent

scripts/
└── pull_agent_smoke.py    # pull_agent 手动冒烟脚本

tests/
├── incident/              # incident 单测 + 渲染 e2e
├── pull_agent/            # pull_agent 单测 + LLM e2e
└── test_llm_client.py     # LLM 客户端单测

docs/
├── design.md / design.pdf # V1 巡检 Agent 设计（历史存档，代码已移除）
├── monitor_data_understanding.md
└── plans/                 # 各阶段实施计划（按日期）
```

> 历史说明：仓库最初是"三阶段巡检 Agent V1"（FastAPI + 7 个监控 Adapter），该版本代码已于 2026-07 清理，设计文档保留在 `docs/`，代码可从 git 历史找回（tag 前最后提交 `88e8a11`）。

## 快速开始

### 安装

```bash
pip install -e ".[dev]"
```

incident 渲染另需：`pip install -r big_data_model/incident/requirements.txt`，并执行 `playwright install chromium`（内网部署见 [DEPLOY.md](big_data_model/incident/DEPLOY.md)）。

### 配置

```bash
cp .env.example .env
```

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `AGENT_LLM_API_KEY` | (空) | LLM API 密钥 |
| `AGENT_LLM_BASE_URL` | `http://localhost:8000/v1` | LLM 服务地址 |
| `AGENT_LLM_MODEL` | `gpt-4o` | 模型名称 |
| `AGENT_LLM_TEMPERATURE` | `0.1` | 生成温度 |
| `AGENT_DEBUG` | `false` | 调试模式 |

### 运行测试

```bash
pytest tests/ -v -m "not e2e"   # 全 mock，不依赖真实 LLM
pytest tests/ -v -m e2e         # 真调 LLM 的端到端测试
```
