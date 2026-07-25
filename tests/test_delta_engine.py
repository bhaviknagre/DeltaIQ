from src.canonical.model import BoundingBox, CanonicalDocument, DocumentMeta, Element, ElementType, Page
from src.delta.engine import ChangeKind, compute_delta


def doc_with(pid: str, elements: list[Element]) -> CanonicalDocument:
    page = Page(index=0, width=1000, height=1000, elements=elements)
    return CanonicalDocument(meta=DocumentMeta(pid=pid, format="pdf_native", source_path=f"{pid}.pdf"), pages=[page])


def el(text, x0, y0, etype=ElementType.TAG):
    bbox = BoundingBox(x0=x0, y0=y0, x1=x0 + 20, y1=y0 + 8)
    return Element(id=Element.make_id(0, text, bbox), page_index=0, element_type=etype, text=text, bbox=bbox)


def test_identical_documents_have_no_delta():
    elements = [el("26-KA-902", 10, 10), el("NOTE 1", 50, 50, ElementType.NOTE)]
    doc_a = doc_with("a", elements)
    doc_b = doc_with("b", [el(e.text, e.bbox.x0, e.bbox.y0, e.element_type) for e in elements])

    result = compute_delta(doc_a, doc_b)
    assert result.items == []
    assert result.unchanged_count == 2


def test_added_element_detected():
    doc_a = doc_with("a", [el("26-KA-902", 10, 10)])
    doc_b = doc_with("b", [el("26-KA-902", 10, 10), el("26-PSV-9099", 200, 200)])

    result = compute_delta(doc_a, doc_b)
    assert len(result.items) == 1
    assert result.items[0].change_kind == ChangeKind.ADDED
    assert result.items[0].after_text == "26-PSV-9099"


def test_removed_element_detected():
    doc_a = doc_with("a", [el("26-KA-902", 10, 10), el("TO CLOSED DRAIN", 200, 200, ElementType.TEXT)])
    doc_b = doc_with("b", [el("26-KA-902", 10, 10)])

    result = compute_delta(doc_a, doc_b)
    assert len(result.items) == 1
    assert result.items[0].change_kind == ChangeKind.REMOVED
    assert result.items[0].before_text == "TO CLOSED DRAIN"


def test_modified_text_at_same_position_detected():
    doc_a = doc_with("a", [el("57-9005", 10, 10)])
    doc_b = doc_with("b", [el("57-9006", 10, 10)])

    result = compute_delta(doc_a, doc_b)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.change_kind == ChangeKind.MODIFIED
    assert item.before_text == "57-9005"
    assert item.after_text == "57-9006"
    assert item.confidence > 0.5


def test_moved_but_unchanged_text_is_flagged_as_modified():
    doc_a = doc_with("a", [el("26-KA-902", 10, 10)])
    doc_b = doc_with("b", [el("26-KA-902", 10, 60)])  

    result = compute_delta(doc_a, doc_b)
    assert len(result.items) == 1
    assert result.items[0].change_kind == ChangeKind.MODIFIED
    assert "moved" in result.items[0].description.lower() or "position" in result.items[0].description.lower()


def test_confidence_is_reproducible_across_runs():
    doc_a = doc_with("a", [el("57-9005", 10, 10)])
    doc_b = doc_with("b", [el("57-9006", 10, 10)])

    r1 = compute_delta(doc_a, doc_b)
    r2 = compute_delta(doc_a, doc_b)
    assert r1.items[0].confidence == r2.items[0].confidence
    assert r1.counts_by_kind() == r2.counts_by_kind()
