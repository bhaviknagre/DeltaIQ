from __future__ import annotations

from src.ingest.pid_store import register_pid

PIDS = [
    ("26-9026-REV-A", "data/samples/pair_native/rev_a.pdf", "Rev A (native PDF)"),
    ("26-9026-REV-B", "data/samples/pair_native/rev_b.pdf", "Rev B (native PDF)"),
    ("26-9026-REV-A-SCAN", "data/samples/pair_scanned/rev_a.pdf", "Rev A (scanned PDF)"),
    ("26-9026-REV-B-SCAN", "data/samples/pair_scanned/rev_b.pdf", "Rev B (scanned PDF)"),
    ("26-9026-ASBUILT", "data/samples/raw/export_gas_compressor.pdf", "raw sample (no revision pair)"),
    ("26-PDI-9054-ASBUILT", "data/samples/raw/lift_gas_compressor.pdf", "raw sample (no revision pair)"),
]

if __name__ == "__main__":
    for pid, path, label in PIDS:
        register_pid(pid, path, label)
        print(f"registered {pid} -> {path}")
