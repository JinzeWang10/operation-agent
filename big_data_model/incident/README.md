# Incident 模块架构

`big_data_model/incident/` 把"一份监控聚合快照"加工成两件人类可消费的产物：

- 一段 ≤500 字的中文**现象简报**（`incident_brief.txt`）
- 一张统一风格的**事件会诊速览**（`incident_report.png`）

整个模块严格遵守 **抽取 / 解读 / 渲染** 三层分离——三层互不耦合，可以独立替换或单测。渲染层采用 HTML + 无头 Chromium：ViewModel → Jinja 模板 → CSS → Playwright 截图。

---

## 一、流水线总览

```
text.txt（监控聚合器返回的原始 JSON 文本）
   │  ast.literal_eval
   ▼
extract(payload) ─────────► FeatureBag           [features.py]
   │
   ├── bag.to_llm_brief() ─► summarize(brief) ──► incident_brief.txt   [summarizer.py]
   │                                │
   │                                └── (作为 brief_text 传入下一步)
   │
   └── render_dashboard(bag, png_path, brief_text) ─► incident_report.png   [render/dashboard.py]
        │
        ├── build_view_model(...) ─► DashboardVM       [render/prepare.py]
        ├── render_bpc_svg(bag)    ─► <svg>...</svg>   [render/charts.py]
        ├── Jinja(dashboard.html.j2 + dashboard.css)   [render/templates, render/static]
        └── html_to_png(html, png) ─► PNG via Playwright [render/png.py]
```

入口编排在 `render_report.py`，全文不到 40 行——它只负责"读 → 抽特征 → 调 LLM → 画图"四步串接，不含业务逻辑。

---

## 二、模块布局

```
big_data_model/incident/
├── __init__.py        # 仅 re-export FeatureBag, extract
├── features.py        # 第 1 层：确定性特征抽取（无 LLM）
├── summarizer.py      # 第 2 层：LLM 现象简报
├── render/            # 第 3 层：会诊速览渲染（HTML + 无头 Chromium）
│   ├── dashboard.py        # 总入口：FeatureBag → HTML → PNG
│   ├── prepare.py          # ViewModel 构建（所有形状决策集中在此层）
│   ├── charts.py           # BPC 4 联图渲染为 SVG（matplotlib 输出 svg 字符串）
│   ├── png.py              # Playwright html → png
│   ├── templates/          # Jinja 模板（dashboard.html.j2、各区块片段）
│   └── static/dashboard.css
├── context.py         # 关联上下文 sidecar（ITSM 事件单 + 变更/升级），透传不入 LLM
├── render_report.py   # 端到端入口：python -m big_data_model.incident.render_report
├── sample/
│   ├── text.txt              # 监控聚合器返回的原始 JSON 样本
│   └── related_context.json  # 关联事件单/变更升级 sidecar 样本
└── output/            # 运行产物（自动创建）
    ├── incident_brief.txt
    └── incident_report.png
```

三层之间依赖方向单向：`render/` 与 `summarizer.py` 都依赖 `features.py`，但彼此互不依赖。

---

## 三、第 1 层：`features.py` —— 特征抽取

把一份原始监控 JSON 解析成强类型的 `FeatureBag`。这是整个模块**唯一**接触原始数据形状的地方，下游永远只读 dataclass。

### 设计原则

1. **Lossless（无损）**——每个监控块的原 JSON 都保留在对应 dataclass 的 `raw_block` 字段中，下游可回查。
2. **Tri-state per monitor（每监控四态）**——每个监控可能处于：
   - `present-with-data`：成功并有数据 → 结构化 dataclass
   - `present-but-empty`：成功但空数据
   - `interface_failed`：接口失败（`code == "-1"`）→ `MissingSignal(reason="interface_failed")`
   - `absent`：根本没出现 → `unknown_monitors` 或字段为 `None`
   下游消费者必须显式处理四种状态。
3. **派生视图叠加（additive）**——percentile、Top-N、子网 cohort、breach cluster、严重度评分都是**在原始值之上新增字段**，从不替换。

### 调度方式

文件末尾两张表决定每个监控块的归宿：

```python
_STRUCTURED_DISPATCH = {
    "BPC监控":              ("bpc",          _extract_bpc),
    "PROMETHEUS应用拨测结果": ("probe",        _extract_probe),
    "组件状态指标":           ("components",   _extract_components),
    "日志关键字指标":         ("log_keywords", _extract_log_keywords),
    "南中心告警":             ("south_center", _extract_south_center),
    "设备-主机":              ("hosts",        _extract_hosts),
    "设备-数据库":            ("databases",    _extract_databases),
}

_MISSING_DISPATCH    = {"调用链指标": "call_chain", "变更单信息": "change_orders", "升级单信息": "upgrade_orders"}
_TEXT_NOTE_DISPATCH  = {"单客户端异常访问分析": "single_client_analysis"}
```

新增监控类型 = 加一行 dispatch + 写一个 `_extract_*`，无需改其他地方。

### 跨监控合成 `_build_cross()`

每路监控独立抽取后，`_build_cross()` 做一次跨信号汇总：

- `snapshot_time`：优先取 BPC 时点的最大值，否则用 payload 的 `timestamp_iso`
- `monitors_anomalous / normal / failed / empty`：监控分桶
- `timeline_anchors`：BPC spike + 主机活跃告警的时间锚点
- `spatial_cohorts`：高负载 /24 子网 cohort
- `top_anomalies`：按 `severity` 倒序、跨监控混合排序的前 10 条异常

### 给 LLM 用的瘦视图 `to_llm_brief()`

把 `FeatureBag` 压缩成纯 dict：保留数值、时间、主机/子网，去掉 `raw_block` 等冗余结构。LLM 与图表共享这同一份 brief 视图，**保证文字与图反映的是同一份事实**。

---

## 四、第 2 层：`summarizer.py` —— LLM 现象简报

唯一调用 LLM 的地方。

### 系统提示的"四条铁律"

- 只陈述快照里的事实，不做根因推测、不给处置建议
- 接口失败 / 空数据的部分简短一句话说明"该信号不可用"，不绕开也不补脑
- 引用具体数值、时间、主机/子网，让人能回 JSON 核对
- 现象稀疏就稀疏写，不为凑字重复或扩写

### 工作方式

```python
brief = bag.to_llm_brief()                    # dict
text  = await summarize(brief)                # ≤500 字中文
```

把 `to_llm_brief()` 直接 `json.dumps` 塞进 user message，调 `big_data_model.llm.client.LLMClient`，输出纯文本中文段落。`Settings` 可注入以便测试。

---

## 五、第 3 层：`render/` —— 会诊速览渲染（HTML + Chromium）

渲染层不直接画 PNG，而是先把 `FeatureBag` 转成纯数据 ViewModel，再交给 Jinja 模板渲染 HTML，最后用无头 Chromium 截图。这样**所有"形状决策"（截断、escape、分类色）集中在 `prepare.py`，模板里零业务逻辑**。

### 渲染流水线

```
FeatureBag
   │
   ├── build_view_model(...)   ─► DashboardVM (BriefVM + BannerVM + BpcVM + HostTableVM + RelatedVM)   [prepare.py]
   ├── render_bpc_svg(bag)     ─► 直接嵌入 HTML 的 <svg>                                              [render/charts.py]
   │
   ▼
Jinja(dashboard.html.j2) + dashboard.css                                                              [templates/, static/]
   │
   ▼
html_to_png(html)                                                                                     [png.py, Playwright]
   │
   ▼
incident_report.png
```

### 速览布局（自上而下，由模板决定，自适应）

| 区块 | 出现条件 | 内容 |
|------|----------|------|
| 标题栏 | 总是 | 事件 ID + 快照时间 |
| 疑似根因 banner | 有核保规则发布时 | 红底高亮，1~N 条规则 |
| 现象简报 + 关联上下文 | 简报有内容时 | 左 6：LLM 简报（按 `## 标题` 切小节）；右 4：ITSM 事件单 + 变更升级双列 |
| BPC 监控 | 本次有 BPC 数据 | 4 联图 SVG（trans_count / succ_rate / duration / rr_rate）由 `render/charts.py` 渲染 |
| 告警主机概览 | 本次有主机数据 | 告警主机置顶（红行底色 + 红 IP + 橙色告警文本），其余按 `CPU+IOwait` 排序，Top 20 |

### 视觉规则

- 深色调色板（`#0d1117` / `#161b22` 面板，`#e6edf3` 文本），定义在 `dashboard.css`
- 中文字体链：`SimHei` → `Microsoft YaHei` → `sans-serif`
- BPC `duration` 偏离基线 ≥2× → 峰值红色高亮 + 数值标注（在 `render/charts.py` 内）
- BPC `succ_rate` / `rr_rate` 跌幅触发阈值 → 谷值橙色高亮
- 主机表 breach 条件（`HOST_THRESHOLDS`）：CPU > 80%、内存 > 85%、IOwait > 30%、磁盘 > 80%，超阈值单元格红色加粗

### 降级行为

`bag.bpc` / `bag.hosts` / `related` / `release_rules` 缺失时，对应区块**整块消失**（不渲染空占位）。这是 tri-state 设计在渲染层的体现：空数据时占位文字反而干扰阅读。模板里所有区块都有 `{% if vm.present %}` 包裹。

---

## 六、为什么这样分层

| 关切 | 由谁负责 |
|------|----------|
| 数据形状变化（监控字段改名、新增监控类型） | 仅 `features.py` 的 dispatch 表和 `_extract_*` |
| 简报口吻、详略、语种调整 | 仅 `summarizer.py` 的 system prompt |
| 截断/排序/分类色等"形状决策" | 仅 `render/prepare.py` |
| 配色、字体、间距等纯视觉 | 仅 `render/static/dashboard.css` |
| 排版（区块顺序、栅格） | 仅 `render/templates/*.html.j2` |
| 同一份事实跨"图"和"文"保持一致 | 共享 `FeatureBag` / `to_llm_brief()` |
| "看不到"也能被忠实呈现 | `MissingSignal` 一等公民 + 模板 `{% if vm.present %}` |

---

## 七、关联上下文 sidecar

ITSM 事件单（INM）与变更/升级（CHM/DRM）来自与监控聚合器**完全不同**的上游系统，因此走独立通路：

- 输入：`sample/related_context.json`（schema 见 `context.py` 的三个 dataclass）
- 加载：`load_related_context(path)` → `RelatedContext`，文件不存在返回 `None`
- 注入点：`render_dashboard(..., related=ctx)`——**不进入 `FeatureBag`、不进入 `to_llm_brief`**
- 渲染：底部双列文字面板，仅展示传入的内容（不做时间窗过滤、不做关联推断）

设计取舍：LLM 简报**不引用**关联上下文，避免它在没有因果证据时把"前 4 小时有变更"写成"由变更引起"。这部分信息仅作为人工研判的对照材料原样呈现。

---

## 八、扩展指引

- **新增一类监控**：在 `_STRUCTURED_DISPATCH` 加一行 → 写 dataclass 与 `_extract_*` → 如需进入 LLM 视图，在 `_build_llm_brief()` 加分支 → 如需可视化，在 `render/prepare.py` 加 ViewModel 字段，配套 `render/templates/` 加片段、`dashboard.css` 加样式。
- **改简报风格**：只改 `summarizer.py` 的 `SYSTEM_PROMPT`。
- **改主机表阈值、排序、截断数**：只动 `render/prepare.py`（阈值在 `features.HOST_THRESHOLDS`）。
- **改配色、字号、间距**：只动 `render/static/dashboard.css`。
- **替换渲染后端**（如换成 PDF）：保留 `prepare.py` 与模板，改 `png.py` 的输出端即可。
