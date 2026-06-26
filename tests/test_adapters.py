import pytest
from big_data_model.adapters.base import AdapterRegistry
from big_data_model.adapters.mock_adapters import (
    BPCAdapter, DatabaseAdapter, create_default_registry,
)


@pytest.fixture
def registry():
    return create_default_registry()


def test_registry_has_all_adapters(registry):
    names = registry.names()
    assert len(names) == 7
    assert "bpc" in names
    assert "database" in names
    assert "south_center" in names


def test_registry_get_existing(registry):
    adapter = registry.get("bpc")
    assert adapter is not None
    assert adapter.name == "bpc"


def test_registry_get_nonexistent(registry):
    assert registry.get("nonexistent") is None


@pytest.mark.asyncio
async def test_bpc_adapter_returns_data():
    adapter = BPCAdapter()
    data = await adapter.fetch_data("SBYL", "总公司", "2026-01-19 15:00:00", "2026-01-19 16:00:00")
    assert "bpcAlarmtypeMap" in data


@pytest.mark.asyncio
async def test_db_adapter_returns_data():
    adapter = DatabaseAdapter()
    data = await adapter.fetch_data("SBYL", "总公司", "2026-01-19 15:00:00", "2026-01-19 16:00:00")
    assert "hostAlarmVO" in data
    assert "dbinfo" in data


def test_adapter_has_description():
    adapter = BPCAdapter()
    assert len(adapter.description) > 0
    assert "BPC" in adapter.description
