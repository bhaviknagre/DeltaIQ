"""Check: environment is set up correctly (Python version, tesseract binary,
required packages importable, writable data dirs). Run this first — most
other check scripts assume this passes.

Usage: python -m scripts.checks.check_env
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from scripts.checks._common import CheckSuite

REQUIRED_PACKAGES = [
    "fitz", "pytesseract", "PIL", "rapidfuzz", "rank_bm25", "pydantic",
    "click", "ezdxf", "anthropic", "openai", "fastapi", "uvicorn", "jinja2",
    "pymongo", "chromadb", "pinecone", "minio", "redis", "celery", "flower",
    "prometheus_client", "langfuse", "numpy", "dvc",
]


def main() -> None:
    suite = CheckSuite("env")

    with suite.check("python >= 3.10"):
        assert sys.version_info >= (3, 10), f"found {sys.version_info}"

    with suite.check("tesseract binary on PATH"):
        assert shutil.which("tesseract") is not None, "not found — brew/apt install tesseract"

    for pkg in REQUIRED_PACKAGES:
        with suite.check(f"import {pkg}"):
            __import__(pkg)

    with suite.check("data/pid_store dir writable"):
        from src.config import settings

        settings.pid_store_path.parent.mkdir(parents=True, exist_ok=True)
        probe = settings.pid_store_path.parent / ".write_probe"
        probe.write_text("ok")
        probe.unlink()

    with suite.check("logs/ and traces/ dirs writable"):
        from src.config import settings

        for d in (settings.logs_dir, settings.traces_dir):
            d.mkdir(parents=True, exist_ok=True)
            probe = Path(d) / ".write_probe"
            probe.write_text("ok")
            probe.unlink()

    suite.exit()


if __name__ == "__main__":
    main()
