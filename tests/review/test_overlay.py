"""overlay 修订层:叠加取最新 + 乐观锁冲突(sqlite 桩真跑）。"""
import pytest

from big_data_model.review import overlay


def test_save_and_latest():
    v1 = overlay.save_edit("E1", {"类别": "DB"}, reviewed=True, reviewer="张三", base_version=None)
    m = overlay.latest_by_event()
    assert m["E1"].patch == {"类别": "DB"}
    assert m["E1"].reviewed is True and m["E1"].reviewer == "张三"
    assert m["E1"].version == v1


def test_latest_wins_over_earlier():
    overlay.save_edit("E1", {"类别": "DB"}, reviewed=True, reviewer="a", base_version=None)
    v = overlay.current_version("E1")
    overlay.save_edit("E1", {"类别": "CONFIG"}, reviewed=True, reviewer="b", base_version=v)
    m = overlay.latest_by_event()
    assert m["E1"].patch == {"类别": "CONFIG"} and m["E1"].reviewer == "b"


def test_optimistic_lock_conflict():
    overlay.save_edit("E1", {"类别": "DB"}, reviewed=True, reviewer="a", base_version=None)
    # 另一个人拿着过期的 base_version(None)再存 → 冲突
    with pytest.raises(overlay.VersionConflict) as ei:
        overlay.save_edit("E1", {"类别": "APP"}, reviewed=True, reviewer="b", base_version=None)
    assert ei.value.latest == overlay.current_version("E1")


def test_patch_field_whitelist():
    overlay.save_edit("E1", {"类别": "DB", "乱塞": "x"}, reviewed=True, reviewer="a", base_version=None)
    assert "乱塞" not in overlay.latest_by_event()["E1"].patch


def test_pending_system_insert():
    overlay.add_pending_system("某新系统", "E9", "张三")  # 不抛即可
