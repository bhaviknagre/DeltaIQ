from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from src.canonical.model import CanonicalDocument
from src.delta.engine import DeltaResult
from src.observability.logging import get_logger, log_event

logger = get_logger("chat.index")

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[\"'/.\-][a-z0-9]+)*")

_STOPWORDS = {
    "a", "an", "the", "is", "was", "were", "be", "been", "being", "to", "of", "in", "on", "at",
    "for", "and", "or", "but", "with", "this", "that", "these", "those", "what", "which", "who",
    "how", "do", "does", "did", "it", "its", "as", "by", "from", "into", "about",
    "id", "pid",
}


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 2 and t not in _STOPWORDS]


@dataclass
class Citation:
    source: str 
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


_DELTA_SOURCE_BOOST = 1.4


class RetrievalIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._corpus_tokens = [_tokenize(c.text) for c in chunks]
        self._bm25 = BM25Okapi(self._corpus_tokens) if chunks else None

    def search(self, query: str, top_k: int, min_score: float) -> list[tuple[Chunk, float]]:
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
