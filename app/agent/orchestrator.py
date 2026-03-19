import time
import uuid
import structlog
from datetime import datetime, timedelta

from app.config import Settings
from app.models import (
    IncidentRequest, InspectionReport,
    InvestigationResult,
)
from app.agent.phase1 import BaselineScanner
from app.agent.phase2 import DeepInvestigator
from app.agent.phase3 import ReportGenerator
from app.agent.prompts import build_phase2_prompt

log = structlog.get_logger()


class Orchestrator:
    def __init__(
        self,
        scanner: BaselineScanner,
        investigator: DeepInvestigator,
        reporter: ReportGenerator,
        settings: Settings,
    ):
        self._scanner = scanner
        self._investigator = investigator
        self._reporter = reporter
        self._settings = settings

    async def run(self, request: IncidentRequest) -> InspectionReport:
        incident_id = uuid.uuid4().hex[:8]
        start = time.time()
        log.info("inspection_start", incident_id=incident_id, system_code=request.system_code)

        # Calculate time window
        event_time = datetime.now()
        window = request.time_window_minutes or self._settings.default_time_window_minutes
        start_time = (event_time - timedelta(minutes=window)).strftime("%Y-%m-%d %H:%M:%S")
        end_time = event_time.strftime("%Y-%m-%d %H:%M:%S")

        # ── Phase 1: Baseline Scan ──
        log.info("phase1_start")
        phase1_result = await self._scanner.scan(
            request.system_code, request.influence_area, start_time, end_time,
        )
        log.info("phase1_done",
                 successful=len(phase1_result.results),
                 errors=len(phase1_result.errors))

        # ── Phase 2: Deep Investigation ──
        log.info("phase2_start")
        try:
            sys_prompt, user_msg = build_phase2_prompt(
                request, phase1_result, start_time, end_time,
            )
            phase2_result = await self._investigator.investigate(sys_prompt, user_msg)
        except Exception as e:
            log.error("phase2_failed", error=str(e))
            phase2_result = InvestigationResult(
                terminated_by="llm_unavailable",
                errors=[str(e)],
            )
        log.info("phase2_done",
                 rounds=phase2_result.rounds_used,
                 terminated_by=phase2_result.terminated_by)

        # ── Phase 3: Report Generation ──
        log.info("phase3_start")
        report_markdown = await self._reporter.generate(
            request, phase1_result, phase2_result,
        )
        log.info("phase3_done", report_length=len(report_markdown))

        duration = round(time.time() - start, 2)
        log.info("inspection_done", incident_id=incident_id, duration=duration)

        return InspectionReport(
            incident_id=incident_id,
            report_markdown=report_markdown,
            phases_summary={
                "phase1": {
                    "total_adapters": phase1_result.total_adapters,
                    "successful": len(phase1_result.results),
                    "errors": len(phase1_result.errors),
                },
                "phase2": {
                    "rounds_used": phase2_result.rounds_used,
                    "terminated_by": phase2_result.terminated_by,
                    "findings_count": len(phase2_result.findings),
                },
                "phase3": {
                    "report_length": len(report_markdown),
                },
            },
            duration_seconds=duration,
        )
