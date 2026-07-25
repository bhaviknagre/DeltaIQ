from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from src.canonical.model import CanonicalDocument
from src.chat.answer import AnswerResult
from src.delta.engine import DeltaItem

_KIND_MAP = {"modify": "modified", "remove": "removed", "add": "added"}
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class DeltaScore:
    true_positives: int
    false_negatives: int
    false_positives: int
    precision: float
    recall: float
    f1: float
    matched_gt_ids: list[str]
    missed_gt_ids: list[str]
    spurious_predicted_ids: list[str]


def score_delta(gt_edits: list[dict], predicted: list[DeltaItem]) -> DeltaScore:
    remaining = list(predicted)
    matched_gt_ids: list[str] = []
    missed_gt_ids: list[str] = []

    for edit in gt_edits:
        target_kind = _KIND_MAP[edit["kind"]]
        gt_texts = [t.strip().lower() for t in (edit.get("old_text"), edit.get("new_text")) if t and t.strip()]
        best = None
        for p in remaining:
            if p.change_kind.value != target_kind:
                continue
            pred_texts = [t.lower() for t in (p.before_text, p.after_text) if t]
            if any(gt in pt for gt in gt_texts for pt in pred_texts):
                best = p
                break
        if best:
            matched_gt_ids.append(edit["id"])
            remaining.remove(best)
        else:
            missed_gt_ids.append(edit["id"])

    tp = len(matched_gt_ids)
    fn = len(missed_gt_ids)
    fp = len(remaining)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return DeltaScore(
        true_positives=tp,
        false_negatives=fn,
        false_positives=fp,
        precision=round(precision, 3),
        recall=round(recall, 3),
        f1=round(f1, 3),
        matched_gt_ids=matched_gt_ids,
        missed_gt_ids=missed_gt_ids,
        spurious_predicted_ids=[p.id for p in remaining],
    )


def score_ocr_accuracy(native_doc: CanonicalDocument, ocr_doc: CanonicalDocument) -> float:
   
    def words(doc: CanonicalDocument) -> Counter:
        text = " ".join(e.text for e in doc.all_elements())
        return Counter(_WORD_RE.findall(text.lower()))

    native_words = words(native_doc)
    ocr_words = words(ocr_doc)
    total_native = sum(native_words.values())
    if total_native == 0:
        return 1.0
    matched = sum(min(count, ocr_words[word]) for word, count in native_words.items())
    return round(matched / total_native, 4)


@dataclass
class ChatQaScore:
    qa_id: str
    question: str
    correct: bool
    grounded: bool
    expect_hedge: bool
    citation_hits: int
    citation_checked: int
    answer: str


@dataclass
class ChatScore:
    per_qa: list[ChatQaScore] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return round(sum(1 for q in self.per_qa if q.correct) / len(self.per_qa), 3) if self.per_qa else 0.0

    @property
    def groundedness_rate(self) -> float:
        non_hedge = [q for q in self.per_qa if not q.expect_hedge]
        return round(sum(1 for q in non_hedge if q.grounded) / len(non_hedge), 3) if non_hedge else 0.0

    @property
    def citation_accuracy(self) -> float:
        checked = sum(q.citation_checked for q in self.per_qa)
        hits = sum(q.citation_hits for q in self.per_qa)
        return round(hits / checked, 3) if checked else 0.0


def score_chat_answer(qa: dict, result: AnswerResult) -> ChatQaScore:
    expect_hedge = qa.get("expect_hedge", False)
    answer_lower = result.answer.lower()

    if expect_hedge:
        correct = (not result.grounded) or "don't have grounded evidence" in answer_lower
        return ChatQaScore(
            qa_id=qa["id"], question=qa["question"], correct=correct, grounded=result.grounded,
            expect_hedge=True, citation_hits=0, citation_checked=0, answer=result.answer,
        )

    expected_keywords = [k.lower() for k in qa.get("expected_keywords", [])]
    keyword_hit = any(k in answer_lower for k in expected_keywords) if expected_keywords else True
    correct = keyword_hit and result.grounded

    citation_checked = 0
    citation_hits = 0
    if expected_keywords:
        chunk_by_label = {ev.chunk.citation.label(): ev.chunk.text.lower() for ev in result.retrieved}
        for label in set(result.citations_used):
            chunk_text = chunk_by_label.get(label)
            if chunk_text is None:
                continue
            citation_checked += 1
            if any(k in chunk_text for k in expected_keywords):
                citation_hits += 1

    return ChatQaScore(
        qa_id=qa["id"], question=qa["question"], correct=correct, grounded=result.grounded,
        expect_hedge=False, citation_hits=citation_hits, citation_checked=citation_checked, answer=result.answer,
    )
