from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from src.canonical.model import CanonicalDocument, Element
from src.config import settings

EXACT_POSITION_EPS = 1.5  
MOVED_POSITION_EPS = 3.0  


@dataclass
class MatchedPair:
    a: Element
    b: Element
    text_sim: float 
    spatial_dist: float  
    method: str 

    @property
    def combined_score(self) -> float:
        spatial_score = max(0.0, 100.0 - (self.spatial_dist / settings.spatial_match_max_dist) * 100.0)
        return 0.65 * self.text_sim + 0.35 * spatial_score


@dataclass
class AlignmentResult:
    matched: list[MatchedPair] = field(default_factory=list)
    removed: list[Element] = field(default_factory=list)  
    added: list[Element] = field(default_factory=list)  


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

        for a_id, a in list(unmatched_a.items()):
            for b_id, b in list(unmatched_b.items()):
                if a.text == b.text and a.element_type == b.element_type and _center_dist(a, b) <= EXACT_POSITION_EPS:
                    result.matched.append(MatchedPair(a=a, b=b, text_sim=100.0, spatial_dist=0.0, method="exact"))
                    del unmatched_a[a_id]
                    del unmatched_b[b_id]
                    break

        candidates: list[MatchedPair] = []
        for a in unmatched_a.values():
            for b in unmatched_b.values():
                dist = _center_dist(a, b)
                if dist > settings.spatial_match_max_dist * 3:
                    continue  
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
