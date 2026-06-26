import json
from big_data_model.adapters.base import AdapterRegistry


def build_tool_definitions(registry: AdapterRegistry) -> list[dict]:
    """Build OpenAI-format tool definitions from registered adapters."""
    tools = []
    for adapter in registry.all():
        tools.append({
            "type": "function",
            "function": {
                "name": f"query_{adapter.name}",
                "description": f"查询{adapter.description}。可调整时间窗口或参数来获取不同维度的数据。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "system_code": {"type": "string", "description": "系统代码"},
                        "influence_area": {"type": "string", "description": "影响范围"},
                        "start_time": {"type": "string", "description": "开始时间，格式 YYYY-MM-DD HH:MM:SS"},
                        "end_time": {"type": "string", "description": "结束时间，格式 YYYY-MM-DD HH:MM:SS"},
                    },
                    "required": ["system_code", "influence_area", "start_time", "end_time"],
                },
            },
        })

    tools.append({
        "type": "function",
        "function": {
            "name": "finish_investigation",
            "description": "当已收集到足够信息时，调用此工具结束调查。请在 summary 中总结发现的异常。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "调查发现摘要，列出关键异常"},
                },
                "required": ["summary"],
            },
        },
    })

    return tools


async def execute_tool(name: str, arguments: dict, registry: AdapterRegistry) -> str:
    """Execute a tool call and return result as JSON string."""
    if name == "finish_investigation":
        return json.dumps(
            {"status": "investigation_finished", "summary": arguments.get("summary", "")},
            ensure_ascii=False,
        )

    # Tool name format: query_<adapter_name>
    adapter_name = name.removeprefix("query_")
    adapter = registry.get(adapter_name)
    if adapter is None:
        return json.dumps({"error": f"未知的监控源: {adapter_name}"}, ensure_ascii=False)

    try:
        data = await adapter.fetch_data(
            arguments["system_code"],
            arguments["influence_area"],
            arguments["start_time"],
            arguments["end_time"],
        )
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"查询失败: {str(e)}"}, ensure_ascii=False)
