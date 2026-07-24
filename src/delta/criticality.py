"""Deterministic RAG (red/yellow/green) criticality signal for a DeltaItem.

Deliberately separate from `confidence`: confidence measures how *certain*
the delta engine is that a change was correctly detected/matched; criticality
measures how much the change *matters* engineering-wise, independent of that
certainty. A confidently-detected note addition is still low criticality; a
line-size change is high criticality even if alignment only matched it at
0.7 confidence.

This is a heuristic classifier, not a physics-aware severity model — it
reacts to *what kind* of thing changed (category + add/remove/modify), not
*by how much* (e.g. it doesn't parse "3/4\" -> 1\"" and reason about the
magnitude of that increase). Named as an explicit next step, not hidden.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from src.canonical.model import ElementType

if TYPE_CHECKING:
    # Type-only: avoids a circular import with engine.py, which imports
    # Criticality/classify_criticality from *this* module at runtime.
    from src.delta.engine import ChangeKind


class Criticality(str, Enum):
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"


def classify_criticality(change_kind: "ChangeKind", category: ElementType) -> Criticality:
    """
    RED    — a dimension (line size / pressure / temp spec / tolerance) was
             modified or removed, or a tag was removed entirely. These are
             the changes that historically get missed in manual review and
             cause rework, mis-fabrication, or safety issues.
    YELLOW — a tag was modified/added, a dimension was added, or a note/text
             item was removed. Worth a reviewer's attention, not spec-level
             on its own.
    GREEN  — everything else: added/modified notes or generic text, added
             geometry/table cells, moved-only changes. Informational.

    Compares against ChangeKind's *string values* ("modified"/"removed"/
    "added") rather than importing the ChangeKind enum, since ChangeKind is
    a `str, Enum` (equality with its value works either way) and this keeps
    the module runtime-independent of engine.py — see the TYPE_CHECKING
    import above for why that matters.
    """
    kind = change_kind.value if hasattr(change_kind, "value") else change_kind

    if category == ElementType.DIMENSION and kind in ("modified", "removed"):
        return Criticality.RED
    if category == ElementType.TAG and kind == "removed":
        return Criticality.RED
    if category == ElementType.TAG and kind in ("modified", "added"):
        return Criticality.YELLOW
    if category == ElementType.DIMENSION and kind == "added":
        return Criticality.YELLOW
    if category in (ElementType.NOTE, ElementType.TEXT) and kind == "removed":
        return Criticality.YELLOW
    return Criticality.GREEN
