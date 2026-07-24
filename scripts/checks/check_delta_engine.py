"""Check: the delta engine — alignment, classification, confidence, and the
criticality signal — against exact ground truth, plus a determinism check
(same input -> byte-identical structural output).

Usage: python -m scripts.checks.check_delta_engine
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent
NATIVE_A = ROOT / "data" / "samples" / "pair_native" / "rev_a.pdf"
NATIVE_B = ROOT / "data" / "samples" / "pair_native" / "rev_b.pdf"
GT_PATH = ROOT / "data" / "samples" / "ground_truth.json"


def main() -> None:
    suite = CheckSuite("delta_engine")

    if not (NATIVE_A.exists() and NATIVE_B.exists()):
        suite.skip("all delta_engine checks", "sample pair not generated — run `make samples`")
        suite.exit()
        return

    from src.delta.engine import compute_delta
    from src.ingest.pid_store import load, register_pid

    register_pid("check-delta-a", str(NATIVE_A), "Rev A")
    register_pid("check-delta-b", str(NATIVE_B), "Rev B")
    doc_a = load("check-delta-a")
    doc_b = load("check-delta-b")

    with suite.check("compute_delta matches exact ground truth (6 edits, 0 FP)"):
        result = compute_delta(doc_a, doc_b)
        gt = json.loads(GT_PATH.read_text())["pair_native"]["edits"]
        assert len(result.items) == len(gt), f"expected {len(gt)} changes, got {len(result.items)}"
        counts = result.counts_by_kind()
        assert counts == {"added": 2, "removed": 1, "modified": 3}, counts

    with suite.check("every DeltaItem has a criticality signal, distribution is sane"):
        result = compute_delta(doc_a, doc_b)
        crit = result.counts_by_criticality()
        assert sum(crit.values()) == len(result.items)
        assert crit["red"] >= 1, "expected at least one red (dimension change) in the demo pair"

    with suite.check("confidence is in [0, 1] for every item"):
        result = compute_delta(doc_a, doc_b)
        assert all(0.0 <= it.confidence <= 1.0 for it in result.items)

    with suite.check("determinism: two runs on the same input produce identical output"):
        r1 = compute_delta(doc_a, doc_b)
        r2 = compute_delta(doc_a, doc_b)
        assert r1.model_dump_json() == r2.model_dump_json(), "non-deterministic delta output"

    suite.exit()


if __name__ == "__main__":
    main()
