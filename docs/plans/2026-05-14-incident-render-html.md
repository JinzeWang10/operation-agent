# 事件会诊速览渲染管线改造：matplotlib → HTML/Playwright

日期：2026-05-14
作者：JinzeWang10
状态：设计已确认，待实施

---

## 一、背景与动机

当前 `app/incident/charts.py` 用 matplotlib 直接绘制最终 PNG。在数据形状稳定时表现良好，但对"异常数据"非常脆弱，根因是 matplotlib 的画布是**先定大小后填内容**——必须在 Python 端预先估算每个面板的英寸高度。

### 当前已知脆弱点

1. **主机表绝对列坐标**（`_TABLE_COLUMNS` x=0.04/0.26/0.36…）：IP 变长（IPv6）或数值变宽，会压到下一列。
2. **Banner 单行不换行**：`rrf.rules[0]` 直接 `ax.text`，规则名稍长就跑出红框；多条规则被 cap 在 3.5 寸高，再多就互相挤压。
3. **Brief panel 高度估算公式失准**：`brief_h = 0.42 * lines + 1.8`，LLM 多写两段或出现长 URL 时 `_wrap_cjk` 退化。
4. **side-by-side 等高错配**：brief 与 related 一侧 2 段一侧 8 条变更，另一侧大片空白或被强制拉伸。
5. **静默截断**：alarm 名 >22 字硬切、主机 top 12、BPC 系统名 >3 个变"等"——异常场景下被藏掉的往往才是关键。
6. **BPC 子图 x 轴时间标签密集时重叠**。

### 改造目标

- 维持产物形态：仍输出单张 PNG（消费端零改动）。
- 把"文字面板、表格、Banner"这类排版敏感部分交给浏览器流式排版，从根上消除 1-5 号脆弱点。
- 把"曲线"这种 matplotlib 擅长的部分保留下来，以 SVG 嵌入 HTML，复用已有绘制逻辑。
- 截断改为**显式协议**——加 `+N more` 提示，用户知道有数据被藏起来。

---

## 二、技术栈选型

| 维度 | 选定方案 | 理由 |
|---|---|---|
| 输出格式 | PNG（保持不变） | 消费场景未变，分发渠道是 IM/工单截图。 |
| 渲染引擎 | Playwright (Chromium) | 现代 CSS（grid/flex）支持完整；中文字体、SVG 无障碍；调试时能直接看 HTML。 |
| 图表 | matplotlib → SVG 嵌入 HTML | 保留现有 BPC 曲线逻辑（峰值高亮、阈值高亮等），改动量最小。 |
| 模板 | Jinja2 模板文件 | HTML/CSS 与 Python 逻辑分离；调样式时可独立预览模板。 |
| 中文字体 | 系统 SimHei | 系统已自带，无需打包字体或 `@font-face`。 |

### 新增依赖

```
playwright >= 1.40
jinja2 >= 3.1
```

`playwright install chromium` 为一次性部署操作（~150MB）。CI 缓存 `~/.cache/ms-playwright`。

---

## 三、模块布局

```
app/incident/
├── features.py / summarizer.py / context.py    # 不动
├── render_report.py                            # 入口：替换调用点
├── charts.py                                   # 旧版保留（迁移期 fallback）
└── render/                                     # 新子包
    ├── __init__.py
    ├── dashboard.py        # render_dashboard(bag, brief, related, out) 总入口
    ├── prepare.py          # FeatureBag → ViewModel（截断/escape/分词集中）
    ├── charts.py           # matplotlib → SVG 字符串（仅 BPC 4 联图）
    ├── png.py              # Playwright: HTML → PNG
    ├── templates/
    │   ├── dashboard.html.j2   # 顶层骨架
    │   ├── brief.html.j2
    │   ├── related.html.j2
    │   ├── banner.html.j2
    │   ├── bpc.html.j2         # 嵌入 SVG
    │   └── hosts.html.j2
    └── static/
        └── dashboard.css       # 单一样式表，深色调色板
```

模块依赖方向单向：`prepare` 与 `charts` 都只依赖 `features`，互不依赖；`dashboard` 依赖三者并组装。

---

## 四、数据流

```
FeatureBag + brief_text + related
   ├─► prepare.build_view_model()  ──► ViewModel（dataclass）
   ├─► charts.render_bpc_svgs()    ──► dict[name, svg_str]
   ▼
Jinja2(dashboard.html.j2, vm, svgs) ──► html_str
   ▼
Playwright.screenshot(html_str, full_page=True) ──► incident_report.png
```

**关键架构选择**：新增 `prepare.py` 一层，把所有"形状决策"（截断、escape、行内分词、超长拆行）集中在此。模板里**零业务逻辑**——只摆位。

Python 端不再估算高度。浏览器排完版后自己知道页面真实高度，`page.screenshot(full_page=True)` 按真实高度截图。这是 HTML 方案最大的红利：**永远不会"画布不够大"**。

---

## 五、CSS 布局策略

固定外框 `width: 1280px`，高度由浏览器流式决定。

### 顶层骨架

```css
.dashboard {
  width: 1280px;
  padding: 24px;
  background: #0d1117;
  color: #e6edf3;
  font-family: "SimHei", "Microsoft YaHei", sans-serif;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.top { display: grid; grid-template-columns: 6fr 4fr; gap: 12px; align-items: stretch; }
.top.solo { grid-template-columns: 1fr; }  /* related 缺失时自动单列，等高问题消失 */
```

### 主机表（解决当前最脆弱的部分）

```html
<table class="hosts">
  <colgroup>
    <col class="ip"><col class="cpu"><col class="mem">
    <col class="iow"><col class="disk"><col class="days"><col class="alarm">
  </colgroup>
  ...
</table>
```

```css
.hosts { table-layout: fixed; width: 100%; }
.hosts col.ip    { width: 18%; }
.hosts col.cpu, col.mem, col.iow, col.disk, col.days { width: 9%; }
.hosts col.alarm { width: 28%; }

.hosts td.ip    { font-family: monospace; word-break: break-all; }  /* IPv6 自动折行 */
.hosts td.alarm { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hosts td.breach { color: #f85149; font-weight: bold; }
```

### Banner（多规则自然撑开）

```css
.banner ul li { line-height: 1.6; word-break: break-word; }
```

5 条规则就 5 行，每条超长自动换行——不再被 cap 3.5 寸压扁。

### Brief 文本（高亮规则由 CSS 而非 Python 决定）

模板渲染：
```html
{% for seg in vm.brief.segments %}<span class="hl-{{seg.kind}}">{{seg.text}}</span>{% endfor %}
```

```css
.brief p { word-break: break-word; line-height: 1.9; }
.hl-ms   { color: #fb8500; font-weight: bold; }
.hl-pct  { color: #d29922; font-weight: bold; }
.hl-time { color: #39c5cf; font-weight: bold; }
.hl-ip   { color: #bc8cff; font-weight: bold; }
.hl-dev  { color: #f85149; font-weight: bold; }
```

### 截断协议（显式 +N more）

模板尾部统一：
```html
{% if vm.hosts.truncated_count %}
  <tr class="more"><td colspan="7">
    +{{ vm.hosts.truncated_count }} 台超阈值主机未展示（共 {{ vm.hosts.total_count }} 台）
  </td></tr>
{% endif %}
```

### 决策：保留硬截断阈值（方案 A）

- 主机表 ≤12
- Banner 规则不截（自然撑开）
- Alarm 名保留 ellipsis（CSS 原生 `text-overflow`，不再字符 `[:21]`）
- Related 列表按现状

异常场景下 IM 里的 PNG 长度可控；被藏掉的数据通过 `+N more` 提示。

---

## 六、ViewModel（`prepare.py`）

集中处理所有"形状决策"。模板只取字段。

```python
@dataclass
class BriefSegment:
    text: str
    kind: str  # "plain" | "ms" | "pct" | "time" | "ip" | "dev"

@dataclass
class BriefVM:
    segments: list[BriefSegment]            # 已分词、已 escape
    monitor_summary: dict | None

@dataclass
class HostRowVM:
    ip: str
    cpu_pct: float;  cpu_breach: bool
    mem_pct: float;  mem_breach: bool
    iow_pct: float;  iow_breach: bool
    disk_pct: float; disk_breach: bool
    days: int
    alarm_text: str           # 不再 [:21]，CSS 自己 ellipsis
    is_alarming: bool

@dataclass
class HostTableVM:
    rows: list[HostRowVM]     # 已按 severity 排序，已截断
    truncated_count: int
    total_count: int
    breach_total: int

@dataclass
class BannerVM:
    present: bool
    rules: list[str]          # 不截断

@dataclass
class RelatedItemVM:
    severity_or_type: str
    color_kind: str           # CSS class hint
    ticket_id: str
    body: str
    time_range: str | None

@dataclass
class DashboardVM:
    title: str
    snapshot_time: str
    brief: BriefVM | None
    banner: BannerVM
    hosts: HostTableVM
    incidents: list[RelatedItemVM]
    changes: list[RelatedItemVM]
```

`build_view_model(bag, brief_text, related) -> DashboardVM` 是入口。

复用现有代码：`_split_brief_segments`、`_host_severity`、`_TABLE_COLUMNS` 的阈值判断、`_bpc_subtitle` 等纯逻辑搬过来即可。

---

## 七、Playwright 集成（`png.py`）

```python
from playwright.async_api import async_playwright

async def html_to_png(html: str, out: Path, width: int = 1280) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(
                viewport={"width": width, "height": 800},
                device_scale_factor=2,   # 2x DPI → IM 缩略图后仍清晰
            )
            await page.set_content(html, wait_until="load")
            await page.screenshot(path=out, full_page=True, type="png")
        finally:
            await browser.close()
```

`device_scale_factor=2` 是关键——微信/钉钉缩略图压缩较狠，1x 中文容易糊。

---

## 八、测试

```
tests/
├── test_prepare.py        # ViewModel 单元测试
│   - 50 台告警主机 → truncated_count = 38
│   - alarm 含 <script> → segments 中无原始尖括号
│   - brief 含长 URL → 分词不破坏
│   - banner 20 条规则 → 全量保留
│   - IPv6 主机 → ip 字段原样保留
├── test_render_html.py    # Jinja 渲染：HTML 文本 snapshot
└── test_render_e2e.py     # 端到端：sample/text.txt → PNG 非空、宽度 == 2560
```

视觉回归用 **HTML 文本 snapshot**，不用像素级比对（字体微调即失效）。

---

## 九、迁移路径

1. 新代码全部进 `render/` 子包，**不动**旧 `charts.py`。
2. `render_report.py` 加 `--engine html|matplotlib` 开关，默认仍走 matplotlib。
3. 平行运行一周：sample 数据 + 真实事件双 PNG 人工对照。
4. 验稳后默认值切到 `html`，再过一周删 `charts.py` 与依赖。

回滚预案：开关切回 `matplotlib` 即可，零成本。

---

## 十、待调样式（首版对照后清单）

首版生成的 HTML PNG 与旧版 matplotlib PNG 并排对照（sample 数据），核心功能等价，
以下细节待人工反馈后调整：

- 顶部标题字号 26px 比旧版 (matplotlib `suptitle fontsize=26` 实际更大) 视觉偏小，
  考虑加大到 28-30px 或加重 letter-spacing。
- BPC SVG 容器内 `width:100% height:auto` 导致 4 联图整体偏矮（旧版 16in×7in，
  新版 14in×5.2in），可调 figsize 或固定 svg height。
- Related 双栏堆叠后第一条事件单 [严重] tag 颜色仅文字色，旧版有更醒目的填色 chip——
  若改 tag 风格为 `background-color + 浅文字色` 视觉更平衡。
- 主机表 alarm 列默认值 `—` 在大量 RGB 色块行间略平淡，可加 `.alarm-empty` 类弱化。
- BPC 子图标题字号偏小（fontsize=12），高密度数据时不够醒目。

这些调整不在 §九 迁移路径的关键路径上，可在切默认 engine 前依据线上反馈逐项处理。

---

## 十一、不在本次范围内（YAGNI）

- 不做交互式 HTML（hover tooltip、可点击链接）——产物仍是 PNG。
- 不替换 BPC 图绘制库——matplotlib SVG 足够。
- 不引入 CSS 框架（Tailwind 等）——单一手写样式表足以覆盖。
- 不做响应式（多分辨率自适应）——固定 1280px。
- 不改 `FeatureBag` 与 LLM 简报内容——本次只换渲染层。
