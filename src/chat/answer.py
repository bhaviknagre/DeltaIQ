"""Grounded chat: retrieve -> prompt -> LLM -> parse citations.

Every answer must cite specific sources using the exact bracketed citation
labels handed to it in context (e.g. `[pid_a:demo-native-a@p0]` or
`[delta:mod-abc123-def456]`). If retrieval finds nothing above the
confidence floor, the LLM is never even called — the system hedges
directly, which is the cheapest and most reliable way to avoid
hallucinating an answer with no supporting evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.chat.index import Chunk, RetrievalIndex
from src.chat.llm import LLMProvider, get_provider
from src.config import settings
from src.observability.logging import get_logger, log_event
from src.observability.tracing import Trace

logger = get_logger("chat.answer")

SYSTEM_PROMPT = """You are a grounded assistant answering questions about two revisions of an \
engineering document (PID A = base revision, PID B = revised revision) and a delta report \
summarizing what changed between them.

Rules:
1. Answer ONLY using the evidence given inside <context>...</context>. Do not use outside knowledge \
about P&IDs, compressors, or this domain beyond what's in the context.
2. Every factual claim must end with the exact bracketed citation label(s) from the context that \
support it, e.g. "The line size changed to 1\" [delta:mod-abc123-def456]."
3. If the context does not contain enough evidence to answer, say so plainly: \
"I don't have grounded evidence to answer that." Do not guess or fabricate a citation.
4. Be concise and specific — prefer exact tag/value names over vague summaries."""

CITATION_RE = re.compile(r"\[(pid_a|pid_b|delta_report|delta):[^\]]+\]")


@dataclass
class RetrievedEvidence:
    chunk: Chunk
    score: float


@dataclass
class AnswerResult:
    answer: str
    grounded: bool
    citations_used: list[str] = field(default_factory=list)
    retrieved: list[RetrievedEvidence] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def _format_context(hits: list[tuple[Chunk, float]]) -> str:
    lines = []
    for chunk, score in hits:
        lines.append(f"{chunk.citation.label()} {chunk.text}")
    return "\n".join(lines)


def answer_question(
    query: str,
    index: RetrievalIndex,
    trace: Trace,
    provider: LLMProvider | None = None,
) -> AnswerResult:
    provider = provider or get_provider()

    with trace.span("retrieve", query=query) as span:
        hits = index.search(query, top_k=settings.retrieval_top_k, min_score=settings.retrieval_min_score)
        span.attrs["num_hits"] = len(hits)
        span.attrs["top_score"] = hits[0][1] if hits else 0.0

    if not hits:
        log_event(logger, 30, "no_grounding_evidence", query=query)
        with trace.span("answer", grounded=False):
            pass
        return AnswerResult(
            answer="I don't have grounded evidence to answer that — nothing in PID A, PID B, "
            "or the delta report matched this question closely enough.",
            grounded=False,
        )

    context = _format_context(hits)
    user_prompt = f"<context>\n{context}\n</context>\n\n<question>\n{query}\n</question>"

    with trace.span("llm_call", provider=provider.name) as span:
        resp = provider.complete(SYSTEM_PROMPT, user_prompt)
        span.attrs.update(
            {
                "model": resp.model,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "cost_usd": resp.cost_usd,
            }
        )

    citations_used = [m.group(0) for m in CITATION_RE.finditer(resp.text)]
    grounded = len(citations_used) > 0 and "don't have grounded evidence" not in resp.text.lower()

    with trace.span("answer", grounded=grounded, num_citations=len(citations_used)):
        pass

    log_event(
        logger, 20, "answer_produced",
        query=query, grounded=grounded, citations=len(citations_used),
        model=resp.model, cost_usd=resp.cost_usd,
    )

    return AnswerResult(
        answer=resp.text,
        grounded=grounded,
        citations_used=citations_used,
        retrieved=[RetrievedEvidence(chunk=c, score=s) for c, s in hits],
        model=resp.model,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        cost_usd=resp.cost_usd,
    )
