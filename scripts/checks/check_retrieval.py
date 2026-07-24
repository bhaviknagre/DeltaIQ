"""Check: BM25 retrieval index — exact-tag matching, the hard lexical-
overlap gate (regression check for the "off-topic query returns nothing"
fix), and citation correctness.

Usage: python -m scripts.checks.check_retrieval
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent
NATIVE_A = ROOT / "data" / "samples" / "pair_native" / "rev_a.pdf"
NATIVE_B = ROOT / "data" / "samples" / "pair_native" / "rev_b.pdf"


def main() -> None:
    suite = CheckSuite("retrieval")

    if not (NATIVE_A.exists() and NATIVE_B.exists()):
        suite.skip("all retrieval checks", "sample pair not generated — run `make samples`")
        suite.exit()
        return

    from src.chat.index import build_index
    from src.delta.engine import compute_delta
    from src.ingest.pid_store import load, register_pid

    register_pid("check-retr-a", str(NATIVE_A), "Rev A")
    register_pid("check-retr-b", str(NATIVE_B), "Rev B")
    doc_a = load("check-retr-a")
    doc_b = load("check-retr-b")
    delta = compute_delta(doc_a, doc_b)
    index = build_index(doc_a, doc_b, delta)

    with suite.check("exact tag query retrieves the matching delta entry"):
        hits = index.search("26-KA-902", top_k=8, min_score=0.05)
        assert len(hits) > 0, "no hits for an exact known tag"
        assert any(c.citation.source == "delta_report" for c, _ in hits), "delta-report chunk not surfaced/boosted"

    with suite.check("off-topic query (no lexical overlap) returns nothing — hard gate holds"):
        hits = index.search("banana spaceship unrelated gibberish", top_k=8, min_score=0.05)
        assert hits == [], f"expected no hits, got {len(hits)}"

    with suite.check("top-k window has no exact-duplicate-text crowding"):
        hits = index.search("26-KA-902", top_k=8, min_score=0.05)
        seen = set()
        for chunk, _ in hits:
            key = (chunk.citation.source, chunk.text)
            assert key not in seen, f"duplicate chunk in top-k: {key}"
            seen.add(key)

    suite.exit()


if __name__ == "__main__":
    main()
