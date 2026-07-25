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
    def __init__(self, chunks: list[Chunk], collection: str):
        chunks = [c for c in chunks if _tokenize(c.text)]
        self.chunks = chunks
        self.collection = collection
        self._embedder = get_embedder()
        self._store = get_vector_store()
        self._by_id = {self._chunk_id(c): c for c in chunks}
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

    def __init__(self, bm25_index: RetrievalIndex, vector_index: VectorSearchIndex):
        self._bm25 = bm25_index
        self._vector = vector_index
        self._weight = settings.hybrid_bm25_weight

    def search(self, query: str, top_k: int, min_score: float) -> list[tuple[Chunk, float]]:
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
    backend = settings.retrieval_backend.lower()
    bm25_index = build_index(doc_a, doc_b, delta)

    if backend == "bm25":
        return bm25_index

    chunks = bm25_index.chunks
    collection = f"retrieval_{doc_a.meta.pid}_{doc_b.meta.pid}"
    try:
        vector_index = VectorSearchIndex(chunks, collection)
    except Exception as exc:  
        log_event(logger, 40, "vector_index_init_failed_falling_back_to_bm25", backend=backend, error=str(exc))
        return bm25_index

    if backend == "vector":
        return vector_index
    if backend == "hybrid":
        return HybridRetrievalIndex(bm25_index, vector_index)

    log_event(logger, 30, "unknown_retrieval_backend_falling_back_to_bm25", backend=backend)
    return bm25_index
