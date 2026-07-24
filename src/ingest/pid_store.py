"""Resolves a PID (persistent identifier for one document revision) to bytes
+ metadata, then dispatches to the right FormatAdapter and returns a
CanonicalDocument. This is the single place the rest of the system calls
into ingestion through — it never sees adapters or raw files directly.

The "store" itself is a flat JSON manifest (data/pid_store/pids.json) mapping
PID -> {path, revision_label}. A real deployment would swap this for a
database/object-store lookup; the interface (`resolve`, `load`) would not
change.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.canonical.model import CanonicalDocument
from src.config import settings
from src.ingest.base import registry
from src.ingest.dwg import DwgAdapter
from src.ingest.pdf_native import NativePdfAdapter
from src.ingest.pdf_scanned import ScannedPdfAdapter
from src.observability.logging import get_logger, log_event

logger = get_logger("ingest.pid_store")

registry.register(NativePdfAdapter)
registry.register(ScannedPdfAdapter)
registry.register(DwgAdapter)


class PidNotFoundError(KeyError):
    pass


def _load_manifest() -> dict:
    if not settings.pid_store_path.exists():
        return {}
    return json.loads(settings.pid_store_path.read_text())


def _save_manifest(manifest: dict) -> None:
    settings.pid_store_path.write_text(json.dumps(manifest, indent=2))


def register_pid(pid: str, path: str, revision_label: str | None = None) -> None:
    manifest = _load_manifest()
    manifest[pid] = {"path": path, "revision_label": revision_label}
    _save_manifest(manifest)


def resolve_pid(pid: str) -> dict:
    manifest = _load_manifest()
    if pid not in manifest:
        raise PidNotFoundError(f"Unknown PID: {pid}")
    return manifest[pid]


def load(pid: str) -> CanonicalDocument:
    """Resolve a PID to bytes+metadata, detect its format, and normalize it
    into the canonical representation."""
    entry = resolve_pid(pid)
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
    return doc
