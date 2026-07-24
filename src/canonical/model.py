"""Format-agnostic canonical representation.

Every ingestion adapter (native PDF, scanned PDF, DWG/DXF, ...) normalizes its
source into this model. Everything downstream (delta engine, retrieval, chat,
markup) only ever sees this model and never touches format-specific bytes
again. This is the seam described in the assignment: to add a 4th format you
write one adapter that emits a CanonicalDocument — nothing else changes.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ElementType(str, Enum):
    """Classification of a single piece of content on a sheet.

    Kept deliberately small and domain-relevant (P&ID / engineering drawing
    vocabulary) rather than a generic "span" — the delta engine and chat
    layer both reason about *what kind* of thing changed.
    """

    TAG = "tag"  # equipment/instrument tag, e.g. 26-KA-902, 26-PDI-9054
    DIMENSION = "dimension"  # numeric dimension / size / tolerance, e.g. 3/4"-DC-26-9026
    NOTE = "note"  # numbered or free-text note / callout
    TEXT = "text"  # generic label / text block that isn't one of the above
    TABLE_CELL = "table_cell"  # cell inside a detected tabular region
    GEOMETRY = "geometry"  # vector geometry (line/arc/polyline run) — DXF/DWG only


class BoundingBox(BaseModel):
    """Location of an element on its page, in PDF/page point space
    (origin top-left, consistent across native-PDF and rasterized-scan
    adapters because we always record the page size alongside it)."""

    x0: float
    y0: float
    x1: float
    y1: float

    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)

    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


class Element(BaseModel):
    """A single located, typed piece of content on a page/sheet."""

    id: str  # stable within one CanonicalDocument, derived from content+position
    page_index: int
    element_type: ElementType
    text: str
    bbox: BoundingBox
    confidence: float = 1.0  # extraction confidence (1.0 for native text, OCR conf for scans)
    source: str = "native"  # "native" | "ocr" | "dxf" | ...
    attrs: dict = Field(default_factory=dict)  # e.g. {"layer": "..."} for DXF

    @staticmethod
    def make_id(page_index: int, text: str, bbox: BoundingBox) -> str:
        h = hashlib.sha1(f"{page_index}:{text}:{bbox.x0:.1f}:{bbox.y0:.1f}".encode()).hexdigest()
        return h[:12]


class Page(BaseModel):
    """One page (PDF) or sheet (DWG layout)."""

    index: int
    width: float
    height: float
    label: Optional[str] = None  # sheet name/number if known
    elements: list[Element] = Field(default_factory=list)
    render_path: Optional[str] = None  # optional rasterized PNG for markup overlay


class DocumentMeta(BaseModel):
    pid: str
    format: str  # "pdf_native" | "pdf_scanned" | "dwg" | "dxf"
    source_path: str
    revision_label: Optional[str] = None
    page_count: int = 0
    extra: dict = Field(default_factory=dict)


class CanonicalDocument(BaseModel):
    """The normalized, format-agnostic representation of one PID."""

    meta: DocumentMeta
    pages: list[Page] = Field(default_factory=list)

    def all_elements(self) -> list[Element]:
        return [e for p in self.pages for e in p.elements]

    def element_by_id(self, element_id: str) -> Optional[Element]:
        for e in self.all_elements():
            if e.id == element_id:
                return e
        return None
