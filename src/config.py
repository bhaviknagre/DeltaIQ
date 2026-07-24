"""Central config: model, thresholds, and paths are all overridable via env
vars / .env — nothing below is meant to be hardcoded at call sites."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


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
