"""Resolves a PID (persistent identifier for one document revision) to bytes
+ metadata, then dispatches to the right FormatAdapter and returns a
CanonicalDocument. This is the single place the rest of the system calls
into ingestion through — it never sees adapters, raw files, or which
metadata backend is configured directly.

The registry/manifest itself is delegated to a MetadataStore
(src/storage/metadata_store.py) — a flat JSON file by default (identical
behavior to before this module existed), or real MongoDB when
METADATA_STORE=mongo. Parsed CanonicalDocuments are cached through the same
store (JSON: sibling cache files; Mongo: a dedicated collection) so
`load()` doesn't re-run OCR/text-extraction on every call within a process
that would otherwise hit the metadata store repeatedly for the same PID.
"""

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
    """Kept for backward compatibility (src/webapp/app.py and tests read
    this directly to list registered PIDs) — delegates to whichever
    MetadataStore is configured rather than reading a JSON file itself."""
    return get_metadata_store().list_pids()


def register_pid(pid: str, path: str, revision_label: str | None = None) -> None:
    get_metadata_store().register_pid(pid, path, revision_label)


def resolve_pid(pid: str) -> dict:
    return get_metadata_store().resolve_pid(pid)


def load(pid: str, use_cache: bool = False) -> CanonicalDocument:
    """Resolve a PID to bytes+metadata, detect its format, and normalize it
    into the canonical representation.

    `use_cache` is opt-in, not default-on, deliberately: the cache is keyed
    by PID name only, with no file-mtime/hash invalidation. Regenerating a
    sample file in place (e.g. `make samples`) while reusing the same PID
    name — which happens routinely in this project's own dev loop — would
    otherwise silently serve stale parsed content with no error. Safe to
    pass True for a genuinely immutable/short-lived scope (e.g. a single
    background task re-reading the same PID multiple times)."""
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
