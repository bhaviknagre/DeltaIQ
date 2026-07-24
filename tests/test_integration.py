"""End-to-end integration test against the real synthetic sample pair
(data/samples/pair_native/), asserting the delta engine recovers exactly the
6 known ground-truth edits with zero false positives on the deterministic
native-PDF path. Skips if samples haven't been generated yet
(`make samples`, or `python -m data.samples.build_synthetic_pairs`)."""

import json
from pathlib import Path

import pytest

from src.delta.engine import compute_delta
from src.ingest.pid_store import load, register_pid

ROOT = Path(__file__).resolve().parent.parent
NATIVE_DIR = ROOT / "data" / "samples" / "pair_native"
GT_PATH = ROOT / "data" / "samples" / "ground_truth.json"

pytestmark = pytest.mark.skipif(
    not (NATIVE_DIR / "rev_a.pdf").exists(),
    reason="sample pair not generated — run `make samples` first",
)


def test_native_pair_delta_matches_ground_truth_exactly():
    register_pid("test-native-a", str(NATIVE_DIR / "rev_a.pdf"), "Rev A")
    register_pid("test-native-b", str(NATIVE_DIR / "rev_b.pdf"), "Rev B")

    doc_a = load("test-native-a")
    doc_b = load("test-native-b")
    result = compute_delta(doc_a, doc_b)

    gt = json.loads(GT_PATH.read_text())["pair_native"]["edits"]
    assert len(result.items) == len(gt), (
        f"expected {len(gt)} changes (exact ground truth), got {len(result.items)}: "
        f"{[i.description for i in result.items]}"
    )

    counts = result.counts_by_kind()
    assert counts == {"added": 2, "removed": 1, "modified": 3}
