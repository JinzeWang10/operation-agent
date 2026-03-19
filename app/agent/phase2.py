import json
import time
import structlog
from app.llm.client import LLMClient
from app.adapters.base import AdapterRegistry
from app.agent.tools import build_tool_definitions, execute_tool
from app.models import InvestigationResult, Finding

log = structlog.get_logger()


class DeepInvestigator:
    def __init__(
        self, llm: LLMClient, registry: AdapterRegistry,
        max_rounds: int = 3, timeout: int = 60,
    ):
        self._llm = llm
        self._registry = registry
        self._max_rounds = max_rounds
        self._timeout = timeout

    async def investigate(self, system_prompt: str, user_message: str) -> InvestigationResult:
        tools = build_tool_definitions(self._registry)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        findings: list[Finding] = []
        errors: list[str] = []
        rounds_used = 0
        terminated_by = "max_rounds"
        start_time = time.time()

        for _ in range(self._max_rounds):
            elapsed = time.time() - start_time
            if elapsed > self._timeout:
                terminated_by = "timeout"
                break

            rounds_used += 1

            try:
                message = await self._llm.chat_with_tools(messages, tools)
            except Exception as e:
                log.error("llm_call_failed", error=str(e))
                errors.append(f"LLM 调用失败: {str(e)}")
                terminated_by = "llm_error"
                break

            # No tool calls — LLM gave a text response or is done
            if not message.tool_calls:
                if message.content:
                    findings.append(Finding(source="llm_analysis", description=message.content))
                terminated_by = "llm_no_tools"
                break

            # Add assistant message with tool calls to history
            messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            })

            # Execute each tool call
            investigation_finished = False
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                if tc.function.name == "finish_investigation":
                    summary = args.get("summary", "")
                    findings.append(Finding(
                        source="investigation_summary",
                        description=summary,
                    ))
                    messages.append({
                        "role": "tool",
                        "content": json.dumps({"status": "finished"}),
                        "tool_call_id": tc.id,
                    })
                    terminated_by = "llm"
                    investigation_finished = True
                    continue

                result_str = await execute_tool(tc.function.name, args, self._registry)
                findings.append(Finding(
                    source=tc.function.name,
                    description=f"查询 {tc.function.name}",
                    data=json.loads(result_str) if result_str else None,
                ))
                messages.append({
                    "role": "tool",
                    "content": result_str,
                    "tool_call_id": tc.id,
                })

            if investigation_finished:
                break

        return InvestigationResult(
            findings=findings,
            rounds_used=rounds_used,
            terminated_by=terminated_by,
            errors=errors,
        )
