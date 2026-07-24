"""Langfuse: LLM-specific observability (prompts, completions, token usage,
cost per call), complementing — not replacing — the homegrown tracer
(tracing.py). The distinction matters: tracing.py covers the whole request
(ingest -> delta -> retrieve -> llm -> answer) with zero external
dependencies and is what every trace file/check script relies on; Langfuse
is specifically the LLM-call layer (prompt/completion/token/cost detail,
a searchable UI across every generation ever made, prompt-version
comparison) that a homegrown per-request JSON file doesn't give you at
scale — the tool this project's own README named as future work under
"served dashboard."

A strict no-op when LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY aren't set —
chat/answer.py calls into this unconditionally; it should never be the
reason a chat request needs Langfuse configured to work.

Not yet verified against a live Langfuse project (no key was available
while writing this — see chat history); the client construction and
generation-logging calls are written against the installed langfuse==4.14.1
SDK's actual signatures (checked via introspection, not assumed), so this
should work as soon as a real key is supplied, but treat it as unverified
until then, same as the Pinecone integration.
"""

from __future__ import annotations

from contextlib import contextmanager

from src.config import settings
from src.observability.logging import get_logger, log_event

logger = get_logger("observability.langfuse")

_client = None
_client_init_attempted = False


def get_langfuse_client():
    global _client, _client_init_attempted
    if _client_init_attempted:
        return _client
    _client_init_attempted = True

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        log_event(logger, 20, "langfuse_client_initialized", host=settings.langfuse_host)
    except Exception as exc:  # noqa: BLE001
        log_event(logger, 40, "langfuse_client_init_failed", error=str(exc))
        _client = None
    return _client


@contextmanager
def log_llm_generation(name: str, model: str, input_text: str, metadata: dict | None = None):
    """Wraps one LLM call. Yields an object with `.finish(output, usage, cost)`
    — a no-op stand-in when Langfuse isn't configured, so call sites never
    need an `if langfuse_enabled:` branch."""
    client = get_langfuse_client()

    if client is None:
        yield _NullGeneration()
        return

    generation = client.start_observation(
        name=name, as_type="generation", input=input_text, model=model, metadata=metadata or {},
    )
    try:
        yield _LangfuseGenerationHandle(generation)
    finally:
        generation.end()


class _LangfuseGenerationHandle:
    def __init__(self, generation):
        self._generation = generation

    def finish(self, output: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        self._generation.update(
            output=output,
            usage_details={"input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens},
            cost_details={"total": cost_usd},
        )


class _NullGeneration:
    def finish(self, output: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        pass
