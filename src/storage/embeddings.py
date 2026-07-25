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
    name = "openai"
    dim = 1536 

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
