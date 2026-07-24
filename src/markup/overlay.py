"""Bonus: draws the delta back onto PID B as a redline-style overlay —
boxes colored by criticality (red/yellow/green), labeled with the change
kind, exported as an annotated PDF. Only meaningful for formats with a
renderable page (native/scanned PDF); for a DXF/DWG-sourced document this
would need a rasterizer first, out of scope here (see README cuts).

Colored by criticality rather than change kind: change kind (added/removed/
modified) tells you *what* happened, criticality tells you *whether you
should care* — a removed note and a removed dimension are both "removed"
but very different in engineering significance (see delta/criticality.py).
"""

from __future__ import annotations

from pathlib import Path

import fitz

from src.delta.criticality import Criticality
from src.delta.engine import DeltaResult

COLOR_BY_CRITICALITY = {
    Criticality.RED: (0.85, 0.1, 0.1),
    Criticality.YELLOW: (0.85, 0.65, 0.0),
    Criticality.GREEN: (0.1, 0.6, 0.2),
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
            color = COLOR_BY_CRITICALITY[item.criticality]
            page.draw_rect(rect, color=color, width=1.2)
            label = f"{item.criticality.value[0].upper()}-{item.change_kind.value[:3].upper()}"
            page.insert_text((rect.x0, max(rect.y0 - 2, 8)), label, fontsize=6, color=color)

    legend_page = src[0]
    y = 10
    for crit, color in COLOR_BY_CRITICALITY.items():
        legend_page.draw_rect(fitz.Rect(10, y, 20, y + 8), color=color, fill=color)
        legend_page.insert_text((24, y + 7), f"{crit.value} criticality", fontsize=7, color=(0, 0, 0))
        y += 12

    out_path.parent.mkdir(parents=True, exist_ok=True)
    src.save(out_path)
    return out_path
