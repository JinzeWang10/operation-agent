# knowledge_pipeline 内网部署说明

一句话：把历史事件工单（example.sql 查出的那种数据）批量转成两类故障知识——
**案例库**（`Case` JSONL）和**候选故障模式**（`Pattern` YAML，人审后入库）。

设计文档：`docs/plans/2026-07-02-batch-knowledge-distill-design.md`

---

## 一、这次新增了什么（未改动任何现有文件）

全部代码在新包 `big_data_model/knowledge_pipeline/`，只**调用**现有模块，零回归风险：

| 文件 | 干什么 |
|------|--------|
| `taxonomy.py` | 根因类别枚举（DB/RELEASE/BATCH/HOST/NET/MIDDLEWARE/APP/CONFIG/DEPENDENCY/CLIENT/NOISE/UNKNOWN）。**正式枚举定稿后改这里的 `_SEED`**，或用环境变量 `AGENT_KP_TAXONOMY=DB,RELEASE,...` 覆盖。类别代码请用纯大写字母数字（会作为 Pattern id 前缀） |
| `loaders.py` | 数据源。`FileSource` 读 xlsx/csv 导出；`SqlSource` 直连数据库跑 `example.sql` |
| `parse.py` | 确定性解析：`monitor_data` → 现场摘要 + 症状标签（复用 `incident/features.py`，与线上 Agent 同一套口径） |
| `prompts.py` | 两段 prompt：Stage1 根因萃取 / Stage2 模式蒸馏，受约束 JSON 输出 |
| `extract.py` | Stage1：每行 → 一条 `Case`，schema 校验后写入案例库 |
| `distill.py` | Stage2：案例按类别聚类 → LLM 蒸馏候选 `Pattern` YAML |
| `batch.py` | 批处理：限并发、断点续跑、单行失败不阻断、统计 |
| `llm_stub.py` | 离线桩，不连 LLM 也能验证全链路 |
| `run.py` | 命令行入口 |

复用的现有模块（未改动）：`incident/features.py`、`incident/knowledge/case_store.py`、
`incident/knowledge/schema.py`、`incident/knowledge/probes.py`、`llm/client.py`、`config.py`。

## 二、内网部署步骤

### 1. 依赖
```
pip install "openai>=1.0" pandas openpyxl        # 基本路径
pip install sqlalchemy <数据库驱动>               # 仅当用 --db-url 直连时
```
（`pydantic`/`pyyaml` 等项目已有依赖不变。）

### 2. 配置 `.env`（仓库根目录，已在 gitignore）
```
AGENT_LLM_BASE_URL=<内网 qwen 的 OpenAI 兼容端点，如 http://x.x.x.x:8000/v1>
AGENT_LLM_API_KEY=<key，没有就随便填个非空串>
AGENT_LLM_MODEL=<内网模型名>
```
不改任何代码——`llm/client.py` 是 OpenAI 兼容客户端，换端点即用。

### 3. 冒烟验证（不耗 LLM 配额）
```
python -m big_data_model.knowledge_pipeline.run stage1 --file 导出.xlsx --stub --limit 5
```
桩模式全链路跑通说明环境 OK。

### 4. 正式跑 Stage 1（事件行 → 案例库）
```
# 方式 A：xlsx/csv 导出文件
python -m big_data_model.knowledge_pipeline.run stage1 --file 导出.xlsx --concurrency 2

# 方式 B：直连数据库跑 example.sql（推荐，见"已知坑"第 1 条）
python -m big_data_model.knowledge_pipeline.run stage1 --db-url "内网库的SQLAlchemy连接串"
```
- 产物：`big_data_model/knowledge_pipeline/out/cases.jsonl`（案例库）、`errors.jsonl`（失败明细）。
- **断点续跑**：中断后原命令重跑即可，已成功的行自动跳过（台账 `out/_ledger.json`）；
  想全量重来加 `--no-resume`。
- 内网模型慢（~80s/次）时 `--concurrency 2` 起步；连接类错误自带指数退避重试。
- 先 `--limit 5` 小批看质量，再放全量。

### 5. 正式跑 Stage 2（案例库 → 候选故障模式）
```
python -m big_data_model.knowledge_pipeline.run stage2 --min-size 3
```
- 产物：`out/candidate_patterns/PATTERN-*.yaml`。
- **候选模式不会自动入库**。人审流程：逐条核对（`来源案例` 字段可回溯到
  cases.jsonl 里的具体事件）→ 修订 → 移入 `big_data_model/incident/knowledge/patterns/`。

## 三、已知坑（都踩过了）

1. **xlsx 截断**：Excel 单元格上限 32767 字符，超长 `monitor_data` 会被静默截断，
   导致现场快照解析失败（管线会降级：只凭工单文本萃取 + 标低置信）。
   **数据量大/快照大时用 `--db-url` 直连，不要走 xlsx。**
2. **中文"乱码"**：Windows 控制台 GBK 码页显示中文可能是乱码，**数据和产物文件
   本身是正常 UTF-8**，用编辑器打开确认即可。CLI 已做防崩处理。
3. **is_invalid 不可尽信**：样本里全部工单标 `is_invalid=1`，但 LLM 复核出约半数
   有明确根因与处置动作，实为真实故障。萃取结果里 `原始._kp_meta.有效性` 是
   LLM 复核结论，`is_invalid_flag` 是原始标记，两者都保留。
4. **低置信案例**：`原始._kp_meta.低置信=true` 的（快照缺失/文本矛盾）建议人工优先复核。

## 三点五、归一化与人工复核标记（2026-08 新增）

为让「命中匹配 / 同系统召回」能对齐，新增确定性归一化层
`incident/knowledge/normalize.py`（系统名规范化 + 定位对象 facet 分解 + 命中口径
「系统+实例token，可降级」）。**消费端自动生效，`cases.jsonl` 无需改、不做迁移。**

内网跑前/跑后注意：

1. **替换系统名词表**：`incident/knowledge/vocab/systems.txt` 当前是从历史 `fault_system`
   自举的**种子**（约 95 条）。内网请用 `t_business_standard.system_name` 的快照
   **整体替换**（一行一个，`#` 开头为注释）。替换后系统识别覆盖更高。
2. **外部依赖词表**：`vocab/external_deps.txt`（行业平台/税局通道等，不在 t_business_standard），
   种子约 11 条，**需人工审核增删**。
3. **系统名标记**：归不进词表的系统名 `resolve_system().resolved=False`（当前种子词表下
   约 14%），这类留待后续人工复核，不阻塞。
4. **prompt 已加强（本次重跑生效）**：Stage 1 要求「回填.描述」必填且与「现场摘要」区分、
   禁止有根因文本时返回 UNKNOWN 空壳；Stage 2 聚类已排除 UNKNOWN 桶。
   → 建议重跑时定向补 UNKNOWN 漏判行 + 断连失败行（断点续跑自动跳过已成功行）。

## 三点六、人工复核优先级口径（Phase 3 输入 · 代码暂未实现）

**背景（2026-08 内网重跑实测，755 行）**：描述空 95%→20%、系统名换行脏键 163→0、
valid 104→184，萃取质量大幅提升。唯一尾巴：UNKNOWN 341 条里 **190 条信息齐全
（有描述/定位）只是错挂 UNKNOWN，151 条为真·"经核查无异常"噪声**。

**决策：UNKNOWN 保留原样，不自动补类。** 按关键词猜类别，等于把诚实的"不确定"
改写成自信的错误标签，还会悄悄污染 Stage 2 聚类与评估 ground truth（错标"看起来
已归类"反而不易被揪出），风险大于收益——与计划 3.1「plausible-but-wrong 比没有
结论更危险」一致。UNKNOWN 是给人看的诚实招牌，保留它；用**排序**让人工高效，而非
替模型下判断。

**复核队列排序口径（只排序，绝不改类别、不替模型猜）：**

| 优先级 | 条件 | 含义 / 处理 |
|--------|------|------------|
| **P0 高** | `类别=UNKNOWN` 且 (`描述` 或 `定位对象` 非空) | 信息齐全、错挂 UNKNOWN，人工一眼可改对（约 190 条） |
| **P1 中** | `低置信=true` / `有效性` 与 `is_invalid_flag` 冲突 / 系统名 `resolve_system().resolved=False` | 需核对 |
| **P2 低（可跳过）** | `类别=UNKNOWN` 且 描述+定位皆空 且 `有效性=invalid` | 真·无异常噪声（约 151 条） |

其余（已归类、非低置信、系统名已入词表）默认免审。信号字段都在
`原始._kp_meta`，队列可先用脚本导 CSV，前端是它以后的皮肤。

**关联的 prompt 软化（留待下次自然重跑，不专门重跑）**：把「能写描述就必须归类」
软化为「根因明确时务必归类，**仅在类别确实模糊或无根因时**才用 UNKNOWN」——修好
明显误挂的，同时保住真不确定时的诚实（避免把"自信错误"从代码侧搬到萃取侧）。

## 四、验证记录（2026-07-02，公网 qwen3.7-plus 替代端点）

- Stage 1：50/50 行成功（含 4 行 xlsx 截断行降级处理）。
- Stage 2：5 条候选模式（RELEASE 19 例 / DB 13 例 / APP 7 例 / NOISE 3 例 / HOST 3 例），
  全部通过现有 `load_library` 回读校验，零告警。
- 内网迁移只需换 `.env` 三行，prompt 与代码不动（同为 qwen 系模型，效果可比性好）。
