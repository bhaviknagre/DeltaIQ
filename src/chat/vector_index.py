"""Vector and hybrid retrieval, built on top of src/storage/vector_store.py
+ src/storage/embeddings.py. Exposes the exact same `search(query, top_k,
min_score) -> list[tuple[Chunk, float]]` shape as the BM25 RetrievalIndex
(src/chat/index.py), so chat/answer.py works unchanged no matter which
RETRIEVAL_BACKEND is configured — it only ever depends on that shape, never
on a specific backend's internals.

Three backends, selected via RETRIEVAL_BACKEND (src/config.py):
  - "bm25" (default): the original lexical index, zero extra infra.
  - "vector": pure embedding similarity via Chroma/Pinecone.
  - "hybrid": both, blended — catches the paraphrase queries BM25 misses
    (see README/eval "candid failures": qa-6) while keeping BM25's precision
    on exact tags/codes, which raw semantic similarity is worse at (a vector
    index has no reason to rank "26-KA-902" above a vaguely-related neighbor
    the way an exact lexical match does).
"""

from __future__ import annotations

from src.canonical.model import CanonicalDocument
from src.chat.index import Chunk, RetrievalIndex, _tokenize, build_index
from src.config import settings
from src.delta.engine import DeltaResult
from src.observability.logging import get_logger, log_event
from src.storage.embeddings import get_embedder
from src.storage.vector_store import get_vector_store

logger = get_logger("chat.vector_index")


class VectorSearchIndex:
    """Pure embedding-similarity retrieval. Each PID-pair gets its own
    Chroma/Pinecone collection (`retrieval_{pid_a}_{pid_b}`), rebuilt (via
    upsert, keyed by a stable chunk id) each time an index is built for that
    pair — cheap for this project's document sizes, and avoids stale
    vectors from a prior revision pair lingering under the same collection
    name."""

    def __init__(self, chunks: list[Chunk], collection: str):
        # Chunks with no real content tokens (bare punctuation/noise lines,
        # e.g. a stray "." or "/" element) hash to a zero vector, which is
        # equidistant from every query in a degenerate way and pollutes
        # results with ties — BM25 already excludes these via its lexical-
        # overlap gate, so drop them here too rather than indexing noise.
        chunks = [c for c in chunks if _tokenize(c.text)]

        self.chunks = chunks
        self.collection = collection
        self._embedder = get_embedder()
        self._store = get_vector_store()
        self._by_id = {self._chunk_id(c): c for c in chunks}

        # Delete-then-upsert, not upsert-only: an upsert-only collection can
        # never truly go stale-free again once anything's written under it —
        # a failed upsert (schema mismatch, a crash mid-write), a later
        # chunking-logic change, or reusing a collection name across an
        # unrelated run all leave old entries with no way to get evicted.
        # Found exactly this while testing: a validation failure had already
        # get_or_create'd an empty collection as a side effect, and it
        # silently returned zero hits forever after — indistinguishable from
        # "no matches" without this.
        self._store.delete_collection(collection)

        if chunks:
            embeddings = self._embedder.embed([c.text for c in chunks])
            self._store.upsert(
                collection,
                ids=list(self._by_id.keys()),
                embeddings=embeddings,
                texts=[c.text for c in chunks],
                metadatas=[{"source": c.citation.source} for c in chunks],
            )

    @staticmethod
    def _chunk_id(chunk: Chunk) -> str:
        # NOT citation.label(): that's a human-readable citation shared by
        # every element on the same page/source (e.g. every pid_a element on
        # page 0 labels as "[pid_a:<pid>@p0]") — using it as a vector-store
        # key collapsed hundreds of distinct chunks onto a handful of IDs.
        # element_id/delta_id are the fields actually unique per chunk.
        c = chunk.citation
        return f"delta:{c.delta_id}" if c.source == "delta_report" else f"{c.source}:{c.element_id}"

    def search(self, query: str, top_k: int, min_score: float) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        query_emb = self._embedder.embed_one(query)
        hits = self._store.query(self.collection, query_emb, top_k=top_k)
        results = []
        for hit in hits:
            chunk = self._by_id.get(hit.id)
            if chunk is None or hit.score < min_score:
                continue
            results.append((chunk, hit.score))
        return results


class HybridRetrievalIndex:
    """Blends BM25 and vector scores by chunk identity (citation label).
    Reciprocal-rank-ish simple weighted sum: both sub-scores are already
    normalized to ~[0,1] by their own indexes, so `w * bm25 + (1-w) * vector`
    stays in range. HYBRID_BM25_WEIGHT (default 0.5) controls the blend."""

    def __init__(self, bm25_index: RetrievalIndex, vector_index: VectorSearchIndex):
        self._bm25 = bm25_index
        self._vector = vector_index
        self._weight = settings.hybrid_bm25_weight

    def search(self, query: str, top_k: int, min_score: float) -> list[tuple[Chunk, float]]:
        # Widen each sub-search so blending has enough candidates to work
        # with before the final top_k/min_score cut is applied.
        wide_k = max(top_k * 3, 20)
        bm25_hits = {c.citation.label(): (c, s) for c, s in self._bm25.search(query, wide_k, 0.0)}
        vector_hits = {c.citation.label(): (c, s) for c, s in self._vector.search(query, wide_k, 0.0)}

        all_labels = set(bm25_hits) | set(vector_hits)
        if not all_labels:
            return []

        blended: list[tuple[Chunk, float]] = []
        for label in all_labels:
            chunk = (bm25_hits.get(label) or vector_hits.get(label))[0]
            bm25_score = bm25_hits[label][1] if label in bm25_hits else 0.0
            vector_score = vector_hits[label][1] if label in vector_hits else 0.0
            score = float(self._weight * bm25_score + (1 - self._weight) * vector_score)
            blended.append((chunk, score))

        blended.sort(key=lambda cs: cs[1], reverse=True)
        return [(c, s) for c, s in blended[:top_k] if s >= min_score]


def build_retriever(doc_a: CanonicalDocument, doc_b: CanonicalDocument, delta: DeltaResult):
    """Factory: returns whichever retriever RETRIEVAL_BACKEND selects, all
    satisfying the same search(query, top_k, min_score) shape. This is what
    runtime call sites (CLI, web UI, eval) should use — build_index() itself
    stays BM25-only and is still used directly where tests/checks
    specifically exercise BM25 behavior."""
    backend = settings.retrieval_backend.lower()
    bm25_index = build_index(doc_a, doc_b, delta)

    if backend == "bm25":
        return bm25_index

    chunks = bm25_index.chunks
    collection = f"retrieval_{doc_a.meta.pid}_{doc_b.meta.pid}"
    try:
        vector_index = VectorSearchIndex(chunks, collection)
    except Exception as exc:  # noqa: BLE001
        log_event(logger, 40, "vector_index_init_failed_falling_back_to_bm25", backend=backend, error=str(exc))
        return bm25_index

    if backend == "vector":
        return vector_index
    if backend == "hybrid":
        return HybridRetrievalIndex(bm25_index, vector_index)

    log_event(logger, 30, "unknown_retrieval_backend_falling_back_to_bm25", backend=backend)
    return bm25_index
