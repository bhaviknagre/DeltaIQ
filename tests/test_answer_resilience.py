from src.canonical.model import BoundingBox, CanonicalDocument, DocumentMeta, Element, ElementType, Page
from src.chat.answer import answer_question
from src.chat.index import build_index
from src.chat.llm import LLMProvider
from src.delta.engine import compute_delta
from src.observability.tracing import new_trace


class ExplodingProvider(LLMProvider):
    name = "exploding"

    def complete(self, system: str, user: str):
        raise RuntimeError("simulated provider outage")


def doc_with(pid: str, elements: list[Element]) -> CanonicalDocument:
    page = Page(index=0, width=1000, height=1000, elements=elements)
    return CanonicalDocument(meta=DocumentMeta(pid=pid, format="pdf_native", source_path=f"{pid}.pdf"), pages=[page])


def el(text, x0, y0, etype=ElementType.TAG):
    bbox = BoundingBox(x0=x0, y0=y0, x1=x0 + 20, y1=y0 + 8)
    return Element(id=Element.make_id(0, text, bbox), page_index=0, element_type=etype, text=text, bbox=bbox)


def test_provider_failure_degrades_instead_of_raising():
    doc_a = doc_with("a", [el("26-KA-902", 10, 10)])
    doc_b = doc_with("b", [el("26-KA-902B", 10, 10)])
    delta = compute_delta(doc_a, doc_b)
    index = build_index(doc_a, doc_b, delta)

    with new_trace(kind="test") as trace:
        result = answer_question("What changed?", index, trace, provider=ExplodingProvider())

    assert result.grounded is False
    assert "provider call failed" in result.answer.lower()
    assert trace.spans[-1].status == "error" or any(s.status == "error" for s in trace.spans)
