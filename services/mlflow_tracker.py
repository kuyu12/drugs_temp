import json
from typing import Any

import mlflow
import mlflow.langchain


class MLflowTracker:
    """Logs triage runs and evaluation trials to MLflow."""

    def __init__(self, tracking_uri: str, experiment_name: str) -> None:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment_name)
        mlflow.langchain.autolog(
            log_traces=True,
            silent=True,
        )

    def log_triage_run(
        self,
        *,
        params: dict[str, Any],
        metrics: dict[str, float],
        artifacts: dict[str, Any],
    ) -> str:
        with mlflow.start_run(run_name="triage-request") as run:
            mlflow.set_tag("run_type", "triage")
            mlflow.log_params(self._clean_params(params))
            mlflow.log_metrics(self._clean_metrics(metrics))
            self._log_artifacts(artifacts)
            return run.info.run_id

    def log_evaluation_trial(
        self,
        *,
        trial_id: str,
        params: dict[str, Any],
        metrics: dict[str, float],
        artifacts: dict[str, Any],
    ) -> str:
        with mlflow.start_run(run_name=f"trial-{trial_id}") as run:
            mlflow.set_tag("run_type", "evaluation")
            mlflow.log_params(self._clean_params(params))
            mlflow.log_metrics(self._clean_metrics(metrics))
            self._log_artifacts(artifacts)
            return run.info.run_id

    def _log_artifacts(self, artifacts: dict[str, Any]) -> None:
        for filename, content in artifacts.items():
            if isinstance(content, str):
                text = content
            else:
                text = json.dumps(content, indent=2)
            mlflow.log_text(text, filename)

    def _clean_params(self, params: dict[str, Any]) -> dict[str, str | int | float | bool]:
        return {
            key: value
            for key, value in params.items()
            if value is not None and isinstance(value, str | int | float | bool)
        }

    def _clean_metrics(self, metrics: dict[str, Any]) -> dict[str, float]:
        return {
            key: float(value)
            for key, value in metrics.items()
            if value is not None
        }
