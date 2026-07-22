import json
import time
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.db.database import AuditLogRepository
from app.db.models import AuditRecord
from app.schemas import BlockedResponse, ErrorResponse, TriageRequest, TriageSuccessResponse
from app.services.cost_tracker import CostTracker, TokenUsage
from app.services.guardrails import GuardrailsService
from app.services.llm_service import LLMCallError, InvalidModelOutputError, PromptRepository, TicketLLMService
from app.services.mlflow_tracker import MLflowTracker
from app.services.triage_graph import TicketTriageGraph, TriageGraphState


class TriageService:
    """Coordinates validation, guardrails, LLM call, logging, and response building."""

    def __init__(
        self,
        settings: Settings,
        audit_log: AuditLogRepository,
        guardrails: GuardrailsService,
        prompts: PromptRepository,
        llm: TicketLLMService,
        cost_tracker: CostTracker,
        mlflow_tracker: MLflowTracker,
    ) -> None:
        self.settings = settings
        self.audit_log = audit_log
        self.guardrails = guardrails
        self.prompts = prompts
        self.llm = llm
        self.cost_tracker = cost_tracker
        self.mlflow_tracker = mlflow_tracker
        self.graph = TicketTriageGraph(
            prompts=self.prompts,
            guardrails=self.guardrails,
            llm=self.llm,
        )

    def triage(self, request: TriageRequest) -> dict[str, Any]:
        started_at = time.perf_counter()
        timestamp = datetime.now(UTC).isoformat()

        try:
            graph_state = self.graph.invoke(request)
            prompt_text = graph_state["prompt_text"]
            rendered_prompt = graph_state["rendered_prompt"]
            guardrail = graph_state["guardrail"]
            usage = self._usage_from_graph_state(graph_state)

            if not guardrail.allowed:
                response_without_run_id = {
                    "status": "blocked",
                    "reason": guardrail.reason,
                    "safe_response": guardrail.safe_response,
                }
                latency_ms = self._elapsed_ms(started_at)
                run_id = self._log_to_mlflow(
                    request=request,
                    prompt_text=prompt_text,
                    rendered_prompt=rendered_prompt,
                    guardrail_output=graph_state.get("guardrail_output"),
                    model_output=None,
                    final_response=response_without_run_id,
                    usage=usage,
                    latency_ms=latency_ms,
                    guardrail_status=guardrail.status,
                    guardrail_reason=guardrail.reason,
                    guardrail_confidence=guardrail.confidence,
                    status="blocked",
                )
                response = BlockedResponse(**response_without_run_id, run_id=run_id).model_dump()
                self._save_audit(
                    run_id=run_id,
                    timestamp=timestamp,
                    request=request,
                    guardrail_status=guardrail.status,
                    guardrail_reason=guardrail.reason,
                    model_output=None,
                    final_response=response,
                    usage=usage,
                    latency_ms=latency_ms,
                    status="blocked",
                )
                return response

            analysis = graph_state["analysis"]
            raw_output = graph_state["model_output"]
            latency_ms = self._elapsed_ms(started_at)
            response_without_run_id = {
                "status": "success",
                **analysis.model_dump(mode="json"),
            }
            run_id = self._log_to_mlflow(
                request=request,
                prompt_text=prompt_text,
                rendered_prompt=rendered_prompt,
                guardrail_output=graph_state.get("guardrail_output"),
                model_output=raw_output,
                final_response=response_without_run_id,
                usage=usage,
                latency_ms=latency_ms,
                guardrail_status=guardrail.status,
                guardrail_reason=None,
                guardrail_confidence=guardrail.confidence,
                status="success",
            )
            response = TriageSuccessResponse(**response_without_run_id, run_id=run_id).model_dump(mode="json")
            self._save_audit(
                run_id=run_id,
                timestamp=timestamp,
                request=request,
                guardrail_status=guardrail.status,
                guardrail_reason=None,
                model_output=raw_output,
                final_response=response,
                usage=usage,
                latency_ms=latency_ms,
                status="success",
                category=response["category"],
                priority=response["priority"],
                risk_type=response["risk_type"],
                requires_human=response["requires_human"],
                confidence=response["confidence"],
            )
            return response
        except InvalidModelOutputError as exc:
            prompt_text, rendered_prompt = self.prompts.render(
                request.prompt_version,
                request.customer_message,
            )
            usage = self.cost_tracker.from_optional_counts(
                input_tokens=None if exc.token_usage is None else exc.token_usage.input_tokens,
                output_tokens=None if exc.token_usage is None else exc.token_usage.output_tokens,
            )
            latency_ms = self._elapsed_ms(started_at)
            response_without_run_id = {
                "status": "error",
                "error_type": "invalid_model_output",
                "message": "The model returned an invalid response format.",
            }
            run_id = self._log_to_mlflow(
                request=request,
                prompt_text=prompt_text,
                rendered_prompt=rendered_prompt,
                guardrail_output=None,
                model_output=exc.raw_output,
                final_response=response_without_run_id,
                usage=usage,
                latency_ms=latency_ms,
                guardrail_status="unknown",
                guardrail_reason=None,
                guardrail_confidence=0,
                status="error",
            )
            response = ErrorResponse(**response_without_run_id, run_id=run_id).model_dump()
            self._save_audit(
                run_id=run_id,
                timestamp=timestamp,
                request=request,
                guardrail_status="unknown",
                guardrail_reason=None,
                model_output=exc.raw_output,
                final_response=response,
                usage=usage,
                latency_ms=latency_ms,
                status="error",
            )
            return response
        except LLMCallError as exc:
            prompt_text, rendered_prompt = self.prompts.render(
                request.prompt_version,
                request.customer_message,
            )
            usage = self.cost_tracker.zero()
            latency_ms = self._elapsed_ms(started_at)
            response_without_run_id = {
                "status": "error",
                "error_type": "model_call_failed",
                "message": str(exc),
            }
            run_id = self._log_to_mlflow(
                request=request,
                prompt_text=prompt_text,
                rendered_prompt=rendered_prompt,
                guardrail_output=None,
                model_output=None,
                final_response=response_without_run_id,
                usage=usage,
                latency_ms=latency_ms,
                guardrail_status="error",
                guardrail_reason=None,
                guardrail_confidence=0,
                status="error",
            )
            response = ErrorResponse(**response_without_run_id, run_id=run_id).model_dump()
            self._save_audit(
                run_id=run_id,
                timestamp=timestamp,
                request=request,
                guardrail_status="error",
                guardrail_reason=None,
                model_output=None,
                final_response=response,
                usage=usage,
                latency_ms=latency_ms,
                status="error",
            )
            return response

    def _log_to_mlflow(
        self,
        *,
        request: TriageRequest,
        prompt_text: str,
        rendered_prompt: str,
        guardrail_output: str | None,
        model_output: str | None,
        final_response: dict[str, Any],
        usage: TokenUsage,
        latency_ms: float,
        guardrail_status: str,
        guardrail_reason: str | None,
        guardrail_confidence: float,
        status: str,
    ) -> str:
        output = self._parse_model_output(model_output)
        params = {
            "prompt_version": request.prompt_version,
            "model_name": self.settings.model_name,
            "category": output.get("category"),
            "priority": output.get("priority"),
            "risk_type": output.get("risk_type"),
            "requires_human": output.get("requires_human"),
            "guardrail_status": guardrail_status,
            "guardrail_reason": guardrail_reason,
            "cost_source": usage.cost_source,
            "status": status,
        }
        metrics = {
            "confidence": output.get("confidence", 0),
            "latency_ms": latency_ms,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "estimated_cost": usage.estimated_cost,
            "guardrail_confidence": guardrail_confidence,
        }
        artifacts = {
            "prompt.txt": prompt_text,
            "input.json": {
                "customer_message": request.customer_message,
                "prompt_version": request.prompt_version,
                "rendered_prompt": rendered_prompt,
            },
            "guardrail_output.json": self._parse_model_output(guardrail_output),
            "output.json": output if output else {"raw_output": model_output},
            "final_response.json": final_response,
        }
        return self.mlflow_tracker.log_triage_run(
            params=params,
            metrics=metrics,
            artifacts=artifacts,
        )

    def _save_audit(
        self,
        *,
        run_id: str,
        timestamp: str,
        request: TriageRequest,
        guardrail_status: str,
        guardrail_reason: str | None,
        model_output: str | None,
        final_response: dict[str, Any],
        usage: TokenUsage,
        latency_ms: float,
        status: str,
        category: str | None = None,
        priority: str | None = None,
        risk_type: str | None = None,
        requires_human: bool | None = None,
        confidence: float | None = None,
    ) -> None:
        self.audit_log.save(
            AuditRecord(
                run_id=run_id,
                timestamp=timestamp,
                customer_message=request.customer_message,
                prompt_version=request.prompt_version,
                guardrail_status=guardrail_status,
                guardrail_reason=guardrail_reason,
                model_name=self.settings.model_name,
                model_output=model_output,
                final_response=json.dumps(final_response),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                estimated_cost=usage.estimated_cost,
                latency_ms=latency_ms,
                status=status,
                category=category,
                priority=priority,
                risk_type=risk_type,
                requires_human=requires_human,
                confidence=confidence,
            )
        )

    def _usage_from_graph_state(self, graph_state: TriageGraphState) -> TokenUsage:
        input_tokens = 0
        output_tokens = 0
        for key in ("guardrail_token_usage", "triage_token_usage"):
            usage = graph_state.get(key)
            if usage is not None:
                input_tokens += usage.input_tokens
                output_tokens += usage.output_tokens

        if input_tokens or output_tokens:
            return self.cost_tracker.from_counts(input_tokens, output_tokens)

        return self.cost_tracker.zero()

    def _parse_model_output(self, model_output: str | None) -> dict[str, Any]:
        if not model_output:
            return {}
        try:
            return json.loads(model_output)
        except json.JSONDecodeError:
            return {"raw_output": model_output}

    def _elapsed_ms(self, started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 2)
