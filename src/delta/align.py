"""Content alignment between two canonical documents.

This is the hard part of "delta," not the diffing. Elements have no stable
cross-revision ID (a re-exported PDF/DXF assigns nothing like a database
primary key to a text run), so alignment has to infer correspondence from
text similarity and spatial proximity, restricted to the same page/sheet.

Strategy, in order of confidence:
  1. Exact match: identical text at (near-)identical position on the same
     page -> aligned as "unchanged", full confidence, no further scoring.
  2. Best-score greedy match on remaining elements: for each page, score
     every remaining (a, b) candidate pair by a blend of text similarity
     (rapidfuzz) and spatial proximity (bbox-center distance), then greedily
     take the highest-scoring pairs first, one-to-one, until nothing left
     clears FUZZY_MATCH_THRESHOLD *or* is close enough spatially even with
     weak text similarity (covers "text fully replaced at the same
     location," e.g. a tag renumbered in place).
  3. Anything left unmatched in A is a removal candidate; unmatched in B is
     an addition candidate.

Greedy (not optimal bipartite/Hungarian) matching is a deliberate trade-off:
P&ID sheets have hundreds of small text elements, so an O(n^2 log n) greedy
pass over precomputed pairwise scores is fast and, in practice, converges to
the same alignment the Hungarian algorithm would for well-separated content
— documented here rather than silently assumed correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from src.canonical.model import CanonicalDocument, Element
from src.config import settings

EXACT_POSITION_EPS = 1.5  # points; bbox-center distance below this + identical text => "unchanged"
MOVED_POSITION_EPS = 3.0  # points; matched pair with identical text but center beyond this => "moved"


@dataclass
class MatchedPair:
    a: Element
    b: Element
    text_sim: float  # 0-100
    spatial_dist: float  # points, +inf if different pages
    method: str  # "exact" | "fuzzy_text" | "spatial_only"

    @property
    def combined_score(self) -> float:
        spatial_score = max(0.0, 100.0 - (self.spatial_dist / settings.spatial_match_max_dist) * 100.0)
        return 0.65 * self.text_sim + 0.35 * spatial_score


@dataclass
class AlignmentResult:
    matched: list[MatchedPair] = field(default_factory=list)
    removed: list[Element] = field(default_factory=list)  # unmatched in A
    added: list[Element] = field(default_factory=list)  # unmatched in B


def _center_dist(e1: Element, e2: Element) -> float:
    c1, c2 = e1.bbox.center(), e2.bbox.center()
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2) ** 0.5


def align(doc_a: CanonicalDocument, doc_b: CanonicalDocument) -> AlignmentResult:
    result = AlignmentResult()

    pages = sorted(set(e.page_index for e in doc_a.all_elements()) | set(e.page_index for e in doc_b.all_elements()))

    for page_index in pages:
        a_elems = [e for e in doc_a.all_elements() if e.page_index == page_index]
        b_elems = [e for e in doc_b.all_elements() if e.page_index == page_index]

        unmatched_a: dict[str, Element] = {e.id: e for e in a_elems}
        unmatched_b: dict[str, Element] = {e.id: e for e in b_elems}

        # Pass 1: exact match (same text, same type, near-identical position)
        for a_id, a in list(unmatched_a.items()):
            for b_id, b in list(unmatched_b.items()):
                if a.text == b.text and a.element_type == b.element_type and _center_dist(a, b) <= EXACT_POSITION_EPS:
                    result.matched.append(MatchedPair(a=a, b=b, text_sim=100.0, spatial_dist=0.0, method="exact"))
                    del unmatched_a[a_id]
                    del unmatched_b[b_id]
                    break

        # Pass 2: greedy best-score match on what's left
        candidates: list[MatchedPair] = []
        for a in unmatched_a.values():
            for b in unmatched_b.values():
                dist = _center_dist(a, b)
                if dist > settings.spatial_match_max_dist * 3:
                    continue  # too far apart to plausibly be the same element
                sim = fuzz.ratio(a.text, b.text)
                method = "fuzzy_text" if sim >= settings.fuzzy_match_threshold else "spatial_only"
                candidates.append(MatchedPair(a=a, b=b, text_sim=sim, spatial_dist=dist, method=method))

        candidates.sort(key=lambda c: c.combined_score, reverse=True)
        used_a: set[str] = set()
        used_b: set[str] = set()
        for c in candidates:
            if c.a.id in used_a or c.b.id in used_b:
                continue
            qualifies = c.text_sim >= settings.fuzzy_match_threshold or (
                c.spatial_dist <= settings.spatial_match_max_dist * 0.5 and c.text_sim >= 30
            )
            if not qualifies:
                continue
            result.matched.append(c)
            used_a.add(c.a.id)
            used_b.add(c.b.id)

        for a_id, a in unmatched_a.items():
            if a_id not in used_a:
                result.removed.append(a)
        for b_id, b in unmatched_b.items():
            if b_id not in used_b:
                result.added.append(b)

    return result
