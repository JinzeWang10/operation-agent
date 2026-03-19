from pydantic import BaseModel, Field
from typing import Any


class IncidentRequest(BaseModel):
    system_code: str
    influence_area: str
    time_window_minutes: int = 60


class AdapterResult(BaseModel):
    adapter_name: str
    data: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0


class BaselineScanResult(BaseModel):
    results: list[AdapterResult] = Field(default_factory=list)
    errors: list[AdapterResult] = Field(default_factory=list)
    total_adapters: int = 0


class Finding(BaseModel):
    source: str
    description: str
    data: dict[str, Any] | None = None


class InvestigationResult(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    rounds_used: int = 0
    terminated_by: str = "not_started"  # "llm" | "max_rounds" | "timeout" | "llm_error" | "llm_unavailable"
    errors: list[str] = Field(default_factory=list)


class InspectionReport(BaseModel):
    incident_id: str
    report_markdown: str
    phases_summary: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float = 0
