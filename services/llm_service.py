import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.prompts import PromptTemplate

from app.schemas import TicketAnalysis


class PromptRepository:
    """Loads prompt versions from plain text files."""

    def __init__(self, prompt_dir: Path) -> None:
        self.prompt_dir = prompt_dir

    def get_prompt_text(self, prompt_version: str) -> str:
        prompt_path = self.prompt_dir / f"ticket_triage_{prompt_version}.txt"
        if not prompt_path.exists():
            raise ValueError(f"Unknown prompt version: {prompt_version}")
        return prompt_path.read_text(encoding="utf-8")

    def render(self, prompt_version: str, customer_message: str) -> tuple[str, str]:
        prompt_text = self.get_prompt_text(prompt_version)
        prompt = PromptTemplate.from_template(prompt_text).format(
            customer_message=customer_message
        )
        return prompt_text, prompt


@dataclass(frozen=True)
class ModelTokenUsage:
    input_tokens: int
    output_tokens: int


class TicketLLMService:
    """LangChain structured-output chain for the final ticket analysis."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def analyze(
        self,
        prompt: str,
        customer_message: str,
        prompt_version: str,
    ) -> tuple[TicketAnalysis, str, ModelTokenUsage | None]:
        result = self._call_model(prompt)
        token_usage = self._extract_token_usage(result.get("raw"))
        parsing_error = result.get("parsing_error")
        if parsing_error is not None:
            raise InvalidModelOutputError(str(result.get("raw")), token_usage) from parsing_error

        analysis = result.get("parsed")
        if not isinstance(analysis, TicketAnalysis):
            raise InvalidModelOutputError(str(result.get("raw")), token_usage)
        raw_output = analysis.model_dump_json()
        return analysis, raw_output, token_usage

    def _call_model(self, prompt: str) -> dict[str, Any]:
        if not os.getenv("OPENAI_API_KEY"):
            raise LLMCallError(
                "OPENAI_API_KEY is not configured in the API container. "
                "Create a .env file and recreate the api service."
            )

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise LLMCallError("Install langchain-openai to call OpenAI models.") from exc

        try:
            model = ChatOpenAI(
                model=self.model_name,
                temperature=0,
            )
            response = model.with_structured_output(
                TicketAnalysis,
                include_raw=True,
            ).invoke(prompt)
        except Exception as exc:
            raise LLMCallError(
                f"OpenAI request failed: {format_llm_exception(exc)}"
            ) from exc
        return response

    def _extract_token_usage(self, response: Any) -> ModelTokenUsage | None:
        if response is None:
            return None
        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata:
            return ModelTokenUsage(
                input_tokens=int(usage_metadata.get("input_tokens", 0)),
                output_tokens=int(usage_metadata.get("output_tokens", 0)),
            )

        response_metadata = getattr(response, "response_metadata", {}) or {}
        token_usage = response_metadata.get("token_usage")
        if token_usage:
            return ModelTokenUsage(
                input_tokens=int(token_usage.get("prompt_tokens", 0)),
                output_tokens=int(token_usage.get("completion_tokens", 0)),
            )
        return None


class InvalidModelOutputError(Exception):
    def __init__(self, raw_output: str, token_usage: ModelTokenUsage | None) -> None:
        super().__init__("The model returned an invalid response format.")
        self.raw_output = raw_output
        self.token_usage = token_usage


class LLMCallError(Exception):
    pass


def format_llm_exception(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    if not message:
        message = "No error details returned."
    return f"{type(exc).__name__}: {message}"
