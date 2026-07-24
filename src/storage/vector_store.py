"""Vector store: segregates embeddings from metadata (metadata_store.py) and
raw file bytes (blob_store.py). One interface, two implementations:

  - ChromaVectorStore (default): embedded, persistent, local-disk Chroma —
    no server process required, no API key, works offline. Can also point
    at a standalone Chroma server (CHROMA_HOST) for the docker-compose
    "full stack" profile.
  - PineconeVectorStore: managed/cloud, needs PINECONE_API_KEY. The
    "production, don't want to run/scale a vector DB yourself" option.

Chroma is the default specifically because it needs no account/credit card/
network access to work at all — same reasoning as MockProvider/GroqProvider/
HashingEmbedder elsewhere in this project: real infrastructure should be
opt-in, not a hard requirement to run the system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.config import settings
from src.observability.logging import get_logger, log_event

logger = get_logger("storage.vector_store")


@dataclass
class VectorHit:
    id: str
    text: str
    metadata: dict
    score: float  # higher is more similar, normalized to roughly [0, 1]


class VectorStore(ABC):
    name: str

    @abstractmethod
    def upsert(self, collection: str, ids: list[str], embeddings: list[list[float]],
               texts: list[str], metadatas: list[dict]) -> None: ...

    @abstractmethod
    def query(self, collection: str, embedding: list[float], top_k: int) -> list[VectorHit]: ...

    @abstractmethod
    def delete_collection(self, collection: str) -> None: ...


class ChromaVectorStore(VectorStore):
    name = "chroma"

    def __init__(self):
        import chromadb

        if settings.chroma_host:
            self._client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
            log_event(logger, 20, "chroma_connected_remote", host=settings.chroma_host, port=settings.chroma_port)
        else:
            self._client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
            log_event(logger, 20, "chroma_connected_embedded", path=str(settings.chroma_persist_dir))

    def _collection(self, name: str):
        return self._client.get_or_create_collection(name)

    def upsert(self, collection: str, ids: list[str], embeddings: list[list[float]],
               texts: list[str], metadatas: list[dict]) -> None:
        if not ids:
            return
        self._collection(collection).upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    def query(self, collection: str, embedding: list[float], top_k: int) -> list[VectorHit]:
        col = self._collection(collection)
        if col.count() == 0:
            return []
        result = col.query(query_embeddings=[embedding], n_results=min(top_k, col.count()))
        hits = []
        ids = result["ids"][0]
        docs = result["documents"][0]
        metas = result["metadatas"][0]
        dists = result["distances"][0]
        for id_, doc, meta, dist in zip(ids, docs, metas, dists):
            # Chroma returns squared L2 distance by default; convert to a
            # roughly [0,1] similarity score (1 = identical) for a consistent
            # scale with the BM25 index's normalized scores in hybrid mode.
            score = float(1.0 / (1.0 + dist))  # Chroma may return numpy floats; keep this JSON-serializable
            hits.append(VectorHit(id=id_, text=doc, metadata=meta or {}, score=score))
        return hits

    def delete_collection(self, collection: str) -> None:
        try:
            self._client.delete_collection(collection)
        except Exception:  # noqa: BLE001 - fine if it didn't exist
            pass


class PineconeVectorStore(VectorStore):
    name = "pinecone"

    def __init__(self):
        from pinecone import Pinecone

        self._pc = Pinecone(api_key=settings.pinecone_api_key)
        self._index_name = settings.pinecone_index_name
        existing = [i["name"] for i in self._pc.list_indexes()]
        if self._index_name not in existing:
            from pinecone import ServerlessSpec

            self._pc.create_index(
                name=self._index_name, dimension=settings.hashing_embedder_dim, metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
        self._index = self._pc.Index(self._index_name)

    # Pinecone rejects a single upsert request over 1000 vectors outright
    # (found live: a real document's ~1200 chunks 400'd in one call) — 100
    # is Pinecone's own documented recommended batch size for throughput,
    # well under the hard cap.
    _UPSERT_BATCH_SIZE = 100

    def upsert(self, collection: str, ids: list[str], embeddings: list[list[float]],
               texts: list[str], metadatas: list[dict]) -> None:
        if not ids:
            return
        vectors = [
            {"id": f"{collection}:{id_}", "values": emb, "metadata": {**meta, "text": text, "collection": collection}}
            for id_, emb, text, meta in zip(ids, embeddings, texts, metadatas)
        ]
        for i in range(0, len(vectors), self._UPSERT_BATCH_SIZE):
            self._index.upsert(vectors=vectors[i:i + self._UPSERT_BATCH_SIZE], namespace=collection)

    def query(self, collection: str, embedding: list[float], top_k: int) -> list[VectorHit]:
        result = self._index.query(vector=embedding, top_k=top_k, namespace=collection, include_metadata=True)
        hits = []
        for match in result["matches"]:
            meta = dict(match["metadata"])
            text = meta.pop("text", "")
            hits.append(VectorHit(id=match["id"], text=text, metadata=meta, score=match["score"]))
        return hits

    def delete_collection(self, collection: str) -> None:
        # Unlike Chroma's get_or_create/delete (idempotent even for a
        # namespace that's never existed), Pinecone's delete(delete_all=True)
        # 404s on a brand-new namespace — found live testing a fresh
        # collection name for the first time. Deleting nothing because there
        # was nothing to delete is exactly the outcome we want, so swallow
        # only that specific case.
        from pinecone.exceptions import NotFoundException

        try:
            self._index.delete(delete_all=True, namespace=collection)
        except NotFoundException:
            pass


class NullVectorStore(VectorStore):
    """VECTOR_STORE=none — retrieval falls back to pure BM25. Lets
    RETRIEVAL_BACKEND stay bm25 without importing chromadb/pinecone at all."""

    name = "none"

    def upsert(self, collection, ids, embeddings, texts, metadatas) -> None:
        pass

    def query(self, collection, embedding, top_k) -> list[VectorHit]:
        return []

    def delete_collection(self, collection) -> None:
        pass


def get_vector_store() -> VectorStore:
    backend = settings.vector_store.lower()
    try:
        if backend == "chroma":
            return ChromaVectorStore()
        if backend == "pinecone" and settings.pinecone_api_key:
            return PineconeVectorStore()
    except Exception as exc:  # noqa: BLE001
        log_event(logger, 40, "vector_store_init_failed_falling_back_to_none", backend=backend, error=str(exc))
        return NullVectorStore()
    return NullVectorStore()
