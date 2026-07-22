import json
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.schemas import EvaluationResponse, TriageRequest
from app.services.mlflow_tracker import MLflowTracker
from app.services.triage_service import TriageService


class EvaluationService:
    """Runs an evaluation dataset and logs trial metrics to MLflow."""

    def __init__(
        self,
        settings: Settings,
        triage_service: TriageService,
        mlflow_tracker: MLflowTracker,
        dataset_path: Path,
    ) -> None:
        self.settings = settings
        self.triage_service = triage_service
        self.mlflow_tracker = mlflow_tracker
        self.dataset_path = dataset_path

    def evaluate(self, prompt_version: str) -> EvaluationResponse:
        examples = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        results = []

        for example in examples:
            response = self.triage_service.triage(
                TriageRequest(
                    customer_message=example["customer_message"],
                    prompt_version=prompt_version,
                )
            )
            results.append({"example": example, "response": response})

        total = len(results)
        category_accuracy = self._accuracy(results, "category")
        priority_accuracy = self._accuracy(results, "priority")
        requires_human_accuracy = self._accuracy(results, "requires_human")
        risk_type_accuracy = self._accuracy(results, "risk_type")
        # The API response intentionally stays small; detailed per-example data is stored in MLflow.
        costs = []
        latencies = []
        input_tokens = []
        output_tokens = []
        total_tokens = []
        for item in results:
            run = self.triage_service.audit_log.get_run(item["response"]["run_id"])
            if run:
                costs.append(run["estimated_cost"])
                latencies.append(run["latency_ms"])
                input_tokens.append(run["input_tokens"])
                output_tokens.append(run["output_tokens"])
                total_tokens.append(run["total_tokens"])

        average_cost = self._average(costs)
        average_latency_ms = self._average(latencies)
        trial_id = f"trial_{uuid4().hex[:8]}"
        response = EvaluationResponse(
            trial_id=trial_id,
            prompt_version=prompt_version,
            total_examples=total,
            category_accuracy=category_accuracy,
            priority_accuracy=priority_accuracy,
            requires_human_accuracy=requires_human_accuracy,
            risk_type_accuracy=risk_type_accuracy,
            average_cost=average_cost,
            average_latency_ms=average_latency_ms,
        )

        self.mlflow_tracker.log_evaluation_trial(
            trial_id=trial_id,
            params={
                "trial_id": trial_id,
                "prompt_version": prompt_version,
                "model_name": self.settings.model_name,
                "total_examples": total,
            },
            metrics={
                "category_accuracy": category_accuracy,
                "priority_accuracy": priority_accuracy,
                "requires_human_accuracy": requires_human_accuracy,
                "risk_type_accuracy": risk_type_accuracy,
                "average_cost": average_cost,
                "average_latency_ms": average_latency_ms,
                "total_cost": round(sum(costs), 8),
                "total_input_tokens": sum(input_tokens),
                "total_output_tokens": sum(output_tokens),
                "total_tokens": sum(total_tokens),
                "average_total_tokens": self._average(total_tokens),
            },
            artifacts={
                "eval_results.json": results,
                "eval_tickets.json": examples,
            },
        )
        return response

    def _accuracy(self, results: list[dict], field: str) -> float:
        expected_field = f"expected_{field}"
        correct = 0
        for item in results:
            if item["response"].get(field) == item["example"].get(expected_field):
                correct += 1
        return round(correct / max(len(results), 1), 4)

    def _average(self, values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 8)
