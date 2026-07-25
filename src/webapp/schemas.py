"""Pydantic request/response models for the JSON API routes.

Before this, /api/chat took a raw `payload: dict` — no validation, no
OpenAPI schema, and a missing field surfaced as an unhandled KeyError (500)
instead of a clean 422. The HTML-form routes (/run, /markup/download) stay
on FastAPI's Form(...) params, which already validate — schemas here cover
the JSON API surface specifically.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    pid_a: str = Field(..., min_length=1, description="Base revision PID")
    pid_b: str = Field(..., min_length=1, description="Revised revision PID")
    question: str = Field(..., min_length=1, description="The question to answer, grounded in pid_a/pid_b/the delta")
    session_id: str | None = Field(None, description="Chat session id for multi-turn history; generated if omitted")
    agentic: bool | None = Field(
        None,
        description="Use the LangGraph retrieve->answer->verify->retry pipeline instead of the single-round-trip "
        "default. Omit to use settings.chat_backend.",
    )


class ChatResponse(BaseModel):
    answer: str
    grounded: bool
    citations: list[str]
    model: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    request_id: str
    session_id: str
    verified: bool | None = None
    attempts: int | None = None


class VersionResponse(BaseModel):
    version: str
