from __future__ import annotations

from pathlib import Path

import fitz  
import pytesseract
from PIL import Image

from src.canonical.model import BoundingBox, CanonicalDocument, DocumentMeta, Element, Page
from src.config import settings
from src.ingest.base import FormatAdapter
from src.ingest.classify import classify_text
from src.observability.logging import get_logger, log_event

logger = get_logger("ingest.pdf_scanned")

MIN_CHARS_PER_PAGE_FOR_NATIVE = 20 


class ScannedPdfAdapter(FormatAdapter):
    format_name = "pdf_scanned"

    @classmethod
    def sniff(cls, path: Path) -> bool:
        if path.suffix.lower() not in (".pdf",):
            return False
        try:
            doc = fitz.open(path)
        except Exception:
            return False
        if doc.page_count == 0:
            return False
        avg_chars = sum(len(p.get_text().strip()) for p in doc) / doc.page_count
        has_images = any(len(p.get_images()) > 0 for p in doc)
        return avg_chars < MIN_CHARS_PER_PAGE_FOR_NATIVE and (has_images or doc.page_count > 0)

    def parse(self, path: Path, pid: str, revision_label: str | None = None) -> CanonicalDocument:
        doc = fitz.open(path)
        scale = 72.0 / settings.ocr_dpi
        render_dir = settings.data_dir / "renders" / pid
        render_dir.mkdir(parents=True, exist_ok=True)

        pages: list[Page] = []
        for page_index, pdf_page in enumerate(doc):
            mat = fitz.Matrix(settings.ocr_dpi / 72, settings.ocr_dpi / 72)
            pix = pdf_page.get_pixmap(matrix=mat)
            render_path = render_dir / f"page_{page_index}.png"
            pix.save(render_path)
            image = Image.open(render_path)

            try:
                ocr_data = pytesseract.image_to_data(
                    image,
                    lang=settings.ocr_lang,
                    config=f"--psm {settings.ocr_psm}",
                    output_type=pytesseract.Output.DICT,
                )
            except pytesseract.TesseractNotFoundError as exc:
                log_event(logger, 40, "tesseract_not_found", pid=pid, page=page_index, error=str(exc))
                raise

            elements = self._words_to_elements(ocr_data, page_index, scale)
            pages.append(
                Page(
                    index=page_index,
                    width=pdf_page.rect.width,
                    height=pdf_page.rect.height,
                    elements=elements,
                    render_path=str(render_path),
                )
            )
            log_event(logger, 20, "ocr_page_done", pid=pid, page=page_index, elements=len(elements))

        return CanonicalDocument(
            meta=DocumentMeta(
                pid=pid,
                format=self.format_name,
                source_path=str(path),
                revision_label=revision_label,
                page_count=len(pages),
                extra={"ocr_dpi": settings.ocr_dpi, "ocr_lang": settings.ocr_lang},
            ),
            pages=pages,
        )

    @staticmethod
    def _words_to_elements(ocr_data: dict, page_index: int, scale: float) -> list[Element]:
        """Group Tesseract's word-level output into line-level elements
        (matching native adapter's granularity) keyed by (block, par, line)."""
        lines: dict[tuple, dict] = {}
        n = len(ocr_data["text"])
        for i in range(n):
            word = ocr_data["text"][i].strip()
            conf = float(ocr_data["conf"][i])
            if not word or conf < 0:
                continue
            key = (ocr_data["block_num"][i], ocr_data["par_num"][i], ocr_data["line_num"][i])
            x, y, w, h = ocr_data["left"][i], ocr_data["top"][i], ocr_data["width"][i], ocr_data["height"][i]
            entry = lines.setdefault(key, {"words": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h, "confs": []})
            entry["words"].append(word)
            entry["x0"] = min(entry["x0"], x)
            entry["y0"] = min(entry["y0"], y)
            entry["x1"] = max(entry["x1"], x + w)
            entry["y1"] = max(entry["y1"], y + h)
            entry["confs"].append(conf)

        elements: list[Element] = []
        for entry in lines.values():
            text = " ".join(entry["words"]).strip()
            if not text:
                continue
            bbox = BoundingBox(
                x0=entry["x0"] * scale, y0=entry["y0"] * scale, x1=entry["x1"] * scale, y1=entry["y1"] * scale
            )
            avg_conf = sum(entry["confs"]) / len(entry["confs"]) / 100.0
            elements.append(
                Element(
                    id=Element.make_id(page_index, text, bbox),
                    page_index=page_index,
                    element_type=classify_text(text),
                    text=text,
                    bbox=bbox,
                    confidence=round(avg_conf, 3),
                    source="ocr",
                )
            )
        return elements
