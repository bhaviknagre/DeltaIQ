"""Heuristic classification of a raw text line into a domain ElementType.

Deterministic regex, not an LLM call: classification of "is this a tag or a
dimension" needs to be reproducible and free, and the patterns in P&ID /
engineering-drawing text are regular enough (tag codes, pipe specs, numbered
notes) that regex does the job. This is the kind of decision the assignment
asks us to be explicit and justify: LLM effort is spent on chat answers and
judgment calls, not on stable, rule-following text classification.
"""

from __future__ import annotations

import re

from src.canonical.model import ElementType

# Equipment / instrument tags: "26-KA-902", "26-PDI-9054", "43BL9054", "26-CX-9021"
_TAG_RE = re.compile(r"^\d{1,3}-?[A-Z]{2,6}-?\d{3,6}[A-Z]?$")

# Piping line specs / dimensions: `3/4"-DC-26-9026-FC11S-00`, `3"x6"`, `EL + 47.4 M`
_DIMENSION_RE = re.compile(
    r'(\d+/\d+")|(\d+")|(\d+\s?["\']x\d)|(^EL\s?[+-]\s?[\d.]+\s?M$)|(^\d+\s?(MM|IN|M)$)',
    re.IGNORECASE,
)

# Numbered notes: "1.", "NOTE 26", "NOTE 16"
# NB: no trailing \b after the literal "." — "." and a following space are
# both non-word characters, so \b would never match there (word boundaries
# only exist between a word char and a non-word char).
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
