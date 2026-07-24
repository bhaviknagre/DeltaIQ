"""Check: the eval harness itself runs end-to-end and produces a
well-formed, non-degenerate scorecard. Slower than the other checks (runs
real delta + real chat against every Q&A question) — that's expected.

Usage: python -m scripts.checks.check_eval
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> None:
    suite = CheckSuite("eval")

    if not (ROOT / "data" / "samples" / "ground_truth.json").exists():
        suite.skip("all eval checks", "sample pairs not generated — run `make samples`")
        suite.exit()
        return

    from eval.run_eval import compute_pass_fail, run_chat_eval, run_delta_eval

    with suite.check("run_delta_eval produces well-formed scores for both pairs"):
        delta_results = run_delta_eval()
        assert set(delta_results) == {"native", "scanned"}, delta_results.keys()
        for name, r in delta_results.items():
            for key in ("precision", "recall", "f1", "avg_confidence", "criticality_counts"):
                assert key in r, f"{name} missing {key}"
        assert delta_results["native"]["f1"] == 1.0, "native pair should be an exact match on the demo sample"
        assert delta_results["scanned"]["ocr_accuracy"] is not None, "OCR accuracy not computed"

    with suite.check("run_chat_eval produces well-formed scores"):
        chat_results = run_chat_eval()
        for key in ("accuracy", "groundedness_rate", "citation_accuracy", "avg_latency_sec", "total_tokens"):
            assert key in chat_results, f"missing {key}"
        assert 0.0 <= chat_results["accuracy"] <= 1.0
        assert len(chat_results["per_qa"]) == 7, f"expected 7 QA results, got {len(chat_results['per_qa'])}"

    with suite.check("PASS/FAIL banner is computable and consistent with thresholds"):
        delta_results = run_delta_eval()
        chat_results = run_chat_eval()
        passed, reasons = compute_pass_fail(delta_results, chat_results)
        assert isinstance(passed, bool)
        assert passed or len(reasons) > 0, "FAIL with no reasons given"

    suite.exit()


if __name__ == "__main__":
    main()
