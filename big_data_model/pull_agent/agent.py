"""拉群编排：先归一化系统名（resolve_assets），再判岗位（bind_roles）。

asset 和 role 拆成两步：
  - resolve_assets 只认系统名，可被查经理 / ywfx / 事件分析等复用；
  - bind_roles 是拉群特有的一步，只在"已确认的少数系统"上判岗位，
    LLM 不再对着几百条大清单大海捞针，判断质量因此稳得多。

返回结构（dict，供调用方直接用，不需要 eval）：
  {"status": "ok|partial|failed",
   "actions": [{"asset": "规范名", "role": "运维经理"}],
   "unresolved": ["原文片段"],
   "message": "给用户看的话"}
"""
import json
import logging
import re

from big_data_model.pull_agent.resolver import resolve_assets, call_qwen

logger = logging.getLogger(__name__)

_VALID_ROLES = {"运维经理", "开发经理"}

ROLE_TEMPLATE = """用户想把某些系统的负责人拉进群。已经确认涉及以下系统（只能用这些，不得增删）：
{assets}

<可选岗位>运维经理 / 开发经理</可选岗位>
<规则>
1. 为每个已确认系统判断要拉哪些岗位。
2. 明确说"运维" -> 运维经理；明确说"开发" -> 开发经理；
   未指明岗位，或用"负责人/接口人/相关同事/人"等模糊词 -> 运维经理 + 开发经理 都拉。
3. 共享修饰语分发到每个系统："Linux和Windows的运维经理" -> 两个系统都出运维经理。
只输出 JSON，不要解释、不要 markdown：
{{"actions":[{{"asset":"规范名","role":"运维经理"}}]}}"""


def _parse_actions(raw: str, asset_set: set[str]) -> list[dict]:
    """从千问输出抠出 actions，并校验 asset/role 合法。非法项直接丢弃。"""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        logger.warning("bind_roles: qwen 输出里没有 JSON: %r", raw)
        return []
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("bind_roles: JSON 非法: %r", raw)
        return []
    actions: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for a in obj.get("actions") or []:
        if not isinstance(a, dict):
            continue
        asset, role = a.get("asset"), a.get("role")
        if asset in asset_set and role in _VALID_ROLES and (asset, role) not in seen:
            actions.append({"asset": asset, "role": role})
            seen.add((asset, role))
    return actions


def bind_roles(user_input: str, assets: list[str]) -> list[dict]:
    """给已确认的系统判岗位，产出 (系统, 岗位) 列表。"""
    if not assets:
        return []
    prompt = ROLE_TEMPLATE.format(assets="\n".join(assets)) + "\n\n用户：" + user_input
    return _parse_actions(call_qwen(prompt), set(assets))


async def handle_message(user_input: str, step_num: int = 1) -> dict:
    logger.info("handle_message input: %s", user_input)

    res = resolve_assets(user_input, step_num)
    if not res.resolved:
        return {
            "status": "failed",
            "actions": [],
            "unresolved": res.unresolved,
            "message": "未能识别系统名称，请提供系统全称后再试。",
        }

    actions = bind_roles(user_input, res.resolved)
    status = "partial" if res.unresolved else "ok"
    result = {
        "status": status,
        "actions": actions,
        "unresolved": res.unresolved,
        "message": "",
    }
    logger.info("handle_message result: %s", result)
    return result
