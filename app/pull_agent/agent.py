import logging

from app.config import Settings
from app.llm.client import LLMClient
from app.pull_agent.assets import load_assets
from app.pull_agent.chat_client import add_sys_manager_to_chat
from app.pull_agent.parser import parse_llm_output, ParseError
from app.pull_agent.prompt import build_prompt

logger = logging.getLogger(__name__)


async def _llm_chat(messages: list[dict]) -> str:
    client = LLMClient(Settings())
    return await client.chat(messages)


async def handle_message(user_input: str) -> dict:
    logger.info("handle_message input: %s", user_input)
    assets = load_assets()
    messages = build_prompt(user_input, assets)
    logger.debug("prompt messages: %s", messages)

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

    called: list[dict] = []
    for action in parsed["actions"]:
        asset, role = action["asset"], action["role"]
        try:
            ok = add_sys_manager_to_chat(asset, role)
            called.append({"asset": asset, "role": role, "success": bool(ok)})
        except Exception as e:
            logger.exception("chat api failed for %s/%s", asset, role)
            called.append(
                {"asset": asset, "role": role, "success": False, "error": str(e)}
            )

    result = {
        "status": parsed["status"],
        "called": called,
        "unresolved": parsed["unresolved"],
        "message": parsed["message"],
    }
    logger.info("handle_message result: %s", result)
    return result
