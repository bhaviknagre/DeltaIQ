"""Central config: model, thresholds, and paths are all overridable via env
vars / .env — nothing below is meant to be hardcoded at call sites."""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

_CREDENTIALS_IN_URI = re.compile(r"(://)[^:/@]*:[^@]+@")


def redact_uri(uri: str) -> str:
    """Strips user:pass@ out of a connection string for anything that gets
    logged, traced, or rendered on a page (the /infra status page, JSON
    logs, trace files) — found live: MONGODB_URI was being logged and
    rendered in full, password included, at every Mongo connection. Never
    log/display settings.mongodb_uri directly; always pass it through this
    first."""
    return _CREDENTIALS_IN_URI.sub(r"\1***:***@", uri)


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


class Settings:
    # --- LLM ---
    llm_provider: str = os.environ.get("LLM_PROVIDER", "anthropic")  # anthropic | openai | groq | mock
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    groq_api_key: str | None = os.environ.get("GROQ_API_KEY")  # free tier, no card required: console.groq.com
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    groq_model: str = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    llm_max_tokens: int = _i("LLM_MAX_TOKENS", 1024)
    llm_temperature: float = _f("LLM_TEMPERATURE", 0.0)

    # --- Alignment / delta thresholds ---
    fuzzy_match_threshold: float = _f("FUZZY_MATCH_THRESHOLD", 78.0)  # rapidfuzz 0-100
    spatial_match_max_dist: float = _f("SPATIAL_MATCH_MAX_DIST", 60.0)  # points
    modified_text_threshold: float = _f("MODIFIED_TEXT_THRESHOLD", 99.5)  # >= this sim => unchanged

    # --- Retrieval ---
    retrieval_top_k: int = _i("RETRIEVAL_TOP_K", 8)
    retrieval_min_score: float = _f("RETRIEVAL_MIN_SCORE", 0.05)
    # bm25 (lexical, default, zero infra) | vector (chroma/pinecone) | hybrid (both, blended)
    retrieval_backend: str = os.environ.get("RETRIEVAL_BACKEND", "bm25")
    hybrid_bm25_weight: float = _f("HYBRID_BM25_WEIGHT", 0.5)  # remainder goes to vector score

    # --- Chat pipeline ---
    # simple (default): chat/answer.py's single retrieve -> LLM -> parse-citations
    # call, one round trip. agentic: src/chat/agentic.py's LangGraph state
    # machine — retrieve -> answer -> verify citations against retrieved
    # evidence -> widen-and-retry on a failed verification, capped at
    # agentic_max_retries. Additive, not a replacement: existing callers that
    # don't opt in keep getting the simple pipeline unchanged.
    chat_backend: str = os.environ.get("CHAT_BACKEND", "simple")  # simple | agentic
    agentic_max_retries: int = _i("AGENTIC_MAX_RETRIES", 2)

    # --- Embeddings (for the vector store) ---
    embedder: str = os.environ.get("EMBEDDER", "hashing")  # hashing (offline, default) | openai
    hashing_embedder_dim: int = _i("HASHING_EMBEDDER_DIM", 256)

    # --- Vector store: segregates embeddings from metadata/blobs ---
    vector_store: str = os.environ.get("VECTOR_STORE", "chroma")  # chroma | pinecone | none
    chroma_persist_dir: Path = ROOT / "data" / "chroma"
    chroma_host: str | None = os.environ.get("CHROMA_HOST")  # set to use a remote/server-mode Chroma instead of embedded
    chroma_port: int = _i("CHROMA_PORT", 8100)
    pinecone_api_key: str | None = os.environ.get("PINECONE_API_KEY")
    pinecone_index_name: str = os.environ.get("PINECONE_INDEX_NAME", "delta-chat")

    # --- Metadata store: segregates PID/document/delta/eval metadata from
    # the vector store and from raw file bytes. JSON is the zero-infra
    # default (identical to the original pid_store.json behavior); Mongo is
    # the real, production-shaped option. ---
    metadata_store: str = os.environ.get("METADATA_STORE", "json")  # json | mongo
    mongodb_uri: str = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    mongodb_db_name: str = os.environ.get("MONGODB_DB_NAME", "delta_chat")

    # --- Blob store: raw PDF/DXF bytes at rest. Local disk is the default
    # (documents already live under data/samples/ as real files); GridFS is
    # the option for when documents arrive as bytes rather than paths on
    # disk (e.g. uploaded via an API), keeping large binaries out of Mongo's
    # regular document collections. ---
    blob_store: str = os.environ.get("BLOB_STORE", "local")  # local | minio | mongo_gridfs
    blob_store_dir: Path = ROOT / "data" / "blobs"
    minio_endpoint: str = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    minio_bucket: str = os.environ.get("MINIO_BUCKET", "delta-chat")
    minio_secure: bool = os.environ.get("MINIO_SECURE", "").lower() in ("1", "true")

    # --- Background tasks (Celery + Redis) ---
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    # Runs tasks synchronously in-process instead of dispatching to a worker
    # — used by check scripts/tests so task *logic* is verified even with no
    # live Celery worker running, without special-casing test code.
    celery_task_always_eager: bool = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "").lower() in ("1", "true")

    # --- LLM observability (Langfuse) ---
    langfuse_public_key: str | None = os.environ.get("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = os.environ.get("LANGFUSE_SECRET_KEY")
    langfuse_host: str = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

    # --- OCR ---
    ocr_dpi: int = _i("OCR_DPI", 300)
    ocr_lang: str = os.environ.get("OCR_LANG", "eng")
    # PSM 11 ("sparse text, no particular order") beats the default PSM 3
    # ("assume a uniform block of text") on P&ID sheets: default PSM merges
    # unrelated nearby labels into single garbled lines because it expects
    # paragraph-like layout; sparse mode treats each scattered label as its
    # own region, which is what a drawing actually looks like.
    ocr_psm: int = _i("OCR_PSM", 11)

    # --- Paths ---
    data_dir: Path = ROOT / "data"
    pid_store_path: Path = ROOT / "data" / "pid_store" / "pids.json"
    logs_dir: Path = ROOT / "logs"
    traces_dir: Path = ROOT / "traces"

    # --- Pricing (USD per 1M tokens), used only for cost telemetry estimates ---
    pricing: dict = {
        "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.5, "output": 10.0},
        # Groq's free developer tier bills $0 within its rate limits; entries
        # reflect that, not their separate paid/enterprise pricing.
        "llama-3.3-70b-versatile": {"input": 0.0, "output": 0.0},
        "llama-3.1-8b-instant": {"input": 0.0, "output": 0.0},
        "mock": {"input": 0.0, "output": 0.0},
    }


settings = Settings()
settings.logs_dir.mkdir(parents=True, exist_ok=True)
settings.traces_dir.mkdir(parents=True, exist_ok=True)
settings.pid_store_path.parent.mkdir(parents=True, exist_ok=True)
settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
settings.blob_store_dir.mkdir(parents=True, exist_ok=True)
