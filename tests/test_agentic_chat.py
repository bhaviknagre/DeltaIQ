from src.canonical.model import BoundingBox, CanonicalDocument, DocumentMeta, Element, ElementType, Page
from src.chat.agentic import answer_question_agentic
from src.chat.index import build_index
from src.chat.llm import LLMProvider, LLMResponse, MockProvider
from src.config import settings
from src.delta.engine import compute_delta
from src.observability.tracing import new_trace


def doc_with(pid: str, elements: list[Element]) -> CanonicalDocument:
    page = Page(index=0, width=1000, height=1000, elements=elements)
    return CanonicalDocument(meta=DocumentMeta(pid=pid, format="pdf_native", source_path=f"{pid}.pdf"), pages=[page])


def el(text, x0, y0, etype=ElementType.TAG):
    bbox = BoundingBox(x0=x0, y0=y0, x1=x0 + 20, y1=y0 + 8)
    return Element(id=Element.make_id(0, text, bbox), page_index=0, element_type=etype, text=text, bbox=bbox)


def _build_index():
    doc_a = doc_with("a", [el("26-KA-902", 10, 10)])
    doc_b = doc_with("b", [el("26-KA-902B", 10, 10)])
    delta = compute_delta(doc_a, doc_b)
    return build_index(doc_a, doc_b, delta)


class HallucinatingProvider(LLMProvider):

    name = "hallucinating"

    def __init__(self):
        self.calls = 0

    def complete(self, system: str, user: str) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            text="The size changed [pid_a:nonexistent@p99].",
            model="fake", input_tokens=1, output_tokens=1, cost_usd=0.0,
        )


class ExplodingProvider(LLMProvider):
    name = "exploding"

    def complete(self, system: str, user: str):
        raise RuntimeError("simulated provider outage")


def test_happy_path_verifies_on_first_attempt():
    index = _build_index()
    with new_trace(kind="test") as trace:
        result = answer_question_agentic("What changed about 26-KA-902?", index, trace, provider=MockProvider())

    assert result.grounded is True
    assert result.verified is True
    assert result.attempts == 1
    assert result.verification_notes == []


def test_hallucinated_citation_triggers_retries_then_gives_up():
    index = _build_index()
    provider = HallucinatingProvider()
    with new_trace(kind="test") as trace:
        result = answer_question_agentic("What changed about 26-KA-902?", index, trace, provider=provider)
    assert provider.calls == settings.agentic_max_retries + 1
    assert result.attempts == settings.agentic_max_retries + 1
    assert result.verified is False
    assert "[pid_a:nonexistent@p99]" in result.verification_notes

    retrieve_spans = [s for s in trace.spans if s.name == "agentic_retrieve"]
    verify_spans = [s for s in trace.spans if s.name == "agentic_verify"]
    assert len(retrieve_spans) == settings.agentic_max_retries + 1
    assert len(verify_spans) == settings.agentic_max_retries + 1
    assert [s.attrs["widened"] for s in retrieve_spans] == [False] + [True] * settings.agentic_max_retries


def test_provider_failure_degrades_instead_of_raising():
    index = _build_index()
    with new_trace(kind="test") as trace:
        result = answer_question_agentic("What changed?", index, trace, provider=ExplodingProvider())

    assert result.grounded is False
    assert "provider call failed" in result.answer.lower()
    assert any(s.status == "error" or s.attrs.get("llm_error") for s in trace.spans)


def test_no_grounding_evidence_hedges_without_calling_llm():
    index = _build_index()

    class UncalledProvider(LLMProvider):
        name = "uncalled"

        def complete(self, system: str, user: str):
            raise AssertionError("LLM should not be called when retrieval finds nothing")

    with new_trace(kind="test") as trace:
        result = answer_question_agentic(
            "completely unrelated off-topic question xyzzy", index, trace, provider=UncalledProvider()
        )

    assert result.grounded is False
    assert result.verified is True
    assert result.attempts == 1
