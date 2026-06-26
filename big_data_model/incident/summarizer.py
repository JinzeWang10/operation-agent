"""LLM-based incident phenomenon summarizer.

Takes a FeatureBag.to_llm_brief() dict, asks the LLM to produce a <=500-char
Chinese summary of *observed phenomena only* (no root-cause speculation,
no recommendations).
"""
from __future__ import annotations

import json
import requests

from big_data_model.config import Settings
from big_data_model.llm.client import LLMClient

SYSTEM_PROMPT = """你是 IT 故障简报助手。用户发生业务影响事件后会拉一份监控快照，你只做一件事：用 ≤500 字总结当前能从数据里看到的"现象"。

铁律：
1. 只陈述快照里有的事实，不做根因推测、不给处置建议。
2. 看不到的就是看不到——接口失败 / 空数据的部分，简短一句话说明"该信号不可用"，不要绕开也不要补脑。
3. 引用具体数值、时间、主机/子网，让人能回 JSON 核对。
4. 现象稀疏就稀疏写——不要为了凑字数重复或扩写。
5. 必须分 2-4 个小节输出，每节聚焦一个维度。每节以一行小标题起头，格式严格为 "## 小标题"（井号空格 + 4-8 字中文），随后是该节正文，正文不再嵌套子标题。小节之间用一个空行分隔。
6. 小标题按数据自然挑选，例如：业务指标、主机与告警、组件状态、关联线索、不可观测信号。没有该维度数据则不要出现对应小节。
7. 日志关键字另有专区单独呈现与研判，你**不要**生成任何与日志相关的小节，也不要在其它小节里转述日志原文。
8. 不要在小节里再列小标题，也不要客套话。
9. 指标归属硬性约束：说"某主机 X 指标高"时，主机必须来自 `hosts.top_{metric}_hosts` 或 `hosts.{metric}_pct.max_host`，并写出该主机的实测百分比。告警名 `alert` 含 "IO" / "内存" / "CPU" 等词只是字面命中，不能据此断言该告警主机的对应指标偏高；要看 `active_alarms[].measured_pct` 里的实测值，并与 `thresholds_pct` 比较。整体水位若全部低于 `thresholds_pct`，应明说"未越阈"而不是夸张为"偏高"。"""


# 日志研判用的独立 prompt：与主简报铁律不同——这里**允许**指出疑似方向。
# 规则刻意收紧成"可指向、不开方"，把"轻度根因指向"关在笼子里。
# TODO(provisional)：措辞与归类词表待拿到真实异常日志样本后收口。
LOG_SYSTEM_PROMPT = """你是 IT 日志研判助手。给你监控匹配到的【异常日志关键词】及其出现次数、波及 IP 数，你用 ≤80 字中文给出一句话研判。

规则：
1. 先把关键词归类（如：连接类 / 超时类 / 资源类 / 认证类 / 数据/SQL类 / 磁盘类 / 其它），再点出疑似方向。
2. 涉及原因时只用"疑似 / 倾向 / 多见于"这类措辞，绝不下确定性断言。
3. 绝不给处置建议（不写"建议重启 / 扩容 / 重试 / 排查"之类）。
4. 只依据给你的关键词与计数，不要脑补没给的系统、主机、错误码。
5. 多个关键词指向同一类问题就合并归纳，可点出最高频者；不要逐条复述。
6. 次数高、波及 IP 广的关键词更值得提，可在研判里带上其量级。
7. 输出纯一段话，不加标题、不加客套。

常见关键词语义参考（仅辅助归类，不要照抄）：
- CannotGetJdbcConnectionException / Connection refused / timeout → 连接类，多见于数据库或下游不可达、连接池耗尽
- does not exist / Unknown column / table → 数据/SQL类，多见于对象缺失或 schema 不一致
- DuplicateKeyException / unique constraint → 数据/SQL类，多见于唯一键冲突
- OutOfMemory / OOM → 资源类"""


def build_log_messages(entries: list[dict]) -> list[dict]:
    lines: list[str] = []
    for e in entries:
        src = f"{e.get('sys', '')}/{e.get('com', '')}".strip("/")
        kws = e.get("keywords") or []
        if kws:
            for h in kws:
                lines.append(
                    f"- [{src}] 关键词「{h.get('kw', '')}」出现 {h.get('count', '?')} 次，"
                    f"涉及 {h.get('ip_count', '?')} 个 IP"
                )
        elif e.get("msg"):
            lines.append(f"- [{src}] {e.get('msg', '')}")
    body = "\n".join(lines)
    user = (
        f"异常日志关键词命中：\n{body}\n\n"
        "请用中文输出 ≤80 字的一句话研判。"
    )
    return [
        {"role": "system", "content": LOG_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


async def summarize_logs(entries: list[dict], settings: Settings | None = None) -> str:
    """对异常日志关键词做一句话研判。
    entries 为 [{'sys','com','keywords':[{'kw','count','ip_count'}], 'msg'}, ...]。
    无异常日志时直接返回空串，调用方据此跳过。"""
    if not entries:
        return ""
    messages = build_log_messages(entries)
    return get_ai_data(json.dumps(messages))


def get_ai_data(content):
    base_url_qianwen = "http://10.20.194.43:6832/qwen2_chat"
    header_data = {"Content-Type": "application/json"}
    params_data = {"system_code": "03F6", "prompt_text": content, "temperature": 0}
    rsp = requests.post(base_url_qianwen, headers=header_data, json=params_data)
    datas = rsp.json()
    print(datas)
    return datas.get("output_result", "")


def build_messages(brief: dict) -> list[dict]:
    snapshot = brief.get("snapshot_time") or "未知时间"
    brief_json = json.dumps(brief, ensure_ascii=False, indent=2, default=str)
    user = (
        f"监控快照（{snapshot}）：\n\n"
        f"```json\n{brief_json}\n```\n\n"
        "请用中文输出 ≤500 字的现象简报。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


async def summarize(brief: dict, settings: Settings | None = None) -> str:
    # client = LLMClient(settings or Settings())
    messages = build_messages(brief)
    print(messages)
    # return await client.chat(messages)
    data = get_ai_data(json.dumps(messages))
    print(data)
    # client = LLMClient(settings or Settings())
    # messages = build_messages(brief)
    return data
