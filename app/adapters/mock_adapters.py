from app.adapters.base import BaseAdapter, AdapterRegistry
from monitor_api_examples import (
    get_bpc_monitor_data,
    get_promtheus_monitor_data,
    get_db_monitor_data,
    get_host_monitor_data,
    get_zujian_monitor_data,
    get_log_monitor_data,
    get_south_centor_minotor_data,
)


class BPCAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "bpc"

    @property
    def description(self) -> str:
        return "BPC 业务交易监控：交易量、响应率、成功率、平均耗时等业务指标"

    async def fetch_data(self, system_code, influence_area, start_time, end_time):
        return get_bpc_monitor_data(system_code, influence_area, start_time, end_time)


class PrometheusAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "prometheus"

    @property
    def description(self) -> str:
        return "Prometheus 网络监控：TCP/HTTP 探测节点数、异常节点、响应参数"

    async def fetch_data(self, system_code, influence_area, start_time, end_time):
        return get_promtheus_monitor_data(system_code, influence_area, start_time, end_time)


class DatabaseAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "database"

    @property
    def description(self) -> str:
        return "数据库监控：GaussDB/Oracle 告警（复制槽延迟、长事务、表空间）及实例状态（CPU、内存、连接数）"

    async def fetch_data(self, system_code, influence_area, start_time, end_time):
        return get_db_monitor_data(system_code, influence_area, start_time, end_time)


class HostAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "host"

    @property
    def description(self) -> str:
        return "主机监控：服务器告警及资源使用情况（CPU、内存、IO Wait、磁盘）"

    async def fetch_data(self, system_code, influence_area, start_time, end_time):
        return get_host_monitor_data(system_code, influence_area, start_time, end_time)


class ComponentAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "component"

    @property
    def description(self) -> str:
        return "中间件组件监控：Redis/Consul/Zuul 等集群状态及各实例运行状态"

    async def fetch_data(self, system_code, influence_area, start_time, end_time):
        return get_zujian_monitor_data(system_code, influence_area, start_time, end_time)


class LogAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "log"

    @property
    def description(self) -> str:
        return "日志监控：应用日志关键字匹配结果"

    async def fetch_data(self, system_code, influence_area, start_time, end_time):
        return get_log_monitor_data(system_code, influence_area, start_time, end_time)


class SouthCenterAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "south_center"

    @property
    def description(self) -> str:
        return "南方中心机房监控：数据中心基础设施告警（存储、网络设备等紧急/虚拟化告警）"

    async def fetch_data(self, system_code, influence_area, start_time, end_time):
        return get_south_centor_minotor_data(system_code, influence_area, start_time, end_time)


def create_default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    for adapter_cls in [
        BPCAdapter, PrometheusAdapter, DatabaseAdapter, HostAdapter,
        ComponentAdapter, LogAdapter, SouthCenterAdapter,
    ]:
        registry.register(adapter_cls())
    return registry
