from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    async def fetch_data(
        self, system_code: str, influence_area: str,
        start_time: str, end_time: str,
    ) -> dict:
        """Fetch monitoring data. Returns raw dict from monitoring system."""
        ...


class AdapterRegistry:
    def __init__(self):
        self._adapters: dict[str, BaseAdapter] = {}

    def register(self, adapter: BaseAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> BaseAdapter | None:
        return self._adapters.get(name)

    def all(self) -> list[BaseAdapter]:
        return list(self._adapters.values())

    def names(self) -> list[str]:
        return list(self._adapters.keys())
