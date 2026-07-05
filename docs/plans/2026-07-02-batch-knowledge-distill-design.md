# 历史事件批量转化为故障知识 — 设计

日期：2026-07-02
作者：JinzeWang10
状态：设计定稿，待实现

关联：[事件处置 Agent 落地计划](2026-06-02-incident-rca-agent-plan.md) 第六节"知识沉淀机制"。本设计是那套知识库的**冷启动灌注管线**——把内网存量事件工单批量蒸馏成 `Case`（案例库）与候选 `Pattern`（故障模式库）。

---

## 一、问题与目标

内网有大量形如 `example.sql` 查出的事件记录（样本见 `event_monitor_20260702.xlsx`，50 行 × 34 列）。每行是一个事件工单，**已经同时包含**：

- 自由文本根因（`fault_reason`，如"批量作业导致""数据备份完成后恢复"）与处置记录（`solution_record`）；
- 事发时的**现场快照** `monitor_data`（嵌套 JSON，含 BPC 耗时时序 / 主机 / DB / 组件状态 / 日志关键字 / 发布 / 客户异常率等 12 个监控块）。

因此本管线的本质是**结构化萃取**（现象+根因都在原始数据里），而非"重新调查推理"。

**目标**：一个可批量运行的脚本，用内网大模型把这些行转成两类故障知识：
1. **Stage 1 — 案例库**：每行 → 一条 `Case`（`来源="历史导入"`），写入现有 `CaseStore` JSONL。
2. **Stage 2 — 候选故障模式**：在案例库上聚类蒸馏候选 `Pattern`（YAML，`备注="待人审"`），供人审入库——**不自动进库**，与计划里"人审入库"的定位一致。

## 二、关键决策（已与需求方确认）

| 决策 | 取值 | 理由 |
|------|------|------|
| 产出目标 | 两段式：案例 → 模式 | 先确定性沉底案例，再在案例上蒸馏模式 |
| 无效事件 `is_invalid=1` | 全部保留，打标签 | "误报/自动恢复"本身是知识；用字段标记，下游聚类可筛 |
| 根因分类法 `类别` | 需求方给固定枚举 | 与 Pattern ID 前缀同一套，保证两段一致性。当前先用**种子枚举**占位，待替换 |
| 输入方式 | 同时支持 xlsx/csv 与 SQL | 主路径读导出文件；预留"直连 DB 跑 example.sql"的 adapter 接口 |
| LLM | 复用 `LLMClient`（OpenAI 兼容） | 端点走 `AGENT_LLM_*` 环境变量；开发期用可达替代端点/离线 stub 验证，内网改 `.env` 即跑 |
| 编码 | 无需处理 | 已验证数据是正常 UTF-8，之前的乱码仅是 Windows 终端码页显示假象 |

## 三、复用现有资产（不重写）

- `incident/features.py::extract(monitor_data)` → `FeatureBag`，`.to_llm_brief()` 给紧凑现场摘要；BPC `symptom_type` 已对齐 `SYMPTOM_TAGS`（slow/errors/response_drop/volume_drop）。**确定性解析层完全复用。**
- `incident/knowledge/case_store.py`：`Case` / `RootCause` / `Hypothesis` / `CaseStore`（append-only JSONL）。Stage 1 输出目标。
- `incident/knowledge/schema.py`：`Pattern` / `PatternLibrary` / `probes.PROBES`。Stage 2 输出目标与校验。
- `llm/client.py::LLMClient.chat(messages)`。

## 四、模块结构

```
big_data_model/knowledge_pipeline/
  __init__.py
  taxonomy.py     # 种子根因类别枚举（待需求方替换）+ 校验
  loaders.py      # load_rows_from_file(xlsx/csv) + SqlSource 接口（内网填连接串）
  parse.py        # 行 → (确定性现场摘要 dict, 症状标签, 元信息)；复用 features.extract
  prompts.py      # Stage1 萃取 prompt / Stage2 蒸馏 prompt（中文、受约束 JSON 输出）
  extract.py      # Stage1: 行 → Case（确定性解析 + LLM 萃取根因/摘要 → Case 校验）
  distill.py      # Stage2: 案例聚类 + LLM 蒸馏 → 候选 Pattern YAML
  batch.py        # 限并发/重试/断点续跑台账/单行失败不阻断/成本耗时统计
  llm_stub.py     # 离线确定性 stub，供无端点时跑通全链路
  run.py          # CLI: `python -m big_data_model.knowledge_pipeline.run stage1|stage2 ...`
```

## 五、Stage 1：行 → Case

每行处理：
1. **确定性解析**（无 LLM，失败不致命）：`ast.literal_eval(monitor_data)` → `features.extract` → `FeatureBag`；取 `to_llm_brief()` 作现场摘要，聚合各系统 `symptom_type` 为事件级症状标签。
2. **LLM 萃取**（受约束 JSON）：输入 = 工单文本字段（title/describe/fault_reason/solution_record/结论）+ 上一步现场摘要 brief。输出：
   - `现场摘要`（自然语言，一段）
   - `回填`：`{类别（枚举内）, 定位对象, 描述}`（真实根因，来自 fault_reason/solution）
   - `有效性`：valid / invalid（映射 `is_invalid`，并让 LLM 复核"是否误报/自动恢复"）
   - 低置信标记（字段缺失或矛盾时置 true，供人审）
3. **组装 `Case`**：`来源="历史导入"`，`回填`/`回填时间`=工单结单时间，`原始`=整行无损保留，症状标签写入。按 `Case` schema 校验，`append` 到 JSONL。

幂等：按 `order_number` 记台账，已处理跳过（支持中断续跑与增量）。

## 六、Stage 2：案例 → 候选 Pattern

1. **确定性聚类**：按 `(回填.类别, 回填.定位对象 归一, 主症状标签)` 分组；`is_invalid` 事件单独成"误报/自恢复"簇。
2. **LLM 蒸馏**：每个 ≥N 条（默认 3）的簇，喂该簇案例的现象+根因摘要 → 输出候选 `Pattern`（名称/适用条件/现象/候选根因/验证方法/排除/症状标签），`来源案例`=簇内事件 ID，`验证[].probe` 从 `PROBES` 注册表里选。
3. **落盘**：按 `Pattern` schema 校验后写 YAML 到 `knowledge_pipeline/out/candidate_patterns/`，`备注` 标注"待人审 + 蒸馏依据簇大小"。人审后移入 `incident/knowledge/patterns/`。

## 七、批处理基建

- `asyncio` + 信号量限并发（默认 4，配置化，避让内网 80s/次）。
- 每行独立 try/except，失败写 `errors.jsonl` 不阻断（沿用 `BaselineScanner` 精神）。
- LLM JSON 解析失败自动重试（默认 2 次，带"仅输出 JSON"纠偏提示）。
- 断点续跑台账 `_ledger.json`（已处理 order_number 集合）。
- 结束打印统计：成功/失败/跳过、耗时、（可选）token。

## 八、验证策略

- **非 LLM 部分**：现在就用真实 50 行跑通 —— 加载、`monitor_data` 解析、现场摘要、症状标签、Case schema 组装，全部走真实数据。
- **LLM 部分**：先用离线 `llm_stub` 跑通全链路 plumbing；需求方给可达替代端点后，跑 3–5 行小批 → 全量；内网部署仅改 `.env`。

## 九、非目标（YAGNI）

- 不做向量库/RAG（计划里是 V2+）。
- 不自动把候选 Pattern 入库（必须人审）。
- 不做基线库/拓扑库灌注（本管线只产 Case + 候选 Pattern；基线另有历史指标来源）。
