from big_data_model.pull_agent.assets import load_assets, MANAGER_TYPES


def test_load_assets_returns_nonempty_list():
    assets = load_assets()
    assert isinstance(assets, list)
    assert len(assets) >= 20
    assert "Linux操作系统" in assets
    assert "GaussDB" in assets


def test_manager_types():
    assert MANAGER_TYPES == ["运维经理", "开发经理"]


def test_load_assets_returns_copy():
    a = load_assets()
    a.append("tampered")
    assert "tampered" not in load_assets()
