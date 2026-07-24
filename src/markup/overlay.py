"""Bonus: draws the delta back onto PID B as a redline-style overlay —
colored bounding boxes per change kind, exported as an annotated PDF. Only
meaningful for formats with a renderable page (native/scanned PDF); for a
DXF/DWG-sourced document this would need a rasterizer first, out of scope
here (see README cuts).
"""

from __future__ import annotations

from pathlib import Path

import fitz

from src.canonical.model import CanonicalDocument
from src.delta.engine import ChangeKind, DeltaResult

COLOR_BY_KIND = {
    ChangeKind.ADDED: (0, 0.6, 0),  # green
    ChangeKind.REMOVED: (0.8, 0, 0),  # red
    ChangeKind.MODIFIED: (0.9, 0.6, 0),  # amber
}


def render_markup(doc_b_source_path: Path, delta: DeltaResult, out_path: Path) -> Path:
    """Overlays delta boxes onto the *revised* document's own PDF pages.
    Requires PID B's source to be a PDF (native or scanned)."""
    src = fitz.open(doc_b_source_path)

    items_by_page: dict[int, list] = {}
    for item in delta.items:
        items_by_page.setdefault(item.page_index, []).append(item)

    for page_index, page in enumerate(src):
        for item in items_by_page.get(page_index, []):
            rect = fitz.Rect(item.bbox.x0, item.bbox.y0, item.bbox.x1, item.bbox.y1)
            color = COLOR_BY_KIND[item.change_kind]
            page.draw_rect(rect, color=color, width=1.2)
            label = f"{item.change_kind.value[:3].upper()}"
            page.insert_text((rect.x0, max(rect.y0 - 2, 8)), label, fontsize=6, color=color)

    legend_page = src[0]
    y = 10
    for kind, color in COLOR_BY_KIND.items():
        legend_page.draw_rect(fitz.Rect(10, y, 20, y + 8), color=color, fill=color)
        legend_page.insert_text((24, y + 7), kind.value, fontsize=7, color=(0, 0, 0))
        y += 12

    out_path.parent.mkdir(parents=True, exist_ok=True)
    src.save(out_path)
    return out_path
