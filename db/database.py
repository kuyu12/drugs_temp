import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.db.models import AuditRecord


class AuditLogRepository:
    """Small PostgreSQL repository for audit and monitoring queries."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_runs (
                    run_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    customer_message TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    guardrail_status TEXT NOT NULL,
                    guardrail_reason TEXT,
                    model_name TEXT NOT NULL,
                    model_output TEXT,
                    final_response TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    estimated_cost DOUBLE PRECISION NOT NULL,
                    latency_ms DOUBLE PRECISION NOT NULL,
                    status TEXT NOT NULL,
                    category TEXT,
                    priority TEXT,
                    risk_type TEXT,
                    requires_human BOOLEAN,
                    confidence DOUBLE PRECISION
                )
                """
            )

    def save(self, record: AuditRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_runs (
                    run_id, timestamp, customer_message, prompt_version,
                    guardrail_status, guardrail_reason, model_name, model_output,
                    final_response, input_tokens, output_tokens, total_tokens,
                    estimated_cost, latency_ms, status, category, priority,
                    risk_type, requires_human, confidence
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    timestamp = EXCLUDED.timestamp,
                    customer_message = EXCLUDED.customer_message,
                    prompt_version = EXCLUDED.prompt_version,
                    guardrail_status = EXCLUDED.guardrail_status,
                    guardrail_reason = EXCLUDED.guardrail_reason,
                    model_name = EXCLUDED.model_name,
                    model_output = EXCLUDED.model_output,
                    final_response = EXCLUDED.final_response,
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens,
                    total_tokens = EXCLUDED.total_tokens,
                    estimated_cost = EXCLUDED.estimated_cost,
                    latency_ms = EXCLUDED.latency_ms,
                    status = EXCLUDED.status,
                    category = EXCLUDED.category,
                    priority = EXCLUDED.priority,
                    risk_type = EXCLUDED.risk_type,
                    requires_human = EXCLUDED.requires_human,
                    confidence = EXCLUDED.confidence
                """,
                (
                    record.run_id,
                    record.timestamp,
                    record.customer_message,
                    record.prompt_version,
                    record.guardrail_status,
                    record.guardrail_reason,
                    record.model_name,
                    record.model_output,
                    record.final_response,
                    record.input_tokens,
                    record.output_tokens,
                    record.total_tokens,
                    record.estimated_cost,
                    record.latency_ms,
                    record.status,
                    record.category,
                    record.priority,
                    record.risk_type,
                    record.requires_human,
                    record.confidence,
                ),
            )

    def list_recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, timestamp, prompt_version, status, category, priority,
                       estimated_cost, latency_ms
                FROM audit_runs
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return rows

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM audit_runs WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        if row is None:
            return None

        result = row
        result["final_response"] = json.loads(result["final_response"])
        if result["model_output"]:
            try:
                result["model_output"] = json.loads(result["model_output"])
            except json.JSONDecodeError:
                pass
        return result

    def cost_summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_runs,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful_runs,
                    SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked_runs,
                    COALESCE(SUM(estimated_cost), 0) AS total_cost,
                    COALESCE(AVG(estimated_cost), 0) AS average_cost_per_run,
                    COALESCE(AVG(latency_ms), 0) AS average_latency_ms
                FROM audit_runs
                """
            ).fetchone()
            expensive = connection.execute(
                """
                SELECT run_id
                FROM audit_runs
                ORDER BY estimated_cost DESC
                LIMIT 1
                """
            ).fetchone()

        result = dict(row)
        result["successful_runs"] = result["successful_runs"] or 0
        result["blocked_runs"] = result["blocked_runs"] or 0
        result["most_expensive_run_id"] = None if expensive is None else expensive["run_id"]
        return result

    def metrics_summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_requests,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful_requests,
                    SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked_requests,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_requests,
                    COALESCE(AVG(latency_ms), 0) AS average_latency_ms,
                    COALESCE(AVG(estimated_cost), 0) AS average_cost,
                    COALESCE(AVG(CASE WHEN priority = 'high' THEN 1.0 ELSE 0.0 END), 0) AS high_priority_rate,
                    COALESCE(AVG(CASE WHEN requires_human IS TRUE THEN 1.0 ELSE 0.0 END), 0) AS human_escalation_rate
                FROM audit_runs
                """
            ).fetchone()
            category = connection.execute(
                """
                SELECT category
                FROM audit_runs
                WHERE category IS NOT NULL
                GROUP BY category
                ORDER BY COUNT(*) DESC
                LIMIT 1
                """
            ).fetchone()

        result = row
        result["successful_requests"] = result["successful_requests"] or 0
        result["blocked_requests"] = result["blocked_requests"] or 0
        result["error_requests"] = result["error_requests"] or 0
        result["most_common_category"] = None if category is None else category["category"]
        return result

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)
