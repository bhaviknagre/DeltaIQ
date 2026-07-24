"""Check: delta report rendering (Markdown + JSON) and the markup overlay.

Usage: python -m scripts.checks.check_delta_report
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent
NATIVE_A = ROOT / "data" / "samples" / "pair_native" / "rev_a.pdf"
NATIVE_B = ROOT / "data" / "samples" / "pair_native" / "rev_b.pdf"


def main() -> None:
    suite = CheckSuite("delta_report")

    if not (NATIVE_A.exists() and NATIVE_B.exists()):
        suite.skip("all delta_report checks", "sample pair not generated — run `make samples`")
        suite.exit()
        return

    from src.delta.engine import compute_delta
    from src.delta.report import to_json, to_markdown, write_report
    from src.ingest.pid_store import load, register_pid
    from src.markup.overlay import render_markup

    register_pid("check-report-a", str(NATIVE_A), "Rev A")
    register_pid("check-report-b", str(NATIVE_B), "Rev B")
    doc_a = load("check-report-a")
    doc_b = load("check-report-b")
    delta = compute_delta(doc_a, doc_b)

    with suite.check("markdown report contains signal + grouped sections"):
        md = to_markdown(delta, "check-report-a", "check-report-b")
        for marker in ("## Added", "## Modified", "## Removed", "🔴", "🟡"):
            assert marker in md, f"missing {marker!r} in rendered report"

    with suite.check("JSON report round-trips item count"):
        payload = to_json(delta)
        assert len(payload["items"]) == len(delta.items)
        assert "criticality" in payload["items"][0]

    with suite.check("write_report writes both files to disk"):
        with tempfile.TemporaryDirectory() as td:
            paths = write_report(delta, Path(td))
            assert Path(paths["markdown_path"]).stat().st_size > 0
            assert Path(paths["json_path"]).stat().st_size > 0

    with suite.check("markup overlay produces a non-trivial PDF"):
        with tempfile.TemporaryDirectory() as td:
            out = render_markup(NATIVE_B, delta, Path(td) / "markup.pdf")
            size = out.stat().st_size
            assert size > 1000, f"markup PDF suspiciously small: {size} bytes"

    suite.exit()


if __name__ == "__main__":
    main()
