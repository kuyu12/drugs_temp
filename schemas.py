from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Category(StrEnum):
    SHIPPING = "shipping"
    REFUND = "refund"
    BILLING = "billing"
    TECHNICAL_SUPPORT = "technical_support"
    ACCOUNT_ACCESS = "account_access"
    PRIVACY = "privacy"
    COMPLAINT = "complaint"
    OTHER = "other"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    ANGRY = "angry"


class RiskType(StrEnum):
    NONE = "none"
    FINANCIAL = "financial"
    LEGAL = "legal"
    PRIVACY = "privacy"
    SECURITY = "security"
    BRAND = "brand"


class TriageRequest(BaseModel):
    customer_message: str = Field(..., max_length=4000)
    prompt_version: Literal["v1", "v2"] = "v1"


class TicketAnalysis(BaseModel):
    category: Category
    priority: Priority
    sentiment: Sentiment
    requires_human: bool
    risk_type: RiskType
    suggested_reply: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)


class GuardrailDecision(BaseModel):
    allowed: bool = Field(..., description="True when the request is safe to continue to ticket triage.")
    reason: str | None = Field(
        default=None,
        description="Machine-readable reason when blocked, for example prompt_injection_detected.",
    )
    safe_response: str | None = Field(
        default=None,
        description="Short safe response to return to the customer when blocked.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)


class TriageSuccessResponse(TicketAnalysis):
    status: Literal["success"] = "success"
    run_id: str


class BlockedResponse(BaseModel):
    status: Literal["blocked"] = "blocked"
    reason: str
    safe_response: str
    run_id: str


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error_type: str
    message: str
    run_id: str | None = None


class CostSummaryResponse(BaseModel):
    total_runs: int
    successful_runs: int
    blocked_runs: int
    total_cost: float
    average_cost_per_run: float
    average_latency_ms: float
    most_expensive_run_id: str | None


class RunSummary(BaseModel):
    run_id: str
    timestamp: str
    prompt_version: str
    status: str
    category: str | None
    priority: str | None
    estimated_cost: float
    latency_ms: float


class MetricsSummaryResponse(BaseModel):
    total_requests: int
    successful_requests: int
    blocked_requests: int
    error_requests: int
    average_latency_ms: float
    average_cost: float
    high_priority_rate: float
    human_escalation_rate: float
    most_common_category: str | None


class EvaluationRequest(BaseModel):
    prompt_version: Literal["v1", "v2"] = "v1"


class EvaluationResponse(BaseModel):
    trial_id: str
    prompt_version: str
    total_examples: int
    category_accuracy: float
    priority_accuracy: float
    requires_human_accuracy: float
    risk_type_accuracy: float
    average_cost: float
    average_latency_ms: float
