"""系统名归一化：把自然语言里的系统/资产口语，映射到清单里的规范全称。

这是一个跟"要拿它干什么"无关的独立原语——拉群、查经理、ywfx、事件分析
都可以复用。它只回答一个问题：这句话里提到了清单里的哪些系统？

三层，命中即用：
  1. 确定性层：别名表 + 清单全称直接出现在文本里（0 token，最精确）。
  2. LLM 兜底层：走内网千问单串接口，只做实体链接，不管岗位/动作。
  3. 校验层：输出必须落在清单内，杜绝幻觉。

清单来自 assets.load_assets(step_num)：step_num=1 是一线主系统（小、干净），
识别不到再自动落到 step_num=2 的全量清单。
"""
import json
import logging
import re

import requests

from big_data_model.pull_agent.assets import load_assets
from constant.const import common_area_name_dict

logger = logging.getLogger(__name__)

QWEN_URL = "http://10.20.194.43:6832/qwen2_chat"
QWEN_SYSTEM_CODE = "03F6"

# 口语/简称 -> 规范名。刻意留空：等上线后观察到某个简称被 LLM 反复认错、
# 且能用一条规则修正时，再往这里加一行。不要预先猜。
ALIASES: dict[str, str] = {}

# 清单不超过这个数，就整个塞进 prompt；超过就先按字面重合度预筛候选，
# 只把最相关的一小撮喂给 LLM——避免几百上千条清单撑爆 prompt、又拖垮判断质量。
MAX_INLINE_ASSETS = 60
CANDIDATE_K = 40


RESOLVE_TEMPLATE = """你是运维系统名识别助手。从用户消息中找出提到的系统/资产，映射到<可选资产>清单里的规范全称。

<可选资产>
{assets}
</可选资产>

<规则>
1. 只能输出<可选资产>清单里的完整名称，一字不差，不得杜撰。
2. 简称/俗称/口误做映射，有把握才映射，不确定就当作无法识别。
   - "高斯"/"高斯DB" -> "GaussDB"
   - "车险承保" -> "第三代车险承保系统"
   - "客服系统" -> "智能客服系统"
3. 无法对应清单里唯一一项时（找不到，或像"数据库"这种对应多项）：放进 unresolved 记原文，不要猜、不要反问。
4. 只识别系统名，不要理会岗位、人员、动作等其它内容。
只输出 JSON，不要解释、不要 markdown 代码块：
{{"resolved":["规范名"],"unresolved":["原文片段"]}}"""


class AssetResolution:
    """resolve_assets 的结果。

    resolved:   命中的规范名（清单内，去重保序）。
    unresolved: 文本里提到、但映射不到清单的原文片段。
    """

    def __init__(self, resolved: list[str], unresolved: list[str]):
        self.resolved = resolved
        self.unresolved = unresolved

    def __bool__(self) -> bool:
        return bool(self.resolved)

    def __repr__(self) -> str:
        return f"AssetResolution(resolved={self.resolved}, unresolved={self.unresolved})"


def call_qwen(prompt_text: str) -> str:
    resp = requests.post(
        QWEN_URL,
        headers={"Content-Type": "application/json"},
        json={
            "system_code": QWEN_SYSTEM_CODE,
            "prompt_text": prompt_text,
            "temperature": 0,
        },
    )
    return resp.json().get("output_result", "")


def _deterministic(text: str, asset_set: set[str]) -> list[str]:
    """别名命中 + 清单全称直接出现在文本里。保序去重。"""
    hits: list[str] = []

    def _add(name: str) -> None:
        if name in asset_set and name not in hits:
            hits.append(name)

    for alias, canon in ALIASES.items():
        if alias and alias in text:
            _add(canon)
    for name in asset_set:
        if name in text:
            _add(name)
    return hits


def _lcs_len(asset: str, text: str) -> int:
    """asset 中"整段出现在 text 里"的最长子串长度。跨语言(高斯/GaussDB)自然得 0。"""
    best = 0
    n = len(asset)
    for i in range(n):
        # 只尝试比当前最优更长的子串
        for j in range(i + best + 1, n + 1):
            if asset[i:j] in text:
                best = j - i
            else:
                break
    return best


def _prefilter(text: str, assets: list[str], k: int) -> list[str]:
    """按字面重合度取 top-k 候选（召回优先，精排交给 LLM）。"""
    scored = [(s, a) for a in assets if (s := _lcs_len(a, text)) >= 2]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [a for _, a in scored[:k]]


def _candidates_for_prompt(text: str, assets: list[str]) -> list[str]:
    """小清单整个用；大清单先预筛，把 prompt 控制在一小撮候选内。"""
    if len(assets) <= MAX_INLINE_ASSETS:
        return assets
    return _prefilter(text, assets, CANDIDATE_K)


def _parse_resolve(raw: str) -> tuple[list[str], list[str]]:
    """从千问原始输出里抠出 JSON。解析失败一律降级为空，不抛异常。"""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        logger.warning("resolve: qwen 输出里没有 JSON: %r", raw)
        return [], []
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("resolve: JSON 非法: %r", raw)
        return [], []
    resolved = [x for x in (obj.get("resolved") or []) if isinstance(x, str)]
    unresolved = [x for x in (obj.get("unresolved") or []) if isinstance(x, str)]
    return resolved, unresolved


def resolve_assets(text: str, step_num: int = 1) -> AssetResolution:
    """把自然语言里的系统名归一化到清单规范名。

    step_num=1 先在一线清单里找；一个都没命中时自动落到 step_num=2 全量清单再试。
    """
    assets = load_assets(step_num)
    asset_set = set(assets)

    resolved = _deterministic(text, asset_set)

    unresolved: list[str] = []
    candidates = _candidates_for_prompt(text, assets)
    if candidates:
        prompt = RESOLVE_TEMPLATE.format(assets="\n".join(candidates)) + "\n\n用户：" + text
        llm_resolved, unresolved = _parse_resolve(call_qwen(prompt))
        for name in llm_resolved:
            if name in asset_set and name not in resolved:  # 校验层：防幻觉
                resolved.append(name)

    # 已识别的就别再算进 unresolved
    resolved_set = set(resolved)
    unresolved = [u for u in unresolved if u not in resolved_set]

    if not resolved and step_num == 1:
        logger.info("resolve: 一线清单未命中，落到全量清单重试: %r", text)
        return resolve_assets(text, step_num=2)

    result = AssetResolution(resolved, unresolved)
    logger.info("resolve_assets(%r, step=%s) -> %s", text, step_num, result)
    return result


def resolve_area(text: str) -> str:
    """从自然语言里识别区域/省份，返回区域编码（如"四川"->"SC"）；识别不到返回空串。

    区域是 40 来个固定中文名的闭集且互不包含，纯子串匹配即可，不走 LLM。
    一句话提到多个区域时取最先出现的那个。
    """
    best_pos = -1
    best_name = None
    for name in common_area_name_dict:
        pos = text.find(name)
        if pos >= 0 and (best_pos < 0 or pos < best_pos):
            best_pos = pos
            best_name = name
    code = common_area_name_dict[best_name] if best_name else ""
    logger.info("resolve_area(%r) -> %r", text, code)
    return code
