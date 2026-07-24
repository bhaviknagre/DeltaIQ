"""Check: end-to-end grounded chat — a real answer_question() call through
whichever LLM provider is currently configured (mock if no key is set; real
if one is). Reports which provider ran, since that materially affects answer
quality but not what this check asserts (grounding/citation/refusal behavior
should hold regardless of provider).

Usage: python -m scripts.checks.check_chat
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent
NATIVE_A = ROOT / "data" / "samples" / "pair_native" / "rev_a.pdf"
NATIVE_B = ROOT / "data" / "samples" / "pair_native" / "rev_b.pdf"


def main() -> None:
    suite = CheckSuite("chat")

    if not (NATIVE_A.exists() and NATIVE_B.exists()):
        suite.skip("all chat checks", "sample pair not generated — run `make samples`")
        suite.exit()
        return

    from src.chat.answer import answer_question
    from src.chat.index import build_index
    from src.chat.llm import get_provider
    from src.delta.engine import compute_delta
    from src.ingest.pid_store import load, register_pid
    from src.observability.tracing import new_trace

    register_pid("check-chat-a", str(NATIVE_A), "Rev A")
    register_pid("check-chat-b", str(NATIVE_B), "Rev B")
    doc_a = load("check-chat-a")
    doc_b = load("check-chat-b")
    delta = compute_delta(doc_a, doc_b)
    index = build_index(doc_a, doc_b, delta)

    provider = get_provider()
    print(f"  using LLM provider: {provider.name}")

    with suite.check("grounded answer + citation for an answerable question"):
        with new_trace(kind="check_chat") as trace:
            result = answer_question("What changed with tag 26-KA-902?", index, trace, provider=provider)
        assert result.grounded, f"expected grounded=True, answer was: {result.answer!r}"
        assert len(result.citations_used) > 0, "no citations in a grounded answer"

    with suite.check("refuses/hedges on an adversarial, ungrounded question"):
        with new_trace(kind="check_chat") as trace:
            result = answer_question("What color is the sky drawn in this P&ID?", index, trace, provider=provider)
        assert not result.grounded, f"expected a hedge, got grounded answer: {result.answer!r}"

    with suite.check("a failed provider call degrades instead of crashing"):
        from src.chat.llm import LLMProvider

        class BoomProvider(LLMProvider):
            name = "boom"

            def complete(self, system, user):
                raise RuntimeError("simulated outage")

        with new_trace(kind="check_chat") as trace:
            result = answer_question("What changed with tag 26-KA-902?", index, trace, provider=BoomProvider())
        assert not result.grounded
        assert "provider call failed" in result.answer.lower()

    suite.exit()


if __name__ == "__main__":
    main()
