"""Provider-agnostic LLM client.

Swappable behind one interface (`LLMProvider.complete`); provider + model
are config, not hardcoded (src/config.py, env vars). Three providers ship:

  - AnthropicProvider (Claude) — used when ANTHROPIC_API_KEY is set.
  - OpenAIProvider (GPT) — used when LLM_PROVIDER=openai and OPENAI_API_KEY is set.
  - MockProvider — deterministic, zero-cost, no-network fallback used when no
    key is configured, so `make run` / `make eval` stay runnable out of the
    box for grading. It does NOT fabricate a generative answer: it extracts
    and lists the retrieved, cited snippets verbatim, clearly labeled as a
    mock response. This keeps the offline path honest instead of silently
    pretending to be a real model.

This is the one place in the system where output is non-deterministic
(real providers) — isolated here deliberately, so the delta engine's
structural output upstream stays reproducible regardless of which LLM
answers a chat question.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.config import settings
from src.observability.logging import get_logger, log_event

logger = get_logger("chat.llm")


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = settings.pricing.get(model)
    if not price:
        return 0.0
    return round((input_tokens / 1_000_000) * price["input"] + (output_tokens / 1_000_000) * price["output"], 6)


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(self, system: str, user: str) -> LLMResponse: ...


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self):
        import anthropic

        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    def complete(self, system: str, user: str) -> LLMResponse:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text"))
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cost_usd=_estimate_cost(self.model, resp.usage.input_tokens, resp.usage.output_tokens),
        )


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self):
        from openai import OpenAI

        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    def complete(self, system: str, user: str) -> LLMResponse:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_usd=_estimate_cost(self.model, usage.prompt_tokens, usage.completion_tokens),
        )


class MockProvider(LLMProvider):
    """No-network, zero-cost fallback. Extracts the retrieved context block
    out of the user prompt (see chat/answer.py's prompt template) and
    returns it as a labeled, cited bullet list instead of fabricating prose
    — deterministic and honest about not being a real model."""

    name = "mock"

    def complete(self, system: str, user: str) -> LLMResponse:
        context_block = ""
        if "<context>" in user and "</context>" in user:
            context_block = user.split("<context>", 1)[1].split("</context>", 1)[0].strip()
        question = ""
        if "<question>" in user and "</question>" in user:
            question = user.split("<question>", 1)[1].split("</question>", 1)[0].strip()

        if not context_block:
            text = (
                "[MOCK LLM — no ANTHROPIC_API_KEY/OPENAI_API_KEY configured] "
                "No retrieved context was available to ground an answer to: "
                f"\"{question}\". I don't have supporting evidence to answer this."
            )
        else:
            snippets = [line for line in context_block.splitlines() if line.strip()][: settings.retrieval_top_k]
            bullets = "\n".join(f"- {s}" for s in snippets)
            text = (
                "[MOCK LLM — no ANTHROPIC_API_KEY/OPENAI_API_KEY configured; this is a "
                "template extractive answer over retrieved, cited context, not a generated one]\n"
                f"Question: {question}\n"
                f"Most relevant retrieved evidence:\n{bullets}"
            )
        input_tokens = (len(system) + len(user)) // 4
        output_tokens = len(text) // 4
        return LLMResponse(text=text, model="mock", input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=0.0)


def get_provider() -> LLMProvider:
    provider = settings.llm_provider.lower()
    try:
        if provider == "anthropic" and settings.anthropic_api_key:
            return AnthropicProvider()
        if provider == "openai" and settings.openai_api_key:
            return OpenAIProvider()
        if provider not in ("anthropic", "openai", "mock"):
            log_event(logger, 30, "unknown_llm_provider_falling_back_to_mock", configured=provider)
    except Exception as exc:  # noqa: BLE001
        log_event(logger, 40, "llm_provider_init_failed_falling_back_to_mock", provider=provider, error=str(exc))
        return MockProvider()

    log_event(logger, 30, "no_llm_api_key_using_mock_provider", configured_provider=provider)
    return MockProvider()
