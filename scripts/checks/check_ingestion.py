"""Check: all three format adapters actually ingest into CanonicalDocument
correctly — native PDF, scanned PDF (OCR), and DXF (the DWG seam). Also
checks format auto-detection routes each file to the right adapter.

Usage: python -m scripts.checks.check_ingestion
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent
NATIVE_A = ROOT / "data" / "samples" / "pair_native" / "rev_a.pdf"
SCANNED_A = ROOT / "data" / "samples" / "pair_scanned" / "rev_a.pdf"

_SAMPLE_DXF = """0
SECTION
2
ENTITIES
0
TEXT
8
0
10
0.0
20
0.0
40
2.5
1
26-CHECK-9001
0
LINE
8
0
10
0.0
20
0.0
11
10.0
21
0.0
0
ENDSEC
0
EOF
"""


def main() -> None:
    suite = CheckSuite("ingestion")

    if not NATIVE_A.exists():
        suite.skip("native PDF adapter", "sample not generated — run `make samples`")
    else:
        with suite.check("native PDF adapter: sniff + parse"):
            from src.ingest.pdf_native import NativePdfAdapter

            assert NativePdfAdapter.sniff(NATIVE_A), "sniff() rejected a known-native PDF"
            doc = NativePdfAdapter().parse(NATIVE_A, pid="check-native")
            assert doc.meta.format == "pdf_native"
            assert len(doc.all_elements()) > 100, f"expected >100 elements, got {len(doc.all_elements())}"
            assert doc.summary()["dimensions"] > 0, "no dimension-type elements classified"

    if not SCANNED_A.exists():
        suite.skip("scanned PDF adapter", "sample not generated — run `make samples`")
    else:
        with suite.check("scanned PDF adapter: sniff + parse (OCR)"):
            from src.ingest.pdf_scanned import ScannedPdfAdapter

            assert ScannedPdfAdapter.sniff(SCANNED_A), "sniff() rejected a known-scanned PDF"
            doc = ScannedPdfAdapter().parse(SCANNED_A, pid="check-scanned")
            assert doc.meta.format == "pdf_scanned"
            assert len(doc.all_elements()) > 20, f"OCR produced too few elements: {len(doc.all_elements())}"

    with suite.check("DXF adapter: sniff + parse (real DWG seam)"):
        from src.ingest.dwg import DwgAdapter

        with tempfile.TemporaryDirectory() as td:
            dxf_path = Path(td) / "check.dxf"
            dxf_path.write_text(_SAMPLE_DXF)
            assert DwgAdapter.sniff(dxf_path), "sniff() rejected a .dxf file"
            doc = DwgAdapter().parse(dxf_path, pid="check-dxf")
            assert doc.meta.format == "dwg"
            elements = doc.all_elements()
            assert len(elements) == 2, f"expected 1 TEXT + 1 LINE element, got {len(elements)}"
            assert any(e.text == "26-CHECK-9001" for e in elements), "TEXT entity not recovered"

    with suite.check("DXF adapter: .dwg raises the documented NotImplementedError"):
        from src.ingest.dwg import DwgAdapter

        with tempfile.TemporaryDirectory() as td:
            fake_dwg = Path(td) / "check.dwg"
            fake_dwg.write_bytes(b"not a real dwg")
            try:
                DwgAdapter().parse(fake_dwg, pid="check-dwg")
                raise AssertionError(".dwg parse should have raised NotImplementedError")
            except NotImplementedError:
                pass

    if NATIVE_A.exists() and SCANNED_A.exists():
        with suite.check("format auto-detection routes both samples to the right adapter"):
            from src.ingest.base import registry
            from src.ingest.pdf_native import NativePdfAdapter
            from src.ingest.pdf_scanned import ScannedPdfAdapter
            import src.ingest.pid_store  # noqa: F401 - registers adapters into `registry`

            assert registry.resolve(NATIVE_A) is NativePdfAdapter
            assert registry.resolve(SCANNED_A) is ScannedPdfAdapter

    suite.exit()


if __name__ == "__main__":
    main()
