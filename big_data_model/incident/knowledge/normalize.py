"""根因锚点归一化:把自由文本的「系统名 / 定位对象」收敛成可比对的规范锚点。

为什么需要它——命中匹配与同系统召回都靠"字符串对齐",而原始数据里同一个目标
被写成很多样子:``UnderwritePowerRule_32App`` 出现过 8 种写法(带/不带"核保规则
发布系统/"前缀、":"vs"/"、后缀"规则包/规则")。不归一化,评估命中率会虚低到
分不清是 Agent 差还是口径没对齐。

两个字段是**两类不同问题**,分开处理:

- **系统名**:有权威闭集词表(``t_business_standard.system_name``,即 pull_agent
  ``load_assets`` 的源)。本模块只做确定性收敛(去范围前缀 + 按 ``known_systems``
  子串命中);链到规范全称的 LLM 兜底走 pull_agent ``resolve_assets``(内网),
  通过 ``resolve`` 回调注入,离线不依赖它。
- **定位对象**:无闭集词表、也不可能有(实例级、开放集)。按 **facet 分解**:
  ``{归属系统, 组件类型, 实例token}``。实例 token(规则App/表名/库实例/IP)在文本里
  高度规整,可确定性正则抽取。

命中口径(``same_root_cause``,对齐计划 3.3 节「系统+实例token,可降级」):

    命中 = 类别一致
         且 归属系统(规范)一致
         且 (两侧都有实例token → token 一致;否则 → 组件类型一致)

**双端复用同一套**:Stage 1 导入给 Case 落规范锚点,Agent 运行时对自己的输出
做同样分解 —— join key 由构造保证对齐。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Optional

# ── 受控词表加载 ─────────────────────────────────────────────────────

_VOCAB_DIR = Path(__file__).resolve().parent / "vocab"


def _load_vocab_file(name: str) -> tuple[str, ...]:
    path = _VOCAB_DIR / name
    if not path.exists():
        return ()
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return tuple(dict.fromkeys(out))  # 去重保序


@lru_cache(maxsize=1)
def load_known_systems() -> frozenset[str]:
    """系统名受控词表。内网用 t_business_standard.system_name 快照替换 vocab/systems.txt。"""
    return frozenset(_load_vocab_file("systems.txt"))


@lru_cache(maxsize=1)
def load_external_deps() -> frozenset[str]:
    """外部依赖受控词表(行业平台/税局通道等,不在 t_business_standard)。"""
    return frozenset(_load_vocab_file("external_deps.txt"))


@lru_cache(maxsize=1)
def load_target_anchors() -> frozenset[str]:
    """定位对象里"归属系统"facet 的识别锚点 = 系统名 ∪ 外部依赖。"""
    return load_known_systems() | load_external_deps()


# ── 系统名归一化 ─────────────────────────────────────────────────────

# 事件单里常见的"范围/部署"包装前缀,本身不是系统名,归一化前先剥掉。
_SCOPE_PREFIX_RE = re.compile(
    r"^(分省部[署属]系统[-:：]?(深信服[:：])?|【[^】]*】)+"
)


def _strip_scope(s: str) -> str:
    prev = None
    cur = s.strip()
    # 前缀可能叠加(【...】分省部署系统-),循环剥到稳定
    while cur != prev:
        prev = cur
        cur = _SCOPE_PREFIX_RE.sub("", cur).strip()
    return cur


@dataclass(frozen=True)
class SystemResolution:
    """系统名归一化结果。``resolved`` 标记是否落进受控词表——供人工复核筛"不确定"项。"""

    canonical: str   # 规范系统名;命不中词表时为剥壳后的首字段原文
    resolved: bool   # 是否命中受控词表(词表为空时恒 False)
    raw: str


def resolve_system(
    raw: str,
    known_systems: Optional[Iterable[str]] = None,
    *,
    resolve: Optional[Callable[[str], str]] = None,
) -> SystemResolution:
    """把系统名文本收敛到受控词表规范名,并返回是否命中(``resolved``)。

    确定性优先:剥范围前缀 → 取首个字段(换行/逗号/顿号切分)→ 在词表里找
    "作为子串出现的最长规范名"。命不中且给了 ``resolve``(内网 resolve_assets)
    才走 LLM 兜底。全都命不中:``resolved=False``、``canonical`` 退化为剥壳后的
    首字段原文(至少稳定、不再带拼接噪声),这类应进人工复核队列。
    """
    if not raw:
        return SystemResolution("", False, raw or "")
    known_set = set(known_systems) if known_systems is not None else set(load_known_systems())
    known = sorted((k for k in known_set if k), key=len, reverse=True)
    # fault_system 可能是 "A\nB" 或 "A,B"——取第一个片段作为主系统
    head = re.split(r"[\n,，、]", raw.strip(), maxsplit=1)[0]
    head = _strip_scope(head).strip()

    if head in known_set:                      # 1) 直接等于规范名
        return SystemResolution(head, True, raw)
    for name in known:                         # 2) 词表里出现的最长规范名
        if name and name in head:
            return SystemResolution(name, True, raw)
    if resolve is not None:                     # 3) LLM 兜底(内网),只认落在词表内的
        r = (resolve(head) or "").strip()
        if r in known_set:
            return SystemResolution(r, True, raw)
    return SystemResolution(head, False, raw)


def canonical_system(
    raw: str,
    known_systems: Optional[Iterable[str]] = None,
    *,
    resolve: Optional[Callable[[str], str]] = None,
) -> str:
    """``resolve_system`` 的便捷封装,只取规范名字符串。"""
    return resolve_system(raw, known_systems, resolve=resolve).canonical


# ── 定位对象 facet 分解 ──────────────────────────────────────────────

# 实例 token:各类别下"能唯一缩小排查范围"的规范标识,埋在自由文本里。
# 规则发布 App:UnderwritePowerRule_32App / PayctrRule_44App /
#              UnderwriteEndorPowerRule_52App / AllUwRulePolicyApp_4300
_RULE_APP_RE = re.compile(
    r"[A-Za-z]+Rule[A-Za-z]*_\d+[A-Za-z]*App|[A-Za-z]*RulePolicyApp_\d+|"
    r"[A-Za-z]+App_\d+",
)
# DB 字段(prplcontent.serialno)、表名(uwtfee表 / prplpayeeinfo表 / ci...表)、
# 库实例(sc5100prpuw3gdb / hp4100car3gdb)
_DB_FIELD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+\.[A-Za-z][A-Za-z0-9_]+")
_DB_TABLE_RE = re.compile(r"prpl[a-z0-9_]+|ci[a-z0-9_]{4,}|[a-z][a-z0-9_]{3,}表")
_DB_INSTANCE_RE = re.compile(r"[a-z0-9]{4,}g?db\b", re.I)
# 主机/网络:IP
_IP_RE = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")

# 组件类型:小受控枚举,给"无 token 时降级比对"用。关键词命中即定型,取先命中者。
_COMPONENT_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rule-app", ("Rule_", "RulePolicyApp", "规则发布", "规则包", "规则集")),
    ("db-table", ("表", "字段", "索引", "serialno")),
    ("db-instance", ("gdb", "数据库实例", "库实例", "OB数据库", "数据库序列")),
    ("mq", ("kafka", "Kafka", "MQ", "消息队列", "topic", "消费")),
    ("cache", ("redis", "Redis", "缓存", "连接池", "HikariPool")),
    ("host", ("主机", "服务器", "物理机", "NAS", "磁盘", "虚拟机", "节点内存")),
    ("api", ("接口", "interface", "微服务", ".do", "服务节点", "服务编码")),
    ("job", ("作业", "批处理", "跑批", "定时任务", "定时节点", "scheduled")),
    ("config", ("配置", "参数", "开关", "阈值", "策略", "Apollo", "阿波罗")),
    ("gateway", ("网关", "zuul", "Zuul", "gateway", "鉴权")),
    ("client", ("客户端", "浏览器", "前端", "页面", "App安装包")),
    ("network", ("防火墙", "交换机", "VTEP", "网络", "端口", "链路")),
)


@dataclass(frozen=True)
class TargetFacets:
    """定位对象分解出的三个可比对 facet。"""

    系统: str        # 归属系统(规范名;抽不到为 "")
    组件类型: str     # 受控枚举(抽不到为 "")
    实例token: str   # 规范实例标识(抽不到为 "")
    raw: str

    def has_token(self) -> bool:
        return bool(self.实例token)


def extract_instance_token(text: str, 类别: str) -> str:
    """按类别抽取内嵌的规范实例 token;抽不到返回 ""。"""
    if not text:
        return ""
    cat = (类别 or "").upper()
    if cat in ("RELEASE", "CONFIG"):
        m = _RULE_APP_RE.search(text)
        if m:
            return m.group(0)
    if cat == "DB":
        for rgx in (_DB_FIELD_RE, _DB_TABLE_RE, _DB_INSTANCE_RE):
            m = rgx.search(text)
            if m:
                return m.group(0)
    if cat in ("HOST", "NET", "MIDDLEWARE"):
        m = _IP_RE.search(text)
        if m:
            return m.group(0)
    # 兜底:任何类别只要出现规则App/IP 这类强标识,也认(跨类别写串很常见)
    for rgx in (_RULE_APP_RE, _IP_RE):
        m = rgx.search(text)
        if m:
            return m.group(0)
    return ""


def component_type(text: str, 类别: str) -> str:
    """从文本线索定型组件类型(受控枚举);无线索返回 ""。"""
    for name, cues in _COMPONENT_CUES:
        for cue in cues:
            if cue in text:
                return name
    return ""


def decompose_target(
    定位对象: str,
    类别: str,
    known_systems: Optional[Iterable[str]] = None,
    *,
    resolve: Optional[Callable[[str], str]] = None,
) -> TargetFacets:
    """把定位对象分解成 {归属系统, 组件类型, 实例token}。

    ``known_systems`` 缺省时用受控词表锚点(系统名 ∪ 外部依赖)。
    """
    raw = (定位对象 or "").strip()
    anchors = set(known_systems) if known_systems is not None else set(load_target_anchors())
    known = sorted((k for k in anchors if k), key=len, reverse=True)
    sys_hit = ""
    for name in known:  # 定位对象里作为子串出现的最长锚点
        if name and name in raw:
            sys_hit = name
            break
    token = extract_instance_token(raw, 类别)
    ctype = component_type(raw, 类别)
    return TargetFacets(系统=sys_hit, 组件类型=ctype, 实例token=token, raw=raw)


def _norm_token(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _norm_raw(s: str) -> str:
    # 兜底原文比对:去首尾空白 + casefold,语义等价于旧 RootCause.same_target
    return (s or "").strip().casefold()


def same_target(a: TargetFacets, b: TargetFacets) -> bool:
    """定位对象是否同一目标(不含类别判断,类别在 same_root_cause 里比)。

    口径(计划 3.3「系统+实例token,可降级」),分三级、**保底不弱于旧精确匹配**:

    1. 两侧都有实例 token → token 归一后一致即命中(同一规则App/表跨系统写法不同,
       token 已足够唯一);token 都有但不同 → 明确判不同。
    2. 降级:归属系统一致时——组件类型都抽到则比类型;都没抽到则按"系统级同一目标"
       命中(计划 1.3 放开)。
    3. 兜底:上面都没结论时,归一化原文相等即命中(等价旧 exact 匹配,如 DB1==db1),
       确保 token/facet 只会"多命中",不会把旧能命中的搞丢。
    """
    if a.has_token() and b.has_token():
        return _norm_token(a.实例token) == _norm_token(b.实例token)
    if a.系统 and b.系统 and a.系统 == b.系统:
        if a.组件类型 and b.组件类型:
            if a.组件类型 == b.组件类型:
                return True
        elif not a.组件类型 and not b.组件类型:
            return True  # 系统级降级:同系统、都无更细目标
    return _norm_raw(a.raw) == _norm_raw(b.raw)  # 兜底:归一化原文相等


@dataclass(frozen=True)
class RootCauseLike:
    """最小根因载体(类别 × 定位对象),供不便构造 pydantic RootCause 时比对/测试用。"""

    类别: str
    定位对象: str


def same_root_cause(a, b, known_systems: Optional[Iterable[str]] = None) -> bool:
    """两个根因(类别 × 定位对象)是否命中同一目标。

    ``a``/``b`` 鸭子类型:任何带 ``.类别`` 与 ``.定位对象`` 的对象(RootCause /
    Hypothesis)。类别不一致直接否;一致再比定位对象 facet。命中口径见 ``same_target``。
    """
    ca = (getattr(a, "类别", "") or "").strip().casefold()
    cb = (getattr(b, "类别", "") or "").strip().casefold()
    if ca != cb:
        return False
    fa = decompose_target(getattr(a, "定位对象", ""), getattr(a, "类别", ""), known_systems)
    fb = decompose_target(getattr(b, "定位对象", ""), getattr(b, "类别", ""), known_systems)
    return same_target(fa, fb)
