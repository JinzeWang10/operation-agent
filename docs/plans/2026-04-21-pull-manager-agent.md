# Pull Manager Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建一个单轮 agent，输入自然语言（如"请拉Linux操作系统和GaussDB的运维经理"），解析后调用 `add_sys_manager_to_chat(system_name, manager_type)` 接口把对应人员拉入群。

**Architecture:** 单次 LLM 调用完成 NLU。主入口 `handle_message(text) -> dict` 按顺序执行：加载资产清单 → 构建 prompt → 调 LLM → 解析 JSON → 循环调接口 → 汇总返回。每模块独立可 mock，便于单测；另加少量真调 LLM 的端到端测试。

**Tech Stack:** Python 3.11+，复用 `app/llm/client.py` 的 `LLMClient`（OpenAI 兼容，已配 `.env`），pytest + pytest-asyncio，stdlib `json` / `logging`。

---

## 目录结构

```
app/
  pull_agent/
    __init__.py
    assets.py         # 写死的资产清单 + loader
    prompt.py         # prompt 模板 + 构建函数
    parser.py         # JSON 解析 + schema 校验
    chat_client.py    # add_sys_manager_to_chat 的包装（stub 先）
    agent.py          # handle_message 主入口
tests/
  pull_agent/
    __init__.py
    test_assets.py
    test_prompt.py
    test_parser.py
    test_chat_client.py
    test_agent.py             # 用 mock LLM 的单测
    test_agent_e2e.py         # 真调 LLM 的端到端
```

---

## Task 1: 资产清单模块

**Files:**
- Create: `app/pull_agent/__init__.py`
- Create: `app/pull_agent/assets.py`
- Test: `tests/pull_agent/__init__.py`, `tests/pull_agent/test_assets.py`

**Step 1: 写失败测试**

```python
# tests/pull_agent/test_assets.py
from app.pull_agent.assets import load_assets, MANAGER_TYPES

def test_load_assets_returns_nonempty_list():
    assets = load_assets()
    assert isinstance(assets, list)
    assert len(assets) >= 20
    assert "Linux操作系统" in assets
    assert "GaussDB" in assets

def test_manager_types():
    assert MANAGER_TYPES == ["运维经理", "开发经理"]
```

**Step 2: 跑测试确认失败**

Run: `pytest tests/pull_agent/test_assets.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: 实现**

```python
# app/pull_agent/assets.py
ASSETS = [
    "智家服务管理系统", "智能合规双录平台", "智能化打印PageOn系统",
    "智能客服系统", "智能培训效果评估系统", "智能识别",
    "智能医疗审核系统", "智能营销", "智能中心",
    "AIX操作系统", "Linux操作系统", "Windows操作系统",
    "SinoDB", "OracleDB", "GaussDB", "PG数据库系统",
    "SVC存储虚拟化", "LinuxONE软件", "Gbase数据库系统", "OceanBase-PAAS",
]

MANAGER_TYPES = ["运维经理", "开发经理"]

def load_assets() -> list[str]:
    return list(ASSETS)
```

**Step 4: 跑测试确认通过**

Run: `pytest tests/pull_agent/test_assets.py -v`
Expected: PASS

**Step 5: 提交**

```bash
git add app/pull_agent/__init__.py app/pull_agent/assets.py tests/pull_agent/
git commit -m "feat(pull_agent): add asset and manager type registry"
```

---

## Task 2: Prompt 构建模块

**Files:**
- Create: `app/pull_agent/prompt.py`
- Test: `tests/pull_agent/test_prompt.py`

**Step 1: 写失败测试**

```python
# tests/pull_agent/test_prompt.py
from app.pull_agent.prompt import build_prompt

def test_build_prompt_contains_all_sections():
    msgs = build_prompt("拉Linux的运维经理", ["Linux操作系统", "GaussDB"])
    assert isinstance(msgs, list)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    sys = msgs[0]["content"]
    assert "Linux操作系统" in sys
    assert "GaussDB" in sys
    assert "运维经理" in sys
    assert "开发经理" in sys
    assert "status" in sys  # 输出格式说明
    assert msgs[1]["content"] == "拉Linux的运维经理"
```

**Step 2: 跑测试确认失败**

Run: `pytest tests/pull_agent/test_prompt.py -v`

**Step 3: 实现**

```python
# app/pull_agent/prompt.py
SYSTEM_TEMPLATE = """你是运维拉群助手。从用户消息中识别需要拉进群的 (资产, 岗位) 对，输出结构化 JSON。

<可选资产>
{assets}
</可选资产>

<可选岗位>
运维经理
开发经理
</可选岗位>

<规则>
1. 资产名必须严格来自 <可选资产> 清单，输出时使用清单里的完整名称。
2. 资产模糊匹配：用户用简称、俗称、口误时做映射。
   - "Linux" → "Linux操作系统"
   - "高斯" / "高斯DB" → "GaussDB"
   - "客服系统" → "智能客服系统"
3. 岗位判定：
   - 明确说"运维经理" → 运维经理
   - 明确说"开发经理" → 开发经理
   - 未指明岗位，或用"负责人/接口人/相关同事/人"等模糊词 → 运维经理 + 开发经理 都拉
4. 共享修饰语要分发到多条：
   - "Linux和Windows的运维经理" → 两条，岗位都是运维经理
   - "Linux的运维和开发经理" → 两条，资产都是Linux操作系统
5. 资产无法识别时（清单里找不到、或泛指词对应多个候选如"数据库经理"）：
   - 不要猜、不要反问、不要列候选
   - 直接在 unresolved 中记录原文
6. 一条消息可能部分能识别、部分不能，把能识别的放 actions，剩下放 unresolved。
</规则>

<输出格式>
只输出 JSON，不要任何解释文字、不要 markdown 代码块。

全部成功：
{{"status":"ok","actions":[{{"asset":"Linux操作系统","role":"运维经理"}}]}}

部分成功：
{{"status":"partial","actions":[...],"unresolved":["数据库经理"],"message":"..."}}

全部失败：
{{"status":"failed","actions":[],"unresolved":["..."],"message":"无法确认资产名称，请明确指出系统名称，或手动拉取相关人员。"}}
</输出格式>

<示例>
用户：请拉Linux操作系统和GaussDB的运维经理
输出：{{"status":"ok","actions":[{{"asset":"Linux操作系统","role":"运维经理"}},{{"asset":"GaussDB","role":"运维经理"}}]}}

用户：把智能客服系统的人都拉进来
输出：{{"status":"ok","actions":[{{"asset":"智能客服系统","role":"运维经理"}},{{"asset":"智能客服系统","role":"开发经理"}}]}}

用户：拉一下高斯的开发
输出：{{"status":"ok","actions":[{{"asset":"GaussDB","role":"开发经理"}}]}}

用户：拉个DBA过来
输出：{{"status":"failed","actions":[],"unresolved":["DBA"],"message":"无法确认资产名称，请明确指出系统名称，或手动拉取相关人员。"}}
</示例>"""


def build_prompt(user_input: str, assets: list[str]) -> list[dict]:
    system = SYSTEM_TEMPLATE.format(assets="\n".join(assets))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_input},
    ]
```

**Step 4: 跑测试确认通过**

**Step 5: 提交**

```bash
git add app/pull_agent/prompt.py tests/pull_agent/test_prompt.py
git commit -m "feat(pull_agent): add prompt builder with rules and examples"
```

---

## Task 3: JSON 解析 + 校验

**Files:**
- Create: `app/pull_agent/parser.py`
- Test: `tests/pull_agent/test_parser.py`

**Step 1: 写失败测试**

```python
# tests/pull_agent/test_parser.py
import pytest
from app.pull_agent.parser import parse_llm_output, ParseError

ASSETS = ["Linux操作系统", "GaussDB"]

def test_parse_ok():
    raw = '{"status":"ok","actions":[{"asset":"Linux操作系统","role":"运维经理"}]}'
    result = parse_llm_output(raw, ASSETS)
    assert result["status"] == "ok"
    assert result["actions"] == [{"asset":"Linux操作系统","role":"运维经理"}]

def test_parse_failed():
    raw = '{"status":"failed","actions":[],"unresolved":["DBA"],"message":"x"}'
    result = parse_llm_output(raw, ASSETS)
    assert result["status"] == "failed"

def test_parse_partial():
    raw = '{"status":"partial","actions":[{"asset":"GaussDB","role":"开发经理"}],"unresolved":["X"],"message":"y"}'
    result = parse_llm_output(raw, ASSETS)
    assert result["status"] == "partial"
    assert len(result["actions"]) == 1

def test_parse_invalid_json():
    with pytest.raises(ParseError):
        parse_llm_output("not json", ASSETS)

def test_parse_unknown_asset_rejected():
    raw = '{"status":"ok","actions":[{"asset":"UnknownSys","role":"运维经理"}]}'
    with pytest.raises(ParseError):
        parse_llm_output(raw, ASSETS)

def test_parse_unknown_role_rejected():
    raw = '{"status":"ok","actions":[{"asset":"GaussDB","role":"CEO"}]}'
    with pytest.raises(ParseError):
        parse_llm_output(raw, ASSETS)

def test_parse_strips_code_fence():
    raw = '```json\n{"status":"ok","actions":[]}\n```'
    result = parse_llm_output(raw, ASSETS)
    assert result["status"] == "ok"
```

**Step 2: 跑测试确认失败**

**Step 3: 实现**

```python
# app/pull_agent/parser.py
import json
import re
from app.pull_agent.assets import MANAGER_TYPES


class ParseError(Exception):
    pass


_VALID_STATUS = {"ok", "partial", "failed"}


def parse_llm_output(raw: str, assets: list[str]) -> dict:
    text = raw.strip()
    # 兜底去 markdown code fence
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ParseError(f"no JSON object found in LLM output: {raw!r}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ParseError(f"invalid JSON: {e}") from e

    status = obj.get("status")
    if status not in _VALID_STATUS:
        raise ParseError(f"invalid status: {status!r}")

    actions = obj.get("actions", [])
    if not isinstance(actions, list):
        raise ParseError("actions must be a list")

    asset_set = set(assets)
    role_set = set(MANAGER_TYPES)
    for a in actions:
        if a.get("asset") not in asset_set:
            raise ParseError(f"unknown asset: {a.get('asset')!r}")
        if a.get("role") not in role_set:
            raise ParseError(f"unknown role: {a.get('role')!r}")

    return {
        "status": status,
        "actions": actions,
        "unresolved": obj.get("unresolved", []),
        "message": obj.get("message", ""),
    }
```

**Step 4: 跑测试确认通过**

**Step 5: 提交**

```bash
git add app/pull_agent/parser.py tests/pull_agent/test_parser.py
git commit -m "feat(pull_agent): add JSON parser with schema validation"
```

---

## Task 4: 拉人接口 stub

说明：`add_sys_manager_to_chat` 是外部真实接口。当前还没有，先写一个 stub，只打 log 并返回成功，便于集成。实际上线时替换实现即可。异常照常向上抛。

**Files:**
- Create: `app/pull_agent/chat_client.py`
- Test: `tests/pull_agent/test_chat_client.py`

**Step 1: 写失败测试**

```python
# tests/pull_agent/test_chat_client.py
from app.pull_agent.chat_client import add_sys_manager_to_chat

def test_stub_returns_true(caplog):
    import logging
    caplog.set_level(logging.INFO)
    ok = add_sys_manager_to_chat("Linux操作系统", "运维经理")
    assert ok is True
    assert "Linux操作系统" in caplog.text
    assert "运维经理" in caplog.text
```

**Step 2: 跑测试确认失败**

**Step 3: 实现**

```python
# app/pull_agent/chat_client.py
import logging

logger = logging.getLogger(__name__)


def add_sys_manager_to_chat(system_name: str, manager_type: str) -> bool:
    """Stub. Replace with real API call when integrating."""
    logger.info("add_sys_manager_to_chat called: system=%s, manager=%s",
                system_name, manager_type)
    return True
```

**Step 4: 跑测试确认通过**

**Step 5: 提交**

```bash
git add app/pull_agent/chat_client.py tests/pull_agent/test_chat_client.py
git commit -m "feat(pull_agent): add chat client stub"
```

---

## Task 5: Agent 主入口（mock LLM 单测）

**Files:**
- Create: `app/pull_agent/agent.py`
- Test: `tests/pull_agent/test_agent.py`

**Step 1: 写失败测试**

```python
# tests/pull_agent/test_agent.py
import pytest
from unittest.mock import AsyncMock, patch
from app.pull_agent.agent import handle_message

@pytest.mark.asyncio
async def test_handle_message_ok():
    fake = '{"status":"ok","actions":[{"asset":"Linux操作系统","role":"运维经理"},{"asset":"GaussDB","role":"运维经理"}]}'
    with patch("app.pull_agent.agent._llm_chat", new=AsyncMock(return_value=fake)):
        result = await handle_message("拉Linux和GaussDB的运维经理")
    assert result["status"] == "ok"
    assert len(result["called"]) == 2
    assert all(c["success"] for c in result["called"])

@pytest.mark.asyncio
async def test_handle_message_failed():
    fake = '{"status":"failed","actions":[],"unresolved":["DBA"],"message":"无法确认"}'
    with patch("app.pull_agent.agent._llm_chat", new=AsyncMock(return_value=fake)):
        result = await handle_message("拉个DBA")
    assert result["status"] == "failed"
    assert result["called"] == []

@pytest.mark.asyncio
async def test_handle_message_chat_api_raises():
    fake = '{"status":"ok","actions":[{"asset":"Linux操作系统","role":"运维经理"}]}'
    def boom(*_):
        raise RuntimeError("network down")
    with patch("app.pull_agent.agent._llm_chat", new=AsyncMock(return_value=fake)), \
         patch("app.pull_agent.agent.add_sys_manager_to_chat", side_effect=boom):
        result = await handle_message("拉Linux的运维经理")
    assert result["called"][0]["success"] is False
    assert "network down" in result["called"][0]["error"]

@pytest.mark.asyncio
async def test_handle_message_parse_error():
    with patch("app.pull_agent.agent._llm_chat", new=AsyncMock(return_value="not json")):
        result = await handle_message("任意")
    assert result["status"] == "failed"
    assert "parse" in result["message"].lower() or "解析" in result["message"]
```

**Step 2: 跑测试确认失败**

**Step 3: 实现**

```python
# app/pull_agent/agent.py
import logging
from app.config import get_settings
from app.llm.client import LLMClient
from app.pull_agent.assets import load_assets
from app.pull_agent.prompt import build_prompt
from app.pull_agent.parser import parse_llm_output, ParseError
from app.pull_agent.chat_client import add_sys_manager_to_chat

logger = logging.getLogger(__name__)


async def _llm_chat(messages: list[dict]) -> str:
    client = LLMClient(get_settings())
    return await client.chat(messages)


async def handle_message(user_input: str) -> dict:
    logger.info("handle_message input: %s", user_input)
    assets = load_assets()
    messages = build_prompt(user_input, assets)
    logger.debug("prompt: %s", messages)

    raw = await _llm_chat(messages)
    logger.info("llm raw output: %s", raw)

    try:
        parsed = parse_llm_output(raw, assets)
    except ParseError as e:
        logger.exception("parse failed")
        return {
            "status": "failed",
            "called": [],
            "unresolved": [],
            "message": f"LLM 输出解析失败: {e}",
        }

    called = []
    for action in parsed["actions"]:
        asset, role = action["asset"], action["role"]
        try:
            ok = add_sys_manager_to_chat(asset, role)
            called.append({"asset": asset, "role": role, "success": bool(ok)})
        except Exception as e:
            logger.exception("chat api failed for %s/%s", asset, role)
            called.append({"asset": asset, "role": role,
                           "success": False, "error": str(e)})

    result = {
        "status": parsed["status"],
        "called": called,
        "unresolved": parsed["unresolved"],
        "message": parsed["message"],
    }
    logger.info("handle_message result: %s", result)
    return result
```

**Step 4: 跑测试确认通过**

Run: `pytest tests/pull_agent/test_agent.py -v`

**Step 5: 提交**

```bash
git add app/pull_agent/agent.py tests/pull_agent/test_agent.py
git commit -m "feat(pull_agent): add single-turn agent entry point"
```

---

## Task 6: 真调 LLM 的端到端测试

说明：这组测试会真实调用 `.env` 配置的 LLM。用 `@pytest.mark.e2e` 标记，默认也跑，需要时可 `-m "not e2e"` 跳过。

**Files:**
- Modify: `pyproject.toml`（加 `e2e` marker，如已有忽略）
- Create: `tests/pull_agent/test_agent_e2e.py`

**Step 1: 写测试**

```python
# tests/pull_agent/test_agent_e2e.py
import pytest
from app.pull_agent.agent import handle_message


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_pull_two_linux_gauss_ops():
    result = await handle_message("请拉Linux操作系统和GaussDB的运维经理")
    assert result["status"] == "ok"
    called = {(c["asset"], c["role"]) for c in result["called"]}
    assert ("Linux操作系统", "运维经理") in called
    assert ("GaussDB", "运维经理") in called


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_unspecified_role_pulls_both():
    result = await handle_message("把智能客服系统的人都拉进来")
    assert result["status"] == "ok"
    called = {(c["asset"], c["role"]) for c in result["called"]}
    assert ("智能客服系统", "运维经理") in called
    assert ("智能客服系统", "开发经理") in called


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_ambiguous_returns_failed():
    result = await handle_message("拉个DBA过来")
    assert result["status"] == "failed"
    assert result["called"] == []
```

**Step 2: 确认 marker 注册**

`pyproject.toml` 下 `[tool.pytest.ini_options]` 加：
```toml
markers = ["e2e: hits real LLM / external APIs"]
```

**Step 3: 跑测试**

Run: `pytest tests/pull_agent/test_agent_e2e.py -v`
Expected: PASS（取决于 LLM 实际输出；若失败按 bad case 调 prompt 里的示例后再跑）

**Step 4: 提交**

```bash
git add tests/pull_agent/test_agent_e2e.py pyproject.toml
git commit -m "test(pull_agent): add e2e tests hitting real LLM"
```

---

## Task 7: 日志配置 + 手动冒烟脚本

目的：方便手动跑几条输入观察效果，积累 bad case。

**Files:**
- Create: `scripts/pull_agent_smoke.py`

**Step 1: 实现**

```python
# scripts/pull_agent_smoke.py
import asyncio
import logging
import sys
from app.pull_agent.agent import handle_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

async def main():
    text = " ".join(sys.argv[1:]) or "请拉Linux操作系统和GaussDB的运维经理"
    result = await handle_message(text)
    print("\n=== RESULT ===")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: 手动跑**

```bash
python scripts/pull_agent_smoke.py "请拉Linux操作系统和GaussDB的运维经理"
python scripts/pull_agent_smoke.py "把智能客服系统的人都拉进来"
python scripts/pull_agent_smoke.py "拉个DBA过来"
```

**Step 3: 提交**

```bash
git add scripts/pull_agent_smoke.py
git commit -m "chore(pull_agent): add smoke script for manual testing"
```

---

## 完成后的产物

- `app/pull_agent/` 独立模块，不影响现有 V1 agent
- 一个入口函数 `handle_message(text: str) -> dict`
- 全量单测（mock LLM）+ 端到端测（真调 LLM）
- 一个手动冒烟脚本
- 全链路 INFO 日志（输入、prompt、LLM 输出、接口调用结果）

## 后续替换点（不在本 plan 范围）

1. `assets.load_assets()` → 接入真实 DB / 配置中心
2. `chat_client.add_sys_manager_to_chat()` → 接入真实 API
3. `.env` 的 LLM 换成内网 OpenAPI（改 `AGENT_LLM_BASE_URL` / `AGENT_LLM_API_KEY` 即可）
