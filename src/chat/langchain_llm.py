"""LangChain-compatible wrapper around the existing provider-agnostic
LLMProvider (src/chat/llm.py).

This is deliberately NOT a second LLM integration: it owns no API keys, no
retry logic, no cost math — it delegates every call straight to
LLMProvider.complete and republishes the result as a LangChain AIMessage.
That keeps chat/llm.py the single place provider selection, the mock/no-key
fallback, and token/cost telemetry live, while giving LangGraph nodes
(src/chat/agentic.py) the message-based interface LangGraph expects.
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, PrivateAttr

from src.chat.llm import LLMProvider, get_provider


class ProviderBackedChatModel(BaseChatModel):
    """Adapts LLMProvider.complete(system, user) -> LangChain's
    messages-in/AIMessage-out shape. Only system + human messages are
    supported (this project's chat is single-turn retrieve-then-answer, not
    multi-turn conversation), which matches exactly what chat/answer.py's
    SYSTEM_PROMPT + <context>/<question> prompt already assumes.

    Token counts and cost stay attached to the returned AIMessage via
    response_metadata rather than a side-channel attribute, so they survive
    however LangGraph/LangChain chooses to pass the message along.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _provider: LLMProvider = PrivateAttr()

    def __init__(self, provider: LLMProvider | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._provider = provider or get_provider()

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @property
    def _llm_type(self) -> str:
        return f"provider-backed:{self._provider.name}"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system = "\n".join(str(m.content) for m in messages if m.type == "system")
        user = "\n".join(str(m.content) for m in messages if m.type == "human")

        resp = self._provider.complete(system, user)

        message = AIMessage(
            content=resp.text,
            response_metadata={
                "model": resp.model,
                "provider": self._provider.name,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "cost_usd": resp.cost_usd,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
