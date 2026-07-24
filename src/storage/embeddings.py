"""Text embedding providers for the vector store (src/storage/vector_store.py).

Same pattern as chat/llm.py's LLMProvider: one interface, a real provider
that needs an API key, and a deterministic offline fallback that needs
nothing — so the vector store (and hybrid retrieval built on it) works with
zero external dependencies by default, and upgrades to real semantic
embeddings when a key is configured.

HashingEmbedder is a real trade-off, not a toy: it uses the hashing trick
(feature-hash tokens into a fixed-size vector, L2-normalize) — deterministic,
free, and captures lexical overlap reasonably, but it is NOT a semantic
embedding. Two paraphrases with no shared vocabulary will not be found
similar by it, same limitation as BM25 (see chat/index.py). It exists so
`RETRIEVAL_BACKEND=vector` or `hybrid` is honestly usable without an API key,
not to pretend to be a real embedding model.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod

import numpy as np

from src.config import settings

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[\"'/.\-][a-z0-9]+)*")


class Embedder(ABC):
    name: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class HashingEmbedder(Embedder):
    """Deterministic, offline, no-key-required. Feature-hashing (the
    "hashing trick"): each token hashes into one of `dim` buckets with a
    sign, vectors are L2-normalized. Same idea scikit-learn's
    HashingVectorizer uses — no training, no vocabulary, no API."""

    name = "hashing"

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in _TOKEN_RE.findall(text.lower()):
            h = int(hashlib.sha1(token.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h // self.dim) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t).tolist() for t in texts]


class OpenAIEmbedder(Embedder):
    """Real semantic embeddings via OpenAI's embeddings API. Needs
    OPENAI_API_KEY regardless of which LLM_PROVIDER is configured for chat —
    Anthropic and Groq don't currently offer an embeddings endpoint."""

    name = "openai"
    dim = 1536  # text-embedding-3-small

    def __init__(self):
        from openai import OpenAI

        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = "text-embedding-3-small"

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


def get_embedder() -> Embedder:
    provider = settings.embedder.lower()
    if provider == "openai" and settings.openai_api_key:
        return OpenAIEmbedder()
    return HashingEmbedder(dim=settings.hashing_embedder_dim)
