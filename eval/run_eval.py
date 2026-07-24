"""Runnable eval harness: `make eval` (or `python -m eval.run_eval`).

Scores the delta engine (precision/recall/F1 against hand-labeled ground
truth) on both the native-PDF and scanned-PDF demo pairs, and scores grounded
chat (correctness, groundedness rate, citation accuracy) on a labeled Q&A
set. Prints a scorecard, writes a timestamped JSON result under
eval/results/ for run-to-run comparison, and prints the diff against the
previous run if one exists — so a change can be shown to help or hurt.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from eval.metrics import ChatScore, score_chat_answer, score_delta
from src.chat.answer import answer_question
from src.chat.index import build_index
from src.delta.engine import compute_delta
from src.ingest.pid_store import load
from src.observability.tracing import new_trace

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"


def run_delta_eval() -> dict:
    gt = json.loads((HERE.parent / "data" / "samples" / "ground_truth.json").read_text())
    pairs = json.loads((HERE / "datasets" / "delta_pairs.json").read_text())["pairs"]

    out = {}
    for pair in pairs:
        with new_trace(kind="eval_delta", pair=pair["name"]) as trace:
            with trace.span("ingest_a"):
                doc_a = load(pair["pid_a"])
            with trace.span("ingest_b"):
                doc_b = load(pair["pid_b"])
            with trace.span("delta") as span:
                delta = compute_delta(doc_a, doc_b)
                span.attrs["total_changes"] = len(delta.items)

        gt_edits = gt[pair["gt_key"]]["edits"]
        score = score_delta(gt_edits, delta.items)
        out[pair["name"]] = {
            "precision": score.precision,
            "recall": score.recall,
            "f1": score.f1,
            "true_positives": score.true_positives,
            "false_negatives": score.false_negatives,
            "false_positives": score.false_positives,
            "missed_gt_ids": score.missed_gt_ids,
            "spurious_predicted_ids": score.spurious_predicted_ids,
            "predicted_total_changes": len(delta.items),
            "unchanged_count": delta.unchanged_count,
        }
    return out


def run_chat_eval() -> dict:
    qa_spec = json.loads((HERE / "datasets" / "qa_pairs.json").read_text())
    doc_a = load(qa_spec["pid_a"])
    doc_b = load(qa_spec["pid_b"])
    delta = compute_delta(doc_a, doc_b)
    index = build_index(doc_a, doc_b, delta)

    chat_score = ChatScore()
    for qa in qa_spec["qa"]:
        with new_trace(kind="eval_chat", qa_id=qa["id"]) as trace:
            result = answer_question(qa["question"], index, trace)
        chat_score.per_qa.append(score_chat_answer(qa, result))

    return {
        "accuracy": chat_score.accuracy,
        "groundedness_rate": chat_score.groundedness_rate,
        "citation_accuracy": chat_score.citation_accuracy,
        "per_qa": [
            {
                "id": q.qa_id, "question": q.question, "correct": q.correct,
                "grounded": q.grounded, "expect_hedge": q.expect_hedge,
                "citation_hits": q.citation_hits, "citation_checked": q.citation_checked,
                "answer_preview": q.answer[:160],
            }
            for q in chat_score.per_qa
        ],
    }


def print_scorecard(delta_results: dict, chat_results: dict) -> None:
    print("=" * 72)
    print("DELTA ENGINE SCORECARD")
    print("=" * 72)
    for name, r in delta_results.items():
        print(f"  [{name}] precision={r['precision']:.2f} recall={r['recall']:.2f} f1={r['f1']:.2f}  "
              f"(TP={r['true_positives']} FN={r['false_negatives']} FP={r['false_positives']})")
        if r["missed_gt_ids"]:
            print(f"    MISSED ground truth: {r['missed_gt_ids']}")
        if r["spurious_predicted_ids"]:
            print(f"    SPURIOUS predictions (false positives): {r['spurious_predicted_ids']}")

    print()
    print("=" * 72)
    print("CHAT SCORECARD")
    print("=" * 72)
    print(f"  accuracy={chat_results['accuracy']:.2f}  "
          f"groundedness_rate={chat_results['groundedness_rate']:.2f}  "
          f"citation_accuracy={chat_results['citation_accuracy']:.2f}")
    print()
    print("  Failure table (incorrect or ungrounded answers):")
    any_failure = False
    for qa in chat_results["per_qa"]:
        if not qa["correct"]:
            any_failure = True
            print(f"    [{qa['id']}] FAIL — \"{qa['question']}\"")
            print(f"        answer: {qa['answer_preview']}...")
    if not any_failure:
        print("    (none)")
    print("=" * 72)


def save_and_diff(delta_results: dict, chat_results: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    prior_files = sorted(RESULTS_DIR.glob("*.json"))
    prior = json.loads(prior_files[-1].read_text()) if prior_files else None

    payload = {"timestamp": time.time(), "delta": delta_results, "chat": chat_results}
    out_path = RESULTS_DIR / f"{int(time.time())}.json"
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\nSaved scorecard -> {out_path}")

    if prior:
        print("\nDiff vs previous run:")
        for name in delta_results:
            prev_f1 = prior.get("delta", {}).get(name, {}).get("f1")
            cur_f1 = delta_results[name]["f1"]
            if prev_f1 is not None:
                delta_sign = "+" if cur_f1 >= prev_f1 else ""
                print(f"  delta[{name}].f1: {prev_f1:.2f} -> {cur_f1:.2f} ({delta_sign}{cur_f1 - prev_f1:.2f})")
        prev_acc = prior.get("chat", {}).get("accuracy")
        if prev_acc is not None:
            cur_acc = chat_results["accuracy"]
            delta_sign = "+" if cur_acc >= prev_acc else ""
            print(f"  chat.accuracy: {prev_acc:.2f} -> {cur_acc:.2f} ({delta_sign}{cur_acc - prev_acc:.2f})")


if __name__ == "__main__":
    delta_results = run_delta_eval()
    chat_results = run_chat_eval()
    print_scorecard(delta_results, chat_results)
    save_and_diff(delta_results, chat_results)
