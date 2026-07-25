"""Agentic grounded chat: retrieve -> answer -> verify citations -> retry.

This is an additive alternative to chat/answer.py's single-round-trip
pipeline, not a replacement for it (see settings.chat_backend). Where
chat/answer.py trusts the LLM's citations at face value, this pipeline adds
one real self-correction step on top: after the LLM answers, every citation
label it used is checked against the citation labels of chunks that were
actually retrieved. An LLM can hallucinate a citation that *looks* like the
project's `[pid_a:...]` / `[delta:...]` format without it corresponding to
anything retrieved for this question — that's exactly the failure mode this
catches. On a failed verification, retrieval is widened (more chunks, lower
score floor) and the question is re-answered, up to
settings.agentic_max_retries times, before giving up and returning the last
answer produced.

Built as a small LangGraph StateGraph (retrieve -> generate -> verify, with
verify looping back to retrieve on failure) rather than a hand-rolled while
loop: the state machine shape is what LangGraph is for, and it's what makes
this pipeline meaningfully different from chat/answer.py rather than the
same logic re-typed with an extra dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from src.chat.answer import CITATION_RE, SYSTEM_PROMPT, AnswerResult, RetrievedEvidence, _format_context
from src.chat.index import Chunk, RetrievalIndex
from src.chat.langchain_llm import ProviderBackedChatModel
from src.chat.llm import LLMProvider
from src.config import settings
from src.observability.langfuse_tracing import log_llm_generation
from src.observability.logging import get_logger, log_event
from src.observability.prometheus_metrics import LLM_CALLS_TOTAL, LLM_COST_USD_TOTAL, LLM_TOKENS_TOTAL
from src.observability.tracing import Trace

logger = get_logger("chat.agentic")


@dataclass
class AgenticAnswerResult(AnswerResult):
    """AnswerResult plus the bookkeeping unique to the agentic pipeline. A
    subclass, not a change to AnswerResult itself: chat/answer.py and its
    callers stay exactly as they are, this only adds fields for the code
    paths that know to look for them."""

    attempts: int = 1
    verified: bool = True
    verification_notes: list[str] = field(default_factory=list)


class _State(TypedDict):
    query: str
    attempt: int
    widened: bool
    hits: list[tuple[Chunk, float]]
    result: AgenticAnswerResult | None
    done: bool


def _verify_citations(citations_used: list[str], hits: list[tuple[Chunk, float]]) -> list[str]:
    """Every citation label the LLM used must belong to a chunk that was
    actually retrieved for this question — catches a fabricated-looking
    citation (right format, wrong/no source) that chat/answer.py's simple
    pipeline has no way to notice."""
    valid_labels = {chunk.citation.label() for chunk, _ in hits}
    return [label for label in citations_used if label not in valid_labels]


def answer_question_agentic(
    query: str,
    index: RetrievalIndex,
    trace: Trace,
    provider: LLMProvider | None = None,
) -> AgenticAnswerResult:
    chat_model = ProviderBackedChatModel(provider=provider)
    max_retries = settings.agentic_max_retries

    def node_retrieve(state: _State) -> _State:
        widen = state["widened"]
        top_k = settings.retrieval_top_k * (3 if widen else 1)
        min_score = settings.retrieval_min_score / (2 if widen else 1)
        with trace.span("agentic_retrieve", attempt=state["attempt"], widened=widen) as span:
            hits = index.search(state["query"], top_k=top_k, min_score=min_score)
            span.attrs["num_hits"] = len(hits)
            span.attrs["top_score"] = hits[0][1] if hits else 0.0
        return {**state, "hits": hits}

    def node_generate(state: _State) -> _State:
        hits = state["hits"]
        if not hits:
            log_event(logger, 20, "agentic_no_grounding_evidence", query=state["query"], attempt=state["attempt"])
            with trace.span("agentic_answer", grounded=False, attempt=state["attempt"]):
                pass
            result = AgenticAnswerResult(
                answer="I don't have grounded evidence to answer that — nothing in PID A, PID B, "
                "or the delta report matched this question closely enough.",
                grounded=False,
                attempts=state["attempt"] + 1,
                verified=True,
            )
            return {**state, "result": result, "done": True}

        context = _format_context(hits)
        user_prompt = f"<context>\n{context}\n</context>\n\n<question>\n{state['query']}\n</question>"

        try:
            with trace.span("agentic_llm_call", provider=chat_model.provider.name, attempt=state["attempt"]) as span:
                with log_llm_generation(
                    "agentic_chat_answer", model=chat_model.provider.name, input_text=user_prompt,
                    metadata={"query": state["query"], "attempt": state["attempt"]},
                ) as generation:
                    ai_message = chat_model.invoke([SystemMessage(SYSTEM_PROMPT), HumanMessage(user_prompt)])
                    meta = ai_message.response_metadata
                    generation.finish(
                        output=ai_message.content, input_tokens=meta["input_tokens"],
                        output_tokens=meta["output_tokens"], cost_usd=meta["cost_usd"],
                    )
                span.attrs.update(meta)
                LLM_TOKENS_TOTAL.labels(provider=meta["provider"], direction="input").inc(meta["input_tokens"])
                LLM_TOKENS_TOTAL.labels(provider=meta["provider"], direction="output").inc(meta["output_tokens"])
                LLM_COST_USD_TOTAL.labels(provider=meta["provider"]).inc(meta["cost_usd"])
        except Exception as exc:  # noqa: BLE001 - same boundary as chat/answer.py: degrade, don't crash
            log_event(
                logger, 40, "agentic_llm_call_failed", query=state["query"], attempt=state["attempt"], error=str(exc),
            )
            with trace.span("agentic_answer", grounded=False, attempt=state["attempt"], llm_error=True):
                pass
            result = AgenticAnswerResult(
                answer=f"The LLM provider call failed ({type(exc).__name__}: {exc}). "
                f"Retrieval found {len(hits)} relevant source(s), but no answer could be generated — "
                "see the trace file for details.",
                grounded=False,
                retrieved=[RetrievedEvidence(chunk=c, score=s) for c, s in hits],
                attempts=state["attempt"] + 1,
                verified=True,
            )
            return {**state, "result": result, "done": True}

        text = ai_message.content
        citations_used = [m.group(0) for m in CITATION_RE.finditer(text)]
        grounded = len(citations_used) > 0 and "don't have grounded evidence" not in text.lower()
        LLM_CALLS_TOTAL.labels(provider=meta["provider"], grounded=str(grounded)).inc()

        result = AgenticAnswerResult(
            answer=text,
            grounded=grounded,
            citations_used=citations_used,
            retrieved=[RetrievedEvidence(chunk=c, score=s) for c, s in hits],
            model=meta["model"],
            input_tokens=meta["input_tokens"],
            output_tokens=meta["output_tokens"],
            cost_usd=meta["cost_usd"],
            attempts=state["attempt"] + 1,
        )
        return {**state, "result": result, "done": False}

    def node_verify(state: _State) -> _State:
        result = state["result"]
        assert result is not None  # only reached when node_generate produced an answer to check

        if not result.grounded:
            # A hedge ("no grounded evidence") has no citations to verify —
            # it's already the correct, honest answer.
            with trace.span("agentic_verify", attempt=state["attempt"], passed=True, reason="hedge"):
                pass
            result.verified = True
            return {**state, "done": True}

        problems = _verify_citations(result.citations_used, state["hits"])
        passed = not problems
        with trace.span("agentic_verify", attempt=state["attempt"], passed=passed, num_problems=len(problems)):
            pass

        result.verified = passed
        result.verification_notes = problems

        if passed:
            return {**state, "done": True}

        if state["attempt"] >= max_retries:
            log_event(
                logger, 30, "agentic_verification_failed_max_retries",
                query=state["query"], attempt=state["attempt"], problems=problems,
            )
            return {**state, "done": True}

        log_event(
            logger, 20, "agentic_verification_failed_retrying",
            query=state["query"], attempt=state["attempt"], problems=problems,
        )
        return {**state, "attempt": state["attempt"] + 1, "widened": True, "done": False}

    def route_after_generate(state: _State) -> str:
        return END if state["done"] else "verify"

    def route_after_verify(state: _State) -> str:
        return END if state["done"] else "retrieve"

    graph = StateGraph(_State)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("generate", node_generate)
    graph.add_node("verify", node_verify)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_conditional_edges("generate", route_after_generate, {"verify": "verify", END: END})
    graph.add_conditional_edges("verify", route_after_verify, {"retrieve": "retrieve", END: END})
    app = graph.compile()

    final_state: _State = app.invoke(
        {"query": query, "attempt": 0, "widened": False, "hits": [], "result": None, "done": False},
        config={"recursion_limit": (max_retries + 2) * 4},
    )

    result = final_state["result"]
    assert result is not None
    log_event(
        logger, 20, "agentic_answer_produced",
        query=query, grounded=result.grounded, verified=result.verified, attempts=result.attempts,
    )
    return result
