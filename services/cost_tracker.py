from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float
    cost_source: Literal["litellm", "configured_fallback", "unavailable"]


class CostTracker:
    """Calculates cost from provider token usage.

    Token counts should come from the model provider metadata. Cost is calculated
    with LiteLLM's model pricing table, with local configured prices as fallback.
    """

    def __init__(self, model_name: str, input_token_cost: float, output_token_cost: float) -> None:
        self.model_name = model_name
        self.input_token_cost = input_token_cost
        self.output_token_cost = output_token_cost

    def zero(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated_cost=0,
            cost_source="unavailable",
        )

    def from_counts(self, input_tokens: int, output_tokens: int) -> TokenUsage:
        estimated_cost, cost_source = self._calculate_cost(input_tokens, output_tokens)
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            estimated_cost=round(estimated_cost, 8),
            cost_source=cost_source,
        )

    def from_optional_counts(
        self,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> TokenUsage:
        if input_tokens is None or output_tokens is None:
            return self.zero()
        return self.from_counts(input_tokens, output_tokens)

    def _calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[float, Literal["litellm", "configured_fallback"]]:
        try:
            from litellm import cost_per_token

            input_cost, output_cost = cost_per_token(
                model=self.model_name,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
            )
            return float(input_cost) + float(output_cost), "litellm"
        except Exception:
            configured_cost = (
                input_tokens * self.input_token_cost
                + output_tokens * self.output_token_cost
            )
            return configured_cost, "configured_fallback"
