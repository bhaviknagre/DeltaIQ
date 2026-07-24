"""Builds the sample PID revision pairs used for demos and eval ground truth.

Provenance: the two source PDFs (export_gas_compressor.pdf,
lift_gas_compressor.pdf, under data/samples/raw/) are real, born-digital
P&ID export sheets supplied for this assignment. They are two *different*
drawings, not two revisions of one drawing, so they can't directly serve as
a PID-A/PID-B pair (the assignment needs revisions of the *same* underlying
document with a knowable delta).

This script synthesizes two revision pairs from that real material, exactly
as the assignment's own FAQ suggests ("edit a PDF and re-export"):

1. pair_native/ — export_gas_compressor.pdf duplicated verbatim as Rev A,
   then edited in place with PyMuPDF (redact + re-insert text at the same
   font/size/position) to produce Rev B. Every edit is listed in
   GROUND_TRUTH below with its exact type/location, giving an exact-known
   delta for eval instead of a guessed one.

2. pair_scanned/ — Rev A and Rev B of the native pair, rasterized to images
   at 300dpi and re-saved as image-only PDFs (no text layer), simulating a
   scan/photograph of the same revision pair. Exercises the OCR ingestion
   path end-to-end on the *same* known delta, so delta P/R/F1 can be
   compared native-vs-scanned on identical ground truth.

Run: python -m data.samples.build_synthetic_pairs
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
NATIVE_DIR = HERE / "pair_native"
SCANNED_DIR = HERE / "pair_scanned"

# Each edit: (kind, old_text_or_None, new_text_or_None, bbox, font, size)
# kind in {"modify", "remove", "add"} — this IS the ground truth delta.
EDITS = [
    {
        "id": "gt-1",
        "kind": "modify",
        "category": "tag",
        "old_text": "26-KA-902",
        "new_text": "26-KA-902B",
        "bbox": (446.52, 405.23, 485.74, 414.47),
        "font": "helv",
        "size": 9.24,
        "description": "Compressor tag 26-KA-902 revised to 26-KA-902B (unit re-tagged).",
    },
    {
        "id": "gt-2",
        "kind": "modify",
        "category": "dimension",
        "old_text": '3/4"-DC-26-9026-FC11S-00',
        "new_text": '1"-DC-26-9026-FC11S-00',
        "bbox": (654.12, 565.75, 717.62, 571.52),
        "font": "helv",
        "size": 5.77,
        "description": 'Drain line size increased from 3/4" to 1" on line spec DC-26-9026-FC11S-00.',
    },
    {
        "id": "gt-3",
        "kind": "modify",
        "category": "tag",
        "old_text": "57-9005",
        "new_text": "57-9006",
        "bbox": (812.04, 560.47, 831.37, 566.24),
        "font": "helv",
        "size": 5.77,
        "description": "Closed-drain tag 57-9005 renumbered to 57-9006.",
    },
    {
        "id": "gt-4",
        "kind": "remove",
        "category": "text",
        "old_text": "TO CLOSED DRAIN",
        "new_text": None,
        "bbox": (1116.84, 563.47, 1159.63, 569.24),
        "font": "helv",
        "size": 5.77,
        "description": "Callout 'TO CLOSED DRAIN' removed (routing note deleted).",
    },
    {
        "id": "gt-5",
        "kind": "add",
        "category": "tag",
        "old_text": None,
        "new_text": "26-PSV-9099",
        "bbox": (900.0, 700.0, 960.0, 707.0),
        "font": "helv",
        "size": 6.5,
        "description": "New pressure safety valve tag 26-PSV-9099 added.",
    },
    {
        "id": "gt-6",
        "kind": "add",
        "category": "note",
        "old_text": None,
        "new_text": "NOTE 99 ADDED PSV PER MOC-1042.",
        "bbox": (900.0, 715.0, 1040.0, 722.0),
        "font": "helv",
        "size": 6.5,
        "description": "New note added referencing MOC-1042 for the added PSV.",
    },
]


def build_native_pair() -> None:
    NATIVE_DIR.mkdir(parents=True, exist_ok=True)
    src = RAW / "export_gas_compressor.pdf"

    rev_a_path = NATIVE_DIR / "rev_a.pdf"
    rev_b_path = NATIVE_DIR / "rev_b.pdf"

    doc_a = fitz.open(src)
    doc_a.save(rev_a_path)
    doc_a.close()

    doc_b = fitz.open(src)
    page = doc_b[0]
    for edit in EDITS:
        x0, y0, x1, y1 = edit["bbox"]
        if edit["kind"] in ("modify", "remove"):
            pad = 0.6
            rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
            page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions()

    for edit in EDITS:
        if edit["kind"] in ("modify", "add"):
            x0, y0, x1, y1 = edit["bbox"]
            page.insert_text((x0, y1 - 1.0), edit["new_text"], fontsize=edit["size"], fontname="helv", color=(0, 0, 0))

    doc_b.save(rev_b_path)
    doc_b.close()
    print(f"native pair -> {rev_a_path}, {rev_b_path}")


def build_scanned_pair() -> None:
    SCANNED_DIR.mkdir(parents=True, exist_ok=True)
    dpi = 300
    for name in ("rev_a", "rev_b"):
        src = NATIVE_DIR / f"{name}.pdf"
        doc = fitz.open(src)
        page = doc[0]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)

        out_doc = fitz.open()
        out_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
        out_page.insert_image(out_page.rect, pixmap=pix)
        out_path = SCANNED_DIR / f"{name}.pdf"
        out_doc.save(out_path)
        out_doc.close()
        doc.close()
        print(f"scanned pair -> {out_path} (image-only, {dpi}dpi, no text layer)")


def write_ground_truth() -> None:
    gt = {
        "pair_native": {"pid_a": "26-9026-REV-A", "pid_b": "26-9026-REV-B", "edits": EDITS},
        "pair_scanned": {"pid_a": "26-9026-REV-A-SCAN", "pid_b": "26-9026-REV-B-SCAN", "edits": EDITS},
        "provenance": {
            "source": "export_gas_compressor.pdf (real, supplied P&ID export sheet)",
            "method": "PyMuPDF redact+reinsert on the native PDF text layer to produce Rev B "
            "from Rev A with an exactly-known set of edits (see 'edits'); pair_scanned "
            "rasterizes both revisions to 300dpi image-only PDFs to simulate a scan.",
        },
    }
    (HERE / "ground_truth.json").write_text(json.dumps(gt, indent=2))
    print(f"ground truth -> {HERE / 'ground_truth.json'}")


if __name__ == "__main__":
    build_native_pair()
    build_scanned_pair()
    write_ground_truth()
