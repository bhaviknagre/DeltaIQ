"""Retrieval over PID A, PID B, and the delta report.

Uses BM25 (rank_bm25) over element-level and delta-item-level chunks rather
than embeddings. Trade-off, stated plainly: BM25 needs no API key and is
fully deterministic (good for reproducible eval), but it's a lexical match
and will miss paraphrase/semantic queries an embedding index would catch.
Given P&ID content is dominated by exact tags, dimensions, and codes (where
lexical match is actually *more* reliable than semantic similarity — "26-KA-
902" should match "26-KA-902", not something merely "related"), this is a
deliberate choice, not a cost-cutting shortcut — documented as a real
retrieval-quality trade-off in the README, with embedding-based retrieval
named as future work.

Every chunk carries a Citation back to its exact source (PID + page + bbox,
or a delta-report item id) so answers can be grounded precisely, not just
"somewhere in document A."
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from src.canonical.model import CanonicalDocument
from src.delta.engine import DeltaResult
from src.observability.logging import get_logger, log_event

logger = get_logger("chat.index")

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[\"'/.\-][a-z0-9]+)*")

# Deliberately small stopword list, not a generic NLP one: the corpus is
# short P&ID labels/tags where common English words are themselves rare, so
# a stray query word like "the" or "is" can get an inflated BM25 IDF and
# spuriously outrank real tag matches. Filtering them (plus 1-char tokens,
# which otherwise let "P&ID" -> "p" collide with unrelated single-letter
# OCR fragments) was found empirically via eval — see README retrieval notes.
_STOPWORDS = {
    "a", "an", "the", "is", "was", "were", "be", "been", "being", "to", "of", "in", "on", "at",
    "for", "and", "or", "but", "with", "this", "that", "these", "those", "what", "which", "who",
    "how", "do", "does", "did", "it", "its", "as", "by", "from", "into", "about",
    # domain-generic: "P&ID" tokenizes to "p" + "id" and appears near-universally
    # in sheet boilerplate, so "id" alone is not a meaningful content token here.
    "id", "pid",
}


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 2 and t not in _STOPWORDS]


@dataclass
class Citation:
    source: str  # "pid_a" | "pid_b" | "delta_report"
    pid: str | None
    page_index: int | None
    element_id: str | None
    delta_id: str | None
    bbox: tuple[float, float, float, float] | None

    def label(self) -> str:
        if self.source == "delta_report":
            return f"[delta:{self.delta_id}]"
        loc = f"p{self.page_index}" if self.page_index is not None else "?"
        return f"[{self.source}:{self.pid}@{loc}]"


@dataclass
class Chunk:
    text: str
    citation: Citation



# Delta-report chunks are pre-summarized, curated evidence specifically about
# what changed — for "what changed" style questions they're a strictly
# better citation than re-discovering the same fact from a raw element
# label, so they get a modest ranking boost rather than competing on raw
# lexical score alone.
_DELTA_SOURCE_BOOST = 1.4


class RetrievalIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._corpus_tokens = [_tokenize(c.text) for c in chunks]
        self._bm25 = BM25Okapi(self._corpus_tokens) if chunks else None

    def search(self, query: str, top_k: int, min_score: float) -> list[tuple[Chunk, float]]:
        """Returns chunks that (a) share at least one real content token with
        the query — a hard gate, not just a score threshold, so a query with
        zero lexical overlap with the corpus (e.g. off-topic/adversarial
        questions) returns nothing rather than "the least-bad top result" —
        and (b) score within `min_score` of the best qualifying match.

        Applies a source boost for delta-report chunks (see
        _DELTA_SOURCE_BOOST) and de-duplicates chunks with identical text
        from the same source so that, e.g., a tag label repeated verbatim
        three times on a sheet doesn't crowd distinct, more informative
        chunks out of the top-k window.
        """
        if not self._bm25:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        q_token_set = set(q_tokens)
        scores = self._bm25.get_scores(q_tokens)

        candidates = []
        for chunk, tokens, score in zip(self.chunks, self._corpus_tokens, scores):
            if score <= 0 or not (q_token_set & set(tokens)):
                continue
            boosted = score * _DELTA_SOURCE_BOOST if chunk.citation.source == "delta_report" else score
            candidates.append((chunk, boosted))
        if not candidates:
            return []

        candidates.sort(key=lambda cs: cs[1], reverse=True)
        max_score = candidates[0][1]

        results = []
        seen_text_by_source: set[tuple[str, str]] = set()
        for chunk, score in candidates:
            if len(results) >= top_k:
                break
            dedup_key = (chunk.citation.source, chunk.text)
            if dedup_key in seen_text_by_source:
                continue
            norm = score / max_score if max_score > 0 else 0.0
            if norm >= min_score:
                results.append((chunk, norm))
                seen_text_by_source.add(dedup_key)
        return results


def build_index(doc_a: CanonicalDocument, doc_b: CanonicalDocument, delta: DeltaResult) -> RetrievalIndex:
    chunks: list[Chunk] = []

    for source, doc in (("pid_a", doc_a), ("pid_b", doc_b)):
        for el in doc.all_elements():
            chunks.append(
                Chunk(
                    text=el.text,
                    citation=Citation(
                        source=source,
                        pid=doc.meta.pid,
                        page_index=el.page_index,
                        element_id=el.id,
                        delta_id=None,
                        bbox=(el.bbox.x0, el.bbox.y0, el.bbox.x1, el.bbox.y1),
                    ),
                )
            )

    for item in delta.items:
        text = f"{item.change_kind.value} {item.category.value}: {item.description}"
        chunks.append(
            Chunk(
                text=text,
                citation=Citation(
                    source="delta_report",
                    pid=None,
                    page_index=item.page_index,
                    element_id=None,
                    delta_id=item.id,
                    bbox=(item.bbox.x0, item.bbox.y0, item.bbox.x1, item.bbox.y1),
                ),
            )
        )

    log_event(logger, 20, "index_built", num_chunks=len(chunks), pid_a=doc_a.meta.pid, pid_b=doc_b.meta.pid)
    return RetrievalIndex(chunks)
