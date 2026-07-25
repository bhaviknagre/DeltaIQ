from __future__ import annotations

from pathlib import Path

import ezdxf

from src.canonical.model import BoundingBox, CanonicalDocument, DocumentMeta, Element, ElementType, Page
from src.ingest.base import FormatAdapter
from src.ingest.classify import classify_text


class DwgAdapter(FormatAdapter):
    format_name = "dwg"

    @classmethod
    def sniff(cls, path: Path) -> bool:
        return path.suffix.lower() in (".dxf", ".dwg")

    def parse(self, path: Path, pid: str, revision_label: str | None = None) -> CanonicalDocument:
        if path.suffix.lower() == ".dwg":
            raise NotImplementedError(
                "Real .dwg parsing requires converting to .dxf first (ODA File Converter or "
                "Autodesk SDK — no license-free pure-Python DWG reader exists). This adapter "
                "parses .dxf directly; point it at a converted file, or run the converter "
                "as a pre-step. See module docstring."
            )

        doc = ezdxf.readfile(path)
        msp = doc.modelspace()

        elements: list[Element] = []
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")

        for entity in msp:
            el = self._entity_to_element(entity)
            if el is None:
                continue
            elements.append(el)
            min_x, min_y = min(min_x, el.bbox.x0), min(min_y, el.bbox.y0)
            max_x, max_y = max(max_x, el.bbox.x1), max(max_y, el.bbox.y1)

        if not elements:
            min_x = min_y = 0.0
            max_x = max_y = 100.0

        page = Page(index=0, width=max_x - min_x, height=max_y - min_y, label="modelspace", elements=elements)

        return CanonicalDocument(
            meta=DocumentMeta(
                pid=pid,
                format=self.format_name,
                source_path=str(path),
                revision_label=revision_label,
                page_count=1,
                extra={"dxf_version": doc.dxfversion, "entity_count": len(elements)},
            ),
            pages=[page],
        )

    @staticmethod
    def _entity_to_element(entity) -> Element | None:
        dxftype = entity.dxftype()
        layer = entity.dxf.layer if entity.dxf.hasattr("layer") else "0"

        if dxftype in ("TEXT", "MTEXT"):
            text = entity.dxf.text if dxftype == "TEXT" else entity.text
            text = (text or "").strip()
            if not text:
                return None
            insert = entity.dxf.insert
            height = entity.dxf.char_height if entity.dxf.hasattr("char_height") else 2.5
            width = max(len(text) * height * 0.6, height)
            bbox = BoundingBox(x0=insert[0], y0=insert[1], x1=insert[0] + width, y1=insert[1] + height)
            return Element(
                id=Element.make_id(0, text, bbox),
                page_index=0,
                element_type=classify_text(text),
                text=text,
                bbox=bbox,
                confidence=1.0,
                source="dxf",
                attrs={"layer": layer, "dxftype": dxftype},
            )

        if dxftype == "LINE":
            start, end = entity.dxf.start, entity.dxf.end
            bbox = BoundingBox(
                x0=min(start[0], end[0]), y0=min(start[1], end[1]), x1=max(start[0], end[0]), y1=max(start[1], end[1])
            )
            label = f"LINE({layer})"
            return Element(
                id=Element.make_id(0, label + f"{bbox.x0}{bbox.y0}", bbox),
                page_index=0,
                element_type=ElementType.GEOMETRY,
                text=label,
                bbox=bbox,
                confidence=1.0,
                source="dxf",
                attrs={"layer": layer, "dxftype": dxftype},
            )

        if dxftype in ("LWPOLYLINE", "CIRCLE"):
            try:
                bbox_raw = entity.bbox() if hasattr(entity, "bbox") else None
            except Exception:
                bbox_raw = None
            if dxftype == "CIRCLE":
                c, r = entity.dxf.center, entity.dxf.radius
                bbox = BoundingBox(x0=c[0] - r, y0=c[1] - r, x1=c[0] + r, y1=c[1] + r)
            elif bbox_raw is not None and bbox_raw.has_data:
                bbox = BoundingBox(x0=bbox_raw.extmin[0], y0=bbox_raw.extmin[1], x1=bbox_raw.extmax[0], y1=bbox_raw.extmax[1])
            else:
                return None
            label = f"{dxftype}({layer})"
            return Element(
                id=Element.make_id(0, label + f"{bbox.x0}{bbox.y0}", bbox),
                page_index=0,
                element_type=ElementType.GEOMETRY,
                text=label,
                bbox=bbox,
                confidence=1.0,
                source="dxf",
                attrs={"layer": layer, "dxftype": dxftype},
            )

        return None
