"""Delta engine: turns an AlignmentResult into a structured, typed, located,
confidence-scored list of DeltaItems. Purely deterministic — no LLM calls —
so the structural output is reproducible run-to-run (the assignment
explicitly asks for this; LLM non-determinism is isolated to the chat layer,
see chat/answer.py).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from src.canonical.model import BoundingBox, CanonicalDocument, Element, ElementType
from src.delta.align import MOVED_POSITION_EPS, AlignmentResult, MatchedPair, align
from src.delta.criticality import Criticality, classify_criticality
from src.observability.logging import get_logger, log_event
from src.observability.prometheus_metrics import DELTA_ITEMS_TOTAL, DELTA_RUNS_TOTAL

logger = get_logger("delta.engine")


class ChangeKind(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class DeltaItem(BaseModel):
    id: str
    change_kind: ChangeKind
    category: ElementType
    page_index: int
    bbox: BoundingBox
    before_text: str | None = None
    after_text: str | None = None
    description: str
    confidence: float
    match_method: str | None = None
    criticality: Criticality


class DeltaResult(BaseModel):
    pid_a: str
    pid_b: str
    items: list[DeltaItem]
    unchanged_count: int
    total_a_elements: int
    total_b_elements: int

    def counts_by_kind(self) -> dict[str, int]:
        out = {"added": 0, "removed": 0, "modified": 0}
        for it in self.items:
            out[it.change_kind.value] += 1
        return out

    def counts_by_category(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for it in self.items:
            out[it.category.value] = out.get(it.category.value, 0) + 1
        return out

    def counts_by_criticality(self) -> dict[str, int]:
        out = {"red": 0, "yellow": 0, "green": 0}
        for it in self.items:
            out[it.criticality.value] += 1
        return out

    def avg_confidence(self) -> float:
        if not self.items:
            return 1.0
        return round(sum(it.confidence for it in self.items) / len(self.items), 3)


def _describe_modified(a: Element, b: Element, dist: float) -> str:
    text_changed = a.text != b.text
    moved = dist > MOVED_POSITION_EPS
    if text_changed and moved:
        return f"Changed and moved: '{a.text}' -> '{b.text}' (moved {dist:.1f}pt)"
    if text_changed:
        return f"Text changed: '{a.text}' -> '{b.text}'"
    if moved:
        return f"Position changed ({dist:.1f}pt), text unchanged: '{a.text}'"
    return f"Unchanged: '{a.text}'"


def _pair_to_delta_item(pair: MatchedPair) -> DeltaItem | None:
    a, b = pair.a, pair.b
    text_changed = a.text != b.text
    moved = pair.spatial_dist > MOVED_POSITION_EPS
    if not text_changed and not moved:
        return None  # truly unchanged, not part of the delta

    confidence = round((pair.combined_score / 100.0) * min(a.confidence, b.confidence), 3)
    return DeltaItem(
        id=f"mod-{a.id}-{b.id}",
        change_kind=ChangeKind.MODIFIED,
        category=b.element_type,
        page_index=b.page_index,
        bbox=b.bbox,
        before_text=a.text,
        after_text=b.text,
        description=_describe_modified(a, b, pair.spatial_dist),
        confidence=confidence,
        match_method=pair.method,
        criticality=classify_criticality(ChangeKind.MODIFIED, b.element_type),
    )


def compute_delta(doc_a: CanonicalDocument, doc_b: CanonicalDocument) -> DeltaResult:
    alignment = align(doc_a, doc_b)

    items: list[DeltaItem] = []
    unchanged = 0

    for pair in alignment.matched:
        item = _pair_to_delta_item(pair)
        if item is None:
            unchanged += 1
        else:
            items.append(item)

    for e in alignment.removed:
        items.append(
            DeltaItem(
                id=f"rem-{e.id}",
                change_kind=ChangeKind.REMOVED,
                category=e.element_type,
                page_index=e.page_index,
                bbox=e.bbox,
                before_text=e.text,
                after_text=None,
                description=f"{e.element_type.value.title()} removed: '{e.text}'",
                confidence=round(e.confidence, 3),
                criticality=classify_criticality(ChangeKind.REMOVED, e.element_type),
            )
        )

    for e in alignment.added:
        items.append(
            DeltaItem(
                id=f"add-{e.id}",
                change_kind=ChangeKind.ADDED,
                category=e.element_type,
                page_index=e.page_index,
                bbox=e.bbox,
                before_text=None,
                after_text=e.text,
                description=f"New {e.element_type.value} added: '{e.text}'",
                confidence=round(e.confidence, 3),
                criticality=classify_criticality(ChangeKind.ADDED, e.element_type),
            )
        )

    items.sort(key=lambda it: (it.page_index, it.bbox.y0, it.bbox.x0))

    result = DeltaResult(
        pid_a=doc_a.meta.pid,
        pid_b=doc_b.meta.pid,
        items=items,
        unchanged_count=unchanged,
        total_a_elements=len(doc_a.all_elements()),
        total_b_elements=len(doc_b.all_elements()),
    )
    log_event(
        logger, 20, "delta_computed",
        pid_a=result.pid_a, pid_b=result.pid_b,
        total_changes=len(items), unchanged=unchanged, **result.counts_by_kind(),
    )

    DELTA_RUNS_TOTAL.inc()
    for criticality, count in result.counts_by_criticality().items():
        DELTA_ITEMS_TOTAL.labels(criticality=criticality).inc(count)

    return result
