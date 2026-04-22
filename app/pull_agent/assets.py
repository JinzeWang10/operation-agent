ASSETS = [
    "智家服务管理系统",
    "智能合规双录平台",
    "智能化打印PageOn系统",
    "智能客服系统",
    "智能培训效果评估系统",
    "智能识别",
    "智能医疗审核系统",
    "智能营销",
    "智能中心",
    "AIX操作系统",
    "Linux操作系统",
    "Windows操作系统",
    "SinoDB",
    "OracleDB",
    "GaussDB",
    "PG数据库系统",
    "SVC存储虚拟化",
    "LinuxONE软件",
    "Gbase数据库系统",
    "OceanBase-PAAS",
]

MANAGER_TYPES = ["运维经理", "开发经理"]


def load_assets() -> list[str]:
    return list(ASSETS)
