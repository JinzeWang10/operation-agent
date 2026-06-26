import structlog
from fastapi import FastAPI

from big_data_model.config import Settings
from big_data_model.models import IncidentRequest, InspectionReport
from big_data_model.adapters.mock_adapters import create_default_registry
from big_data_model.llm.client import LLMClient
from big_data_model.agent.phase1 import BaselineScanner
from big_data_model.agent.phase2 import DeepInvestigator
from big_data_model.agent.phase3 import ReportGenerator
from big_data_model.agent.orchestrator import Orchestrator

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

settings = Settings()

app = FastAPI(title=settings.app_name)

# ── Initialize components ──
registry = create_default_registry()
llm_client = LLMClient(settings)
scanner = BaselineScanner(registry, timeout=settings.timeout_adapter)
investigator = DeepInvestigator(
    llm_client, registry,
    max_rounds=settings.phase2_max_rounds,
    timeout=settings.timeout_phase2,
)
reporter = ReportGenerator(llm_client)
orchestrator = Orchestrator(scanner, investigator, reporter, settings)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "adapters": registry.names(),
    }


@app.post("/api/v1/incidents", response_model=InspectionReport)
async def create_incident(request: IncidentRequest):
    report = await orchestrator.run(request)

    # Console output
    print(f"\n{'=' * 60}")
    print(f"巡检报告 [{report.incident_id}]")
    print(f"{'=' * 60}")
    print(report.report_markdown)
    print(f"{'=' * 60}")
    print(f"耗时: {report.duration_seconds}s")
    print(f"Phase 1: {report.phases_summary.get('phase1', {})}")
    print(f"Phase 2: {report.phases_summary.get('phase2', {})}")
    print(f"{'=' * 60}\n")

    return report
