import asyncio
import time
from app.adapters.base import AdapterRegistry
from app.models import AdapterResult, BaselineScanResult


class BaselineScanner:
    def __init__(self, registry: AdapterRegistry, timeout: int = 15):
        self._registry = registry
        self._timeout = timeout

    async def scan(
        self, system_code: str, influence_area: str,
        start_time: str, end_time: str,
    ) -> BaselineScanResult:
        adapters = self._registry.all()
        tasks = [
            self._fetch_one(adapter, system_code, influence_area, start_time, end_time)
            for adapter in adapters
        ]
        all_results = await asyncio.gather(*tasks)

        successful = [r for r in all_results if r.error is None]
        failed = [r for r in all_results if r.error is not None]

        return BaselineScanResult(
            results=successful,
            errors=failed,
            total_adapters=len(adapters),
        )

    async def _fetch_one(
        self, adapter, system_code, influence_area, start_time, end_time,
    ) -> AdapterResult:
        start = time.time()
        try:
            data = await asyncio.wait_for(
                adapter.fetch_data(system_code, influence_area, start_time, end_time),
                timeout=self._timeout,
            )
            return AdapterResult(
                adapter_name=adapter.name,
                data=data,
                duration_ms=round((time.time() - start) * 1000, 1),
            )
        except asyncio.TimeoutError:
            return AdapterResult(
                adapter_name=adapter.name,
                error=f"Timeout after {self._timeout}s",
                duration_ms=round((time.time() - start) * 1000, 1),
            )
        except Exception as e:
            return AdapterResult(
                adapter_name=adapter.name,
                error=str(e),
                duration_ms=round((time.time() - start) * 1000, 1),
            )
