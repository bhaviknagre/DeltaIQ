"""Seeds data/pid_store/pids.json with the sample PID pairs used for demos
and eval. Run once after `make setup` (or automatically via `make run`)."""

from __future__ import annotations

from src.ingest.pid_store import register_pid

PIDS = [
    ("demo-native-a", "data/samples/pair_native/rev_a.pdf", "Rev A (native PDF)"),
    ("demo-native-b", "data/samples/pair_native/rev_b.pdf", "Rev B (native PDF)"),
    ("demo-scanned-a", "data/samples/pair_scanned/rev_a.pdf", "Rev A (scanned PDF)"),
    ("demo-scanned-b", "data/samples/pair_scanned/rev_b.pdf", "Rev B (scanned PDF)"),
    ("raw-export", "data/samples/raw/export_gas_compressor.pdf", "raw sample (no revision pair)"),
    ("raw-lift-gas", "data/samples/raw/lift_gas_compressor.pdf", "raw sample (no revision pair)"),
]

if __name__ == "__main__":
    for pid, path, label in PIDS:
        register_pid(pid, path, label)
        print(f"registered {pid} -> {path}")
