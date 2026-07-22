from dataclasses import dataclass


@dataclass(frozen=True)
class AuditRecord:
    run_id: str
    timestamp: str
    customer_message: str
    prompt_version: str
    guardrail_status: str
    guardrail_reason: str | None
    model_name: str
    model_output: str | None
    final_response: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float
    latency_ms: float
    status: str
    category: str | None = None
    priority: str | None = None
    risk_type: str | None = None
    requires_human: bool | None = None
    confidence: float | None = None

