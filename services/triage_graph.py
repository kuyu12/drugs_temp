from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.schemas import TicketAnalysis, TriageRequest
from app.services.guardrails import GuardrailResult, GuardrailsService
from app.services.llm_service import ModelTokenUsage, PromptRepository, TicketLLMService


class TriageGraphState(TypedDict, total=False):
    request: TriageRequest
    prompt_text: str
    rendered_prompt: str
    guardrail: GuardrailResult
    guardrail_output: str | None
    guardrail_token_usage: ModelTokenUsage | None
    analysis: TicketAnalysis
    model_output: str | None
    triage_token_usage: ModelTokenUsage | None
    status: Literal["success", "blocked"]


class TicketTriageGraph:
    """LangGraph workflow for prompt rendering, guardrails, and ticket analysis."""

    def __init__(
        self,
        prompts: PromptRepository,
        guardrails: GuardrailsService,
        llm: TicketLLMService,
    ) -> None:
        self.prompts = prompts
        self.guardrails = guardrails
        self.llm = llm
        self.graph = self._build_graph()

    def invoke(self, request: TriageRequest) -> TriageGraphState:
        return self.graph.invoke({"request": request})

    def _build_graph(self) -> Any:
        graph_builder = StateGraph(TriageGraphState)
        graph_builder.add_node("render_prompt", self._render_prompt)
        graph_builder.add_node("run_guardrails", self._run_guardrails)
        graph_builder.add_node("run_triage", self._run_triage)

        graph_builder.add_edge(START, "render_prompt")
        graph_builder.add_edge("render_prompt", "run_guardrails")
        graph_builder.add_conditional_edges(
            "run_guardrails",
            self._route_after_guardrails,
            {
                "run_triage": "run_triage",
                "blocked": END,
            },
        )
        graph_builder.add_edge("run_triage", END)
        return graph_builder.compile()

    def _render_prompt(self, state: TriageGraphState) -> dict[str, str]:
        request = state["request"]
        prompt_text, rendered_prompt = self.prompts.render(
            request.prompt_version,
            request.customer_message,
        )
        return {
            "prompt_text": prompt_text,
            "rendered_prompt": rendered_prompt,
        }

    def _run_guardrails(self, state: TriageGraphState) -> dict[str, Any]:
        request = state["request"]
        guardrail = self.guardrails.check(request.customer_message)
        status: Literal["success", "blocked"] = "success" if guardrail.allowed else "blocked"
        return {
            "guardrail": guardrail,
            "guardrail_output": guardrail.raw_output,
            "guardrail_token_usage": guardrail.token_usage,
            "status": status,
        }

    def _route_after_guardrails(self, state: TriageGraphState) -> str:
        guardrail = state["guardrail"]
        return "run_triage" if guardrail.allowed else "blocked"

    def _run_triage(self, state: TriageGraphState) -> dict[str, Any]:
        request = state["request"]
        analysis, raw_output, token_usage = self.llm.analyze(
            state["rendered_prompt"],
            request.customer_message,
            request.prompt_version,
        )
        return {
            "analysis": analysis,
            "model_output": raw_output,
            "triage_token_usage": token_usage,
            "status": "success",
        }
