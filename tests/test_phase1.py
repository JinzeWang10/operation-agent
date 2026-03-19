import pytest
import asyncio
from app.adapters.base import BaseAdapter, AdapterRegistry
from app.agent.phase1 import BaselineScanner
from app.adapters.mock_adapters import create_default_registry


class SlowAdapter(BaseAdapter):
    @property
    def name(self): return "slow"
    @property
    def description(self): return "Slow adapter for testing"
    async def fetch_data(self, system_code, influence_area, start_time, end_time):
        await asyncio.sleep(10)
        return {}


class FailingAdapter(BaseAdapter):
    @property
    def name(self): return "failing"
    @property
    def description(self): return "Failing adapter for testing"
    async def fetch_data(self, system_code, influence_area, start_time, end_time):
        raise ConnectionError("Connection refused")


@pytest.mark.asyncio
async def test_scan_all_adapters_succeed():
    registry = create_default_registry()
    scanner = BaselineScanner(registry, timeout=15)
    result = await scanner.scan("SBYL", "总公司", "2026-01-19 15:00:00", "2026-01-19 16:00:00")

    assert result.total_adapters == 7
    assert len(result.results) == 7
    assert len(result.errors) == 0
    names = {r.adapter_name for r in result.results}
    assert "bpc" in names
    assert "database" in names


@pytest.mark.asyncio
async def test_scan_handles_timeout():
    registry = AdapterRegistry()
    registry.register(SlowAdapter())
    scanner = BaselineScanner(registry, timeout=1)
    result = await scanner.scan("X", "Y", "2026-01-01 00:00:00", "2026-01-01 01:00:00")

    assert len(result.errors) == 1
    assert "Timeout" in result.errors[0].error


@pytest.mark.asyncio
async def test_scan_handles_failure():
    registry = AdapterRegistry()
    registry.register(FailingAdapter())
    scanner = BaselineScanner(registry, timeout=15)
    result = await scanner.scan("X", "Y", "2026-01-01 00:00:00", "2026-01-01 01:00:00")

    assert len(result.errors) == 1
    assert "Connection refused" in result.errors[0].error


@pytest.mark.asyncio
async def test_scan_partial_failure():
    """One adapter fails, others succeed — failures don't block."""
    registry = create_default_registry()
    registry.register(FailingAdapter())
    scanner = BaselineScanner(registry, timeout=15)
    result = await scanner.scan("SBYL", "总公司", "2026-01-19 15:00:00", "2026-01-19 16:00:00")

    assert result.total_adapters == 8  # 7 mock + 1 failing
    assert len(result.results) == 7
    assert len(result.errors) == 1
