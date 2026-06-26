# 事件会诊速览 — 内网部署说明

会诊速览的排版由 HTML + 无头 Chromium 渲染：`features.py` 抽特征 → `render/prepare.py` 构 ViewModel → Jinja 模板 + CSS → Playwright 截图为 PNG。

本文说明从零部署所需的全部改动和验证步骤。

---

## 一、需要新装的东西

| 项目 | 用途 | 大小 |
|------|------|------|
| `jinja2 >= 3.1` | HTML 模板渲染（纯 Python） | <1MB |
| `playwright >= 1.40` | 控制无头浏览器的 Python SDK | ~40MB |
| Chromium 浏览器 | 把 HTML 渲染成 PNG | ~150MB |
| `matplotlib >= 3.7` | BPC 4 联图渲染为 SVG（HTML 内联） | ~50MB |
| Linux 系统库 | Chromium 运行依赖（libnss3 等） | 视发行版 |
| 中文字体（SimHei 或等价） | 中文渲染 | — |

---

## 二、部署步骤

### 1. 拉代码

```bash
git pull        # 或把整个 big_data_model/incident/ 目录覆盖
```

### 2. 装 Python 包

```bash
pip install -r big_data_model/incident/requirements.txt
```

### 3. 装 Chromium

```bash
python -m playwright install chromium
```

**内网拉不动 Microsoft CDN 时的两条路：**

**A. 代理**

```bash
export HTTPS_PROXY=http://proxy.intra:port
python -m playwright install chromium
```

**B. 离线拷贝**

在能联网的机器上跑完 `playwright install chromium`，然后把这个目录整体拷到部署机：

```bash
# 源机器：默认路径
~/.cache/ms-playwright/

# 部署机：放到任意位置（例如 /opt）并设环境变量
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
```

`PLAYWRIGHT_BROWSERS_PATH` 必须对运行 Python 的进程可见，建议写进系统 profile 或服务的 env 配置。

### 4. 装系统库（Linux）

Chromium 在 Linux 上依赖 GUI 相关动态库。Playwright 自带安装脚本：

```bash
sudo python -m playwright install-deps chromium
```

没 sudo 权限的话让运维装下面这套包（Debian/Ubuntu 包名）：

```
libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0
libcups2 libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1
libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
```

RHEL/CentOS 系包名略不同，运维通常知道对应关系；或者跑 `playwright install-deps` 让它告诉你缺什么。

### 5. 中文字体

```bash
fc-list :lang=zh | grep -iE 'sim|noto'
```

有 SimHei 或 Noto Sans CJK 任一输出即可——`dashboard.css` 的字体链是：

```
font-family: "SimHei", "Microsoft YaHei", sans-serif;
```

如果两个都没有：
- 让运维装：`apt install fonts-noto-cjk` 或 `yum install google-noto-sans-cjk-fonts`
- 或把 `SimHei.ttf` 拷到 `/usr/share/fonts/`，再 `fc-cache -fv`
- 或修改 `big_data_model/incident/render/static/dashboard.css` 的 `font-family` 链，把目标机器实际有的字体加进去

---

## 三、验证

### 1. 字体探针

```bash
python -m big_data_model.incident.render._probe_font
```

打开 `big_data_model/incident/output/_probe_font.png`：应能看到清晰的中文「事件会诊速览 · 中文字体探针」+ 橙/黄色高亮 span，**没有方框**。看到方框就是字体未生效，回到 §2.5 解决。

### 2. 端到端跑一次

```bash
python -m big_data_model.incident.render_report
```

产物：
- `big_data_model/incident/output/incident_brief.txt` — LLM 生成的现象简报（≤500 字，按 `## 标题` 分小节）
- `big_data_model/incident/output/incident_report.png` — 最终会诊速览图

如果 LLM 接口失败或返回"模型存在问题"，**PNG 仍能正常出图**，简报区会显示降级提示「Qwen 大模型接口异常，暂无法生成现象简报」。其他区块（疑似根因、BPC 图、主机表、关联上下文）不受 LLM 影响。

---

## 四、常见故障

| 错误关键字 | 含义 | 处置 |
|---|---|---|
| `Executable doesn't exist at .../chrome-XXX/chrome` | Chromium 没装好或路径找不到 | 跑 `playwright install chromium`，离线模式确认 `PLAYWRIGHT_BROWSERS_PATH` 设对 |
| `error while loading shared libraries: libnss3.so` | Linux GUI 库缺 | `playwright install-deps chromium` 或让运维装 §2.4 列表 |
| 截图里中文是方框 | 系统没中文字体 | `fc-list :lang=zh` 检查；装 fonts-noto-cjk 或拷 SimHei |
| `Page crashed` / 启动卡住 | root 用户跑或容器里沙箱不可用 | 在 `big_data_model/incident/render/png.py` 的 `chromium.launch()` 加 `args=["--no-sandbox"]`（仅在受信环境用） |
| `asyncio.run() cannot be called from a running event loop` | 在已有 async 上下文里又调 `asyncio.run` | 直接 `await render_dashboard(...)` 而非 `asyncio.run(...)` |
| 简报里出现 `[LLM_ERROR]` | LLM 接口异常被降级 | 这是预期行为，不是 bug；检查 LLM 服务状态 |

---

## 五、关于"看不到 BPC / 主机表 / 关联事件" 的情况

布局是**自适应**的：

- BPC 监控本次没数据 → BPC 4 联图区域完全消失，brief 直接接到主机表
- 主机数据缺失 → 主机表区块消失
- 无关联事件单/变更 → 右侧关联区消失，brief 改为整宽单列
- 无核保规则发布 → 顶部红 banner 消失
- LLM 失败 → brief 显示降级文案，其他区块照常

这是 by design，**不是 bug**——空数据时占位文字反而干扰阅读。如果某次出图明显比预期短/少东西，先查输入的 `sample/text.txt`（或线上 sampler 的产物）是否包含对应监控块。
