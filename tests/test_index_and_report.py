from src.canonical.model import BoundingBox, CanonicalDocument, DocumentMeta, Element, ElementType, Page
from src.chat.index import build_index
from src.delta.engine import compute_delta
from src.delta.report import to_json, to_markdown


def doc_with(pid: str, elements: list[Element]) -> CanonicalDocument:
    page = Page(index=0, width=1000, height=1000, elements=elements)
    return CanonicalDocument(meta=DocumentMeta(pid=pid, format="pdf_native", source_path=f"{pid}.pdf"), pages=[page])


def el(text, x0, y0, etype=ElementType.TAG):
    bbox = BoundingBox(x0=x0, y0=y0, x1=x0 + 20, y1=y0 + 8)
    return Element(id=Element.make_id(0, text, bbox), page_index=0, element_type=etype, text=text, bbox=bbox)


def _sample_delta():
    doc_a = doc_with("a", [el("57-9005", 10, 10), el("TO CLOSED DRAIN", 200, 200, ElementType.TEXT)])
    doc_b = doc_with("b", [el("57-9006", 10, 10), el("26-PSV-9099", 300, 300)])
    return doc_a, doc_b, compute_delta(doc_a, doc_b)


def test_report_markdown_contains_all_change_kinds():
    doc_a, doc_b, delta = _sample_delta()
    md = to_markdown(delta, "PID-A", "PID-B")
    assert "MODIFIED" in md
    assert "REMOVED" in md
    assert "ADDED" in md
    assert "PID-A" in md and "PID-B" in md


def test_report_json_roundtrips_counts():
    _, _, delta = _sample_delta()
    payload = to_json(delta)
    assert len(payload["items"]) == len(delta.items)
    assert payload["pid_a"] == "a"
    assert payload["pid_b"] == "b"


def test_index_retrieves_relevant_chunk_for_exact_tag_query():
    doc_a, doc_b, delta = _sample_delta()
    index = build_index(doc_a, doc_b, delta)
    hits = index.search("57-9005", top_k=5, min_score=0.05)
    assert len(hits) > 0
    assert any("57-9005" in c.text for c, _ in hits)


def test_index_returns_nothing_for_query_with_no_lexical_overlap():
    doc_a, doc_b, delta = _sample_delta()
    index = build_index(doc_a, doc_b, delta)
    hits = index.search("banana spaceship unrelated", top_k=5, min_score=0.05)
    assert hits == []
