"""根因锚点归一化测试:系统名收敛、定位对象 facet 分解、命中匹配口径。"""
from big_data_model.incident.knowledge import normalize
from big_data_model.incident.knowledge.normalize import (
    RootCauseLike,
    SystemResolution,
    canonical_system,
    decompose_target,
    resolve_system,
    same_root_cause,
    same_target,
)

# 测试用固定词表,不依赖 vocab 文件内容
KNOWN = {"车险核保系统", "核保规则发布系统", "收付费系统", "第三代非车核保系统"}


# ── 系统名归一化 ─────────────────────────────────────────────────────


def test_canonical_strips_newline_merge():
    # 构造 bug 的历史脏值:fault_system\naffected_business —— 取首段
    assert canonical_system("车险核保系统\n第三代非车理赔系统", KNOWN) == "车险核保系统"


def test_canonical_strips_scope_prefix():
    assert canonical_system("分省部署系统-车险核保系统", KNOWN) == "车险核保系统"


def test_canonical_substring_match():
    assert canonical_system("车险核保系统信创", KNOWN) == "车险核保系统"


def test_resolve_flags_unresolved():
    # 不在词表 → resolved=False,进人工复核队列
    r = resolve_system("某不存在的系统", KNOWN)
    assert isinstance(r, SystemResolution)
    assert r.resolved is False and r.canonical == "某不存在的系统"


def test_resolve_flags_resolved():
    assert resolve_system("收付费系统", KNOWN).resolved is True


# ── 实例 token 抽取 ──────────────────────────────────────────────────


def test_token_rule_app_across_spellings():
    forms = [
        "核保规则发布系统/UnderwritePowerRule_32App",
        "核保规则发布系统/UnderwritePowerRule_32App规则包",
        "核保规则发布系统:UnderwritePowerRule_32App",
        "核保规则UnderwritePowerRule_32App",
        '核保规则"UnderwritePowerRule_32App"',
        "车险核保系统/核保规则发布模块/UnderwritePowerRule_32App",
    ]
    facs = [decompose_target(f, "RELEASE", KNOWN) for f in forms]
    assert all(f.实例token == "UnderwritePowerRule_32App" for f in facs)


def test_token_db_table_and_ip():
    assert decompose_target("uwtfee表(单号字段无索引)", "DB", KNOWN).实例token == "uwtfee表"
    assert decompose_target("主机 10.20.45.18 内存 97%", "HOST", KNOWN).实例token == "10.20.45.18"


# ── 命中匹配:三级口径 ───────────────────────────────────────────────


def _rc(类别, 定位对象):
    return RootCauseLike(类别=类别, 定位对象=定位对象)


def test_same_target_token_unifies_spellings():
    a = decompose_target("核保规则发布系统/UnderwritePowerRule_32App规则包", "RELEASE", KNOWN)
    b = decompose_target("车险核保系统/核保规则发布模块/UnderwritePowerRule_32App", "RELEASE", KNOWN)
    assert same_target(a, b) is True


def test_same_target_different_token_misses():
    a = decompose_target("核保规则发布系统/UnderwritePowerRule_32App", "RELEASE", KNOWN)
    b = decompose_target("核保规则UnderwritePowerRule_34App", "RELEASE", KNOWN)
    assert same_target(a, b) is False


def test_same_target_raw_fallback_parity():
    # 无 token、无系统识别:退化为归一化原文相等,保底不弱于旧精确匹配
    a = decompose_target("DB1", "DB", KNOWN)
    b = decompose_target(" db1 ", "DB", KNOWN)
    assert same_target(a, b) is True


def test_same_target_system_level_downgrade():
    # 同系统、都无更细目标(无 token 无组件类型)→ 系统级命中(计划 1.3 放开)
    a = decompose_target("收付费系统", "APP", KNOWN)
    b = decompose_target("收付费系统", "APP", KNOWN)
    assert same_target(a, b) is True


def test_same_root_cause_category_gate():
    # 定位对象同,但类别不同 → 不命中
    assert same_root_cause(_rc("DB", "DB1"), _rc("HOST", "DB1"), KNOWN) is False
    assert same_root_cause(_rc("DB", "DB1"), _rc("db", " db1 "), KNOWN) is True
