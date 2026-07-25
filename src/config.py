from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

_CREDENTIALS_IN_URI = re.compile(r"(://)[^:/@]*:[^@]+@")


def redact_uri(uri: str) -> str:
    return _CREDENTIALS_IN_URI.sub(r"\1***:***@", uri)


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


class Settings:
    # --- LLM ---
    llm_provider: str = os.environ.get("LLM_PROVIDER", "anthropic") 
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    groq_api_key: str | None = os.environ.get("GROQ_API_KEY")  
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    groq_model: str = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    llm_max_tokens: int = _i("LLM_MAX_TOKENS", 1024)
    llm_temperature: float = _f("LLM_TEMPERATURE", 0.0)

    # --- Alignment / delta thresholds ---
    fuzzy_match_threshold: float = _f("FUZZY_MATCH_THRESHOLD", 78.0)  
    spatial_match_max_dist: float = _f("SPATIAL_MATCH_MAX_DIST", 60.0)  
    modified_text_threshold: float = _f("MODIFIED_TEXT_THRESHOLD", 99.5) 

    # --- Retrieval ---
    retrieval_top_k: int = _i("RETRIEVAL_TOP_K", 8)
    retrieval_min_score: float = _f("RETRIEVAL_MIN_SCORE", 0.05)
    retrieval_backend: str = os.environ.get("RETRIEVAL_BACKEND", "bm25")
    hybrid_bm25_weight: float = _f("HYBRID_BM25_WEIGHT", 0.5) 

    # --- Chat pipeline ---
    chat_backend: str = os.environ.get("CHAT_BACKEND", "simple")  
    agentic_max_retries: int = _i("AGENTIC_MAX_RETRIES", 2)

    # --- Embeddings (for the vector store) ---
    embedder: str = os.environ.get("EMBEDDER", "hashing")  
    hashing_embedder_dim: int = _i("HASHING_EMBEDDER_DIM", 256)

    # --- Vector store: segregates embeddings from metadata/blobs ---
    vector_store: str = os.environ.get("VECTOR_STORE", "chroma") 
    chroma_persist_dir: Path = ROOT / "data" / "chroma"
    chroma_host: str | None = os.environ.get("CHROMA_HOST")  
    chroma_port: int = _i("CHROMA_PORT", 8100)
    pinecone_api_key: str | None = os.environ.get("PINECONE_API_KEY")
    pinecone_index_name: str = os.environ.get("PINECONE_INDEX_NAME", "delta-chat")

    # --- Metadata storev ---
    metadata_store: str = os.environ.get("METADATA_STORE", "json")  
    mongodb_uri: str = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    mongodb_db_name: str = os.environ.get("MONGODB_DB_NAME", "delta_chat")

    # --- Blob store ---
    blob_store: str = os.environ.get("BLOB_STORE", "local")  
    blob_store_dir: Path = ROOT / "data" / "blobs"
    minio_endpoint: str = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    minio_bucket: str = os.environ.get("MINIO_BUCKET", "delta-chat")
    minio_secure: bool = os.environ.get("MINIO_SECURE", "").lower() in ("1", "true")

    # --- Background tasks (Celery + Redis) ---
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    celery_task_always_eager: bool = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "").lower() in ("1", "true")

    # --- LLM observability (Langfuse) ---
    langfuse_public_key: str | None = os.environ.get("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = os.environ.get("LANGFUSE_SECRET_KEY")
    langfuse_host: str = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

    # --- OCR ---
    ocr_dpi: int = _i("OCR_DPI", 300)
    ocr_lang: str = os.environ.get("OCR_LANG", "eng")
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
