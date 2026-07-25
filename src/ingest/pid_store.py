from __future__ import annotations

from pathlib import Path

from src.canonical.model import CanonicalDocument
from src.ingest.base import registry
from src.ingest.dwg import DwgAdapter
from src.ingest.pdf_native import NativePdfAdapter
from src.ingest.pdf_scanned import ScannedPdfAdapter
from src.observability.logging import get_logger, log_event
from src.storage.metadata_store import PidNotFoundError, get_metadata_store

logger = get_logger("ingest.pid_store")

registry.register(NativePdfAdapter)
registry.register(ScannedPdfAdapter)
registry.register(DwgAdapter)

__all__ = ["PidNotFoundError", "register_pid", "resolve_pid", "load"]


def _load_manifest() -> dict:
    return get_metadata_store().list_pids()


def register_pid(pid: str, path: str, revision_label: str | None = None) -> None:
    get_metadata_store().register_pid(pid, path, revision_label)


def resolve_pid(pid: str) -> dict:
    return get_metadata_store().resolve_pid(pid)


def load(pid: str, use_cache: bool = False) -> CanonicalDocument:
    store = get_metadata_store()
    entry = store.resolve_pid(pid)

    if use_cache:
        cached = store.get_canonical_document(pid)
        if cached is not None:
            log_event(logger, 20, "ingest_cache_hit", pid=pid, backend=store.name)
            return CanonicalDocument.model_validate(cached)

    path = Path(entry["path"])
    if not path.exists():
        raise FileNotFoundError(f"PID {pid} resolves to missing file: {path}")

    adapter_cls = registry.resolve(path)
    adapter = adapter_cls()
    log_event(logger, 20, "ingest_start", pid=pid, path=str(path), adapter=adapter_cls.format_name)
    doc = adapter.parse(path, pid=pid, revision_label=entry.get("revision_label"))
    log_event(
        logger, 20, "ingest_done", pid=pid, adapter=adapter_cls.format_name,
        pages=len(doc.pages), elements=len(doc.all_elements()),
    )
    if use_cache:
        store.save_canonical_document(pid, doc.model_dump(mode="json"))
    return doc
