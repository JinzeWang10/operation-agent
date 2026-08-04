"""复核优先级分诊测试(对齐 DEPLOY 三点六）。"""
from big_data_model.review.priority import review_priority


def _p(**kw):
    base = dict(系统="车险核保系统", 类别="DB", 定位对象="uwtfee表", 描述="慢SQL",
                有效性="valid", is_invalid_flag=False, 低置信=False)
    base.update(kw)
    return review_priority(**base)


def test_p0_unknown_but_has_info():
    prio, reasons = _p(类别="UNKNOWN", 定位对象="", 描述="表空间满导致只读")
    assert prio == "P0" and reasons


def test_p0_unknown_has_loc_only():
    prio, _ = _p(类别="UNKNOWN", 定位对象="数据库集群/表空间", 描述="")
    assert prio == "P0"


def test_p2_unknown_empty_invalid():
    prio, reasons = _p(类别="UNKNOWN", 定位对象="", 描述="", 有效性="invalid")
    assert prio == "P2" and "噪声" in reasons[0]


def test_p2_unknown_empty_valid():
    prio, _ = _p(类别="UNKNOWN", 定位对象="(未定位)", 描述="", 有效性="valid")
    assert prio == "P2"


def test_p1_low_confidence():
    prio, reasons = _p(低置信=True)
    assert prio == "P1" and "低置信" in reasons


def test_p1_validity_conflict():
    prio, reasons = _p(is_invalid_flag=True, 有效性="valid")
    assert prio == "P1" and any("冲突" in r for r in reasons)


def test_p1_system_not_in_vocab():
    prio, reasons = _p(系统="完全不存在的系统XYZ")
    assert prio == "P1" and any("词表" in r for r in reasons)


def test_no_flag_clean_case():
    prio, reasons = _p()
    assert prio is None and reasons == []


def test_p0_beats_p1():
    # UNKNOWN 有信息 + 低置信 → P0 优先
    prio, _ = _p(类别="UNKNOWN", 描述="表空间满", 低置信=True)
    assert prio == "P0"
