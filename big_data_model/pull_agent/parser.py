import json
import re

from big_data_model.pull_agent.assets import MANAGER_TYPES


class ParseError(Exception):
    pass


_VALID_STATUS = {"ok", "partial", "failed"}


def parse_llm_output(raw: str, assets: list[str]) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
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
        if not isinstance(a, dict):
            raise ParseError(f"action must be dict, got {a!r}")
        if a.get("asset") not in asset_set:
            raise ParseError(f"unknown asset: {a.get('asset')!r}")
        if a.get("role") not in role_set:
            raise ParseError(f"unknown role: {a.get('role')!r}")

    unresolved = obj.get("unresolved", [])
    if not isinstance(unresolved, list):
        raise ParseError("unresolved must be a list")

    return {
        "status": status,
        "actions": actions,
        "unresolved": unresolved,
        "message": obj.get("message", ""),
    }
