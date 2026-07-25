from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from src.canonical.model import ElementType

if TYPE_CHECKING:
    from src.delta.engine import ChangeKind


class Criticality(str, Enum):
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"


def classify_criticality(change_kind: "ChangeKind", category: ElementType) -> Criticality:
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
