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

    TAG = "tag"  
    DIMENSION = "dimension"  
    NOTE = "note"  
    TEXT = "text"  
    TABLE_CELL = "table_cell"  
    GEOMETRY = "geometry" 


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

    id: str  
    page_index: int
    element_type: ElementType
    text: str
    bbox: BoundingBox
    confidence: float = 1.0  
    source: str = "native"  
    attrs: dict = Field(default_factory=dict)  

    @staticmethod
    def make_id(page_index: int, text: str, bbox: BoundingBox) -> str:
        h = hashlib.sha1(f"{page_index}:{text}:{bbox.x0:.1f}:{bbox.y0:.1f}".encode()).hexdigest()
        return h[:12]


class Page(BaseModel):
    """One page (PDF) or sheet (DWG layout)."""

    index: int
    width: float
    height: float
    label: Optional[str] = None  
    elements: list[Element] = Field(default_factory=list)
    render_path: Optional[str] = None  

class DocumentMeta(BaseModel):
    pid: str
    format: str  
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

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for e in self.all_elements():
            counts[e.element_type.value] = counts.get(e.element_type.value, 0) + 1
        return {
            "pid": self.meta.pid,
            "format": self.meta.format,
            "revision_label": self.meta.revision_label,
            "pages": len(self.pages),
            "elements": len(self.all_elements()),
            "tags": counts.get("tag", 0),
            "dimensions": counts.get("dimension", 0),
            "notes": counts.get("note", 0),
            "tables": counts.get("table_cell", 0),
            "text": counts.get("text", 0),
            "geometry": counts.get("geometry", 0),
        }
