from __future__ import annotations

import re

from src.canonical.model import ElementType

_TAG_RE = re.compile(r"^\d{1,3}-?[A-Z]{2,6}-?\d{3,6}[A-Z]?$")

_DIMENSION_RE = re.compile(
    r'(\d+/\d+")|(\d+")|(\d+\s?["\']x\d)|(^EL\s?[+-]\s?[\d.]+\s?M$)|(^\d+\s?(MM|IN|M)$)',
    re.IGNORECASE,
)

_NOTE_RE = re.compile(r"^(NOTE\s+\d+\b|\d{1,2}\.(?=\s|$))", re.IGNORECASE)


def classify_text(text: str) -> ElementType:
    t = text.strip()
    if not t:
        return ElementType.TEXT
    if _NOTE_RE.match(t):
        return ElementType.NOTE
    if _DIMENSION_RE.search(t):
        return ElementType.DIMENSION
    if _TAG_RE.match(t) and any(c.isdigit() for c in t):
        return ElementType.TAG
    return ElementType.TEXT
