import structlog
from app.llm.client import LLMClient
from app.models import BaselineScanResult, InvestigationResult, IncidentRequest
from app.agent.prompts import build_phase3_prompt, format_phase1_summary

log = structlog.get_logger()


class ReportGenerator:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    async def generate(
        self,
        request: IncidentRequest,
        phase1_result: BaselineScanResult,
        phase2_result: InvestigationResult,
    ) -> str:
        system_prompt, context = build_phase3_prompt(request, phase1_result, phase2_result)

        try:
            report = await self._llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context},
            ])
            if report and len(report.strip()) > 50:
                return report
            log.warning("llm_report_too_short", length=len(report) if report else 0)
        except Exception as e:
            log.error("llm_report_failed", error=str(e))

        # Fallback: template-based report
        return self._generate_fallback(request, phase1_result, phase2_result)

    def _generate_fallback(
        self,
        request: IncidentRequest,
        phase1_result: BaselineScanResult,
        phase2_result: InvestigationResult,
    ) -> str:
        phase1_text = format_phase1_summary(phase1_result)
        lines = [
            "# 巡检报告（模板生成）",
            "",
            f"> LLM 不可用，以下为原始巡检数据",
            "",
            f"**系统代码**: {request.system_code}",
            f"**影响范围**: {request.influence_area}",
            "",
            "## 基础巡检数据",
            "",
            phase1_text,
            "",
        ]

        if phase2_result.findings:
            lines.append("## 深入调查发现")
            lines.append("")
            for f in phase2_result.findings:
                lines.append(f"- [{f.source}] {f.description}")
            lines.append("")

        if phase2_result.errors:
            lines.append("## 调查错误")
            lines.append("")
            for e in phase2_result.errors:
                lines.append(f"- {e}")

        return "\n".join(lines)
