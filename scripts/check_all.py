"""Master check script: runs every scripts/checks/check_*.py in a sensible
dependency order, in its own subprocess (so a crash in one doesn't take down
the rest), streams its output live, and prints a final subsystem-by-
subsystem summary. This is the "is everything working as expected right
now" script for day-to-day development — `make check`.

Individual checks can still be run standalone when you only care about one
subsystem, e.g. `python -m scripts.checks.check_delta_engine`. This script
doesn't replace `make test` (pytest unit/integration tests) or `make eval`
(the scored eval harness) — it's a faster, coarser-grained "did I break
something" pass across every subsystem, including ones pytest doesn't cover
(the web UI's live routes, the docs site build).

Usage: python -m scripts.check_all [--skip-slow]
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (module, label, slow?) — order matters: later checks assume earlier
# subsystems work (e.g. chat checks assume ingestion/delta already ingest
# correctly), so a failure early tells you where to actually look first.
CHECKS = [
    ("scripts.checks.check_env", "Environment", False),
    ("scripts.checks.check_ingestion", "Ingestion (native/scanned/DXF)", False),
    ("scripts.checks.check_delta_engine", "Delta engine", False),
    ("scripts.checks.check_delta_report", "Delta report + markup", False),
    ("scripts.checks.check_retrieval", "Retrieval (BM25 index)", False),
    ("scripts.checks.check_observability", "Observability (tracing/logs)", False),
    ("scripts.checks.check_chat", "Grounded chat", False),
    ("scripts.checks.check_webapp", "Web UI (FastAPI routes)", False),
    ("scripts.checks.check_eval", "Eval harness", True),
    ("scripts.checks.check_docs", "MkDocs site build", True),
]


def main() -> None:
    skip_slow = "--skip-slow" in sys.argv
    results: list[tuple[str, bool, float]] = []

    print(f"Running {len(CHECKS)} subsystem checks{' (skipping slow ones)' if skip_slow else ''}...\n")

    for module, label, slow in CHECKS:
        if slow and skip_slow:
            print(f"\n== {label} == (skipped, --skip-slow)")
            continue
        start = time.time()
        proc = subprocess.run([sys.executable, "-m", module], cwd=ROOT)
        elapsed = time.time() - start
        results.append((label, proc.returncode == 0, elapsed))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_ok = True
    for label, ok, elapsed in results:
        status = "PASS" if ok else "FAIL"
        all_ok = all_ok and ok
        print(f"  [{status}] {label} ({elapsed:.1f}s)")
    print("=" * 60)

    if not results:
        print("No checks ran.")
        sys.exit(1)

    if all_ok:
        print("All subsystems OK.")
        sys.exit(0)
    else:
        failed = [label for label, ok, _ in results if not ok]
        print(f"FAILED: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
