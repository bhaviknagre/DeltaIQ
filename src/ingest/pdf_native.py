from __future__ import annotations

from pathlib import Path

import fitz  

from src.canonical.model import BoundingBox, CanonicalDocument, DocumentMeta, Element, Page
from src.ingest.base import FormatAdapter
from src.ingest.classify import classify_text

MIN_CHARS_PER_PAGE_FOR_NATIVE = 20


class NativePdfAdapter(FormatAdapter):
    format_name = "pdf_native"

    @classmethod
    def sniff(cls, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        try:
            doc = fitz.open(path)
        except Exception:
            return False
        if doc.page_count == 0:
            return False
        avg_chars = sum(len(p.get_text().strip()) for p in doc) / doc.page_count
        return avg_chars >= MIN_CHARS_PER_PAGE_FOR_NATIVE

    def parse(self, path: Path, pid: str, revision_label: str | None = None) -> CanonicalDocument:
        doc = fitz.open(path)
        pages: list[Page] = []
        for page_index, pdf_page in enumerate(doc):
            elements: list[Element] = []
            raw = pdf_page.get_text("dict")
            for block in raw.get("blocks", []):
                for line in block.get("lines", []):
                    text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = line["bbox"]
                    bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
                    elements.append(
                        Element(
                            id=Element.make_id(page_index, text, bbox),
                            page_index=page_index,
                            element_type=classify_text(text),
                            text=text,
                            bbox=bbox,
                            confidence=1.0,
                            source="native",
                        )
                    )
            pages.append(Page(index=page_index, width=pdf_page.rect.width, height=pdf_page.rect.height, elements=elements))

        return CanonicalDocument(
            meta=DocumentMeta(
                pid=pid,
                format=self.format_name,
                source_path=str(path),
                revision_label=revision_label,
                page_count=len(pages),
            ),
            pages=pages,
        )
