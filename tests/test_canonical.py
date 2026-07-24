from src.canonical.model import BoundingBox, CanonicalDocument, DocumentMeta, Element, ElementType, Page


def make_element(text="26-KA-902", x0=0, y0=0, etype=ElementType.TAG) -> Element:
    bbox = BoundingBox(x0=x0, y0=y0, x1=x0 + 10, y1=y0 + 5)
    return Element(id=Element.make_id(0, text, bbox), page_index=0, element_type=etype, text=text, bbox=bbox)


def test_bbox_center_and_area():
    bbox = BoundingBox(x0=0, y0=0, x1=10, y1=4)
    assert bbox.area() == 40
    assert bbox.center() == (5, 2)


def test_element_id_is_stable_for_same_input():
    bbox = BoundingBox(x0=1, y0=2, x1=3, y1=4)
    id1 = Element.make_id(0, "hello", bbox)
    id2 = Element.make_id(0, "hello", bbox)
    assert id1 == id2


def test_element_id_differs_for_different_position():
    bbox1 = BoundingBox(x0=1, y0=2, x1=3, y1=4)
    bbox2 = BoundingBox(x0=100, y0=200, x1=300, y1=400)
    assert Element.make_id(0, "hello", bbox1) != Element.make_id(0, "hello", bbox2)


def test_canonical_document_all_elements_and_lookup():
    e1 = make_element("A")
    e2 = make_element("B", x0=50)
    page = Page(index=0, width=100, height=100, elements=[e1, e2])
    doc = CanonicalDocument(meta=DocumentMeta(pid="p1", format="pdf_native", source_path="x.pdf"), pages=[page])

    assert len(doc.all_elements()) == 2
    assert doc.element_by_id(e1.id) is e1
    assert doc.element_by_id("does-not-exist") is None
