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
    except Exception as exc: 
        log_event(logger, 40, "langfuse_client_init_failed", error=str(exc))
        _client = None
    return _client


@contextmanager
def log_llm_generation(name: str, model: str, input_text: str, metadata: dict | None = None):
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
