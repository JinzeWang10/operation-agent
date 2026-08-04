"""身份 seam:从站点签发的 token 解出当前用户(写 overlay 时记"复核人")。

- **本地/测试**(默认):返回固定桩用户,不校验 token。
- **内网**:设 ``AGENT_REVIEW_IDENTITY=intranet``,把 ``_intranet_user`` 换成现成的
  "token → 用户信息(用户名/账号ID/权限)"函数一行调用即可。

不自建鉴权 —— 访问权由现有站点管;这里只为"改动归属"取当前用户名。
"""
from __future__ import annotations

import os
from typing import Optional


def get_current_user(token: str) -> dict:
    if os.getenv("AGENT_REVIEW_IDENTITY", "stub") == "intranet":
        return _intranet_user(token)
    return {"用户名": "本地测试员", "账号ID": "local", "权限": []}


def reviewer_name(token: Optional[str]) -> str:
    """取用于 ``reviewer`` 字段的显示名。token 缺失/解析失败回落 'unknown'。"""
    try:
        u = get_current_user(_strip_bearer(token or "")) or {}
    except Exception:
        return "unknown"
    return str(u.get("用户名") or u.get("账号ID") or "unknown")


def _strip_bearer(token: str) -> str:
    t = token.strip()
    return t[7:].strip() if t.lower().startswith("bearer ") else t


# ── 内网接线点:换成现成函数,例如  return decode_user(token) ──────────────
def _intranet_user(token: str) -> dict:
    raise NotImplementedError("接内网身份函数:token -> {用户名, 账号ID, 权限}")
