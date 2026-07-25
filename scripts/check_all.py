from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHECKS = [
    ("scripts.checks.check_env", "Environment", False),
    ("scripts.checks.check_ingestion", "Ingestion (native/scanned/DXF)", False),
    ("scripts.checks.check_delta_engine", "Delta engine", False),
    ("scripts.checks.check_delta_report", "Delta report + markup", False),
    ("scripts.checks.check_retrieval", "Retrieval (BM25 index)", False),
    ("scripts.checks.check_observability", "Observability (tracing/logs)", False),
    ("scripts.checks.check_storage", "Storage (Mongo/Redis/MinIO/vector)", False),
    ("scripts.checks.check_metrics", "Prometheus metrics", False),
    ("scripts.checks.check_dvc", "DVC data versioning", False),
    ("scripts.checks.check_k8s", "Kubernetes manifests (kubeconform)", False),
    ("scripts.checks.check_chat", "Grounded chat", False),
    ("scripts.checks.check_webapp", "Web UI (FastAPI routes)", False),
    ("scripts.checks.check_tasks", "Background tasks (Celery)", True),
    ("scripts.checks.check_eval", "Eval harness", True),
    ("scripts.checks.check_docs", "MkDocs site build", True),
]


def main() -> None:
    skip_slow = "--skip-slow" in sys.argv
    results: list[tuple[str, bool, float]] = []

    print(f"Running {len(CHECKS)} subsystem checks{' (skipping slow ones)' if skip_slow else ''}...\n")

    passthrough = [a for a in ("--verbose", "--traceback") if a in sys.argv]

    for module, label, slow in CHECKS:
        if slow and skip_slow:
            print(f"\n== {label} == (skipped, --skip-slow)")
            continue
        start = time.time()
        proc = subprocess.run([sys.executable, "-m", module, *passthrough], cwd=ROOT)
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
