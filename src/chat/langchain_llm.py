from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, PrivateAttr

from src.chat.llm import LLMProvider, get_provider


class ProviderBackedChatModel(BaseChatModel):
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
