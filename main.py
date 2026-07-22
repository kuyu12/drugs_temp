from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from app.config import Settings, get_settings
from app.db.database import AuditLogRepository
from app.schemas import (
    CostSummaryResponse,
    EvaluationRequest,
    EvaluationResponse,
    MetricsSummaryResponse,
    TriageRequest,
)
from app.services.cost_tracker import CostTracker
from app.services.evaluator import EvaluationService
from app.services.guardrails import GuardrailsService
from app.services.llm_service import PromptRepository, TicketLLMService
from app.services.mlflow_tracker import MLflowTracker
from app.services.triage_service import TriageService


def build_triage_service(settings: Settings) -> TriageService:
    audit_log = AuditLogRepository(settings.database_url)
    mlflow_tracker = MLflowTracker(
        tracking_uri=settings.mlflow_tracking_uri,
        experiment_name=settings.mlflow_experiment_name,
    )
    return TriageService(
        settings=settings,
        audit_log=audit_log,
        guardrails=GuardrailsService(settings.model_name),
        prompts=PromptRepository(settings.prompt_dir),
        llm=TicketLLMService(settings.model_name),
        cost_tracker=CostTracker(
            model_name=settings.model_name,
            input_token_cost=settings.input_token_cost,
            output_token_cost=settings.output_token_cost,
        ),
        mlflow_tracker=mlflow_tracker,
    )


settings = get_settings()
triage_service = build_triage_service(settings)
app = FastAPI(title=settings.app_name)


def get_triage_service() -> TriageService:
    return triage_service


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/triage")
def triage(
    request: TriageRequest,
    service: Annotated[TriageService, Depends(get_triage_service)],
) -> dict:
    return service.triage(request)


@app.get("/costs", response_model=CostSummaryResponse)
def costs(service: Annotated[TriageService, Depends(get_triage_service)]) -> dict:
    return service.audit_log.cost_summary()


@app.get("/runs")
def runs(
    service: Annotated[TriageService, Depends(get_triage_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict]:
    return service.audit_log.list_recent_runs(limit=limit)


@app.get("/runs/{run_id}")
def run_details(
    run_id: str,
    service: Annotated[TriageService, Depends(get_triage_service)],
) -> dict:
    run = service.audit_log.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/metrics-summary", response_model=MetricsSummaryResponse)
def metrics_summary(service: Annotated[TriageService, Depends(get_triage_service)]) -> dict:
    return service.audit_log.metrics_summary()


@app.post("/evaluate", response_model=EvaluationResponse)
def evaluate(
    request: EvaluationRequest,
    service: Annotated[TriageService, Depends(get_triage_service)],
) -> EvaluationResponse:
    evaluator = EvaluationService(
        settings=settings,
        triage_service=service,
        mlflow_tracker=service.mlflow_tracker,
        dataset_path=settings.eval_dataset_path,
    )
    return evaluator.evaluate(request.prompt_version)
