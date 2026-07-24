"""Runnable eval harness: `make eval` (or `python -m eval.run_eval`).

Scores the delta engine (precision/recall/F1 against hand-labeled ground
truth) on both the native-PDF and scanned-PDF demo pairs, scores grounded
chat (correctness, groundedness rate, citation accuracy) on a labeled Q&A
set, and computes real OCR accuracy, latency, token usage, and estimated
cost from the actual requests just run — not placeholder numbers. Prints a
scorecard with a PASS/FAIL banner, writes a timestamped JSON result under
eval/results/ for run-to-run comparison, and prints the diff against the
previous run if one exists — so a change can be shown to help or hurt.

PASS thresholds (PASS_THRESHOLDS below) are a judgment call, not handed down
by spec — chosen to reflect "good enough to trust, not perfect": delta F1 and
chat accuracy/groundedness at 0.75 allow for the honest, known OCR-precision
and BM25-paraphrase gaps documented in the README without masking a real
regression below that floor.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from eval.metrics import ChatScore, score_chat_answer, score_delta, score_ocr_accuracy
from src.chat.answer import answer_question
from src.chat.vector_index import build_retriever
from src.delta.engine import compute_delta
from src.ingest.pid_store import load
from src.observability.tracing import new_trace

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"

PASS_THRESHOLDS = {"delta_f1": 0.75, "chat_accuracy": 0.75, "groundedness_rate": 0.75}


def run_delta_eval() -> dict:
    gt = json.loads((HERE.parent / "data" / "samples" / "ground_truth.json").read_text())
    pairs = json.loads((HERE / "datasets" / "delta_pairs.json").read_text())["pairs"]

    docs_by_pair = {}
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

        docs_by_pair[pair["name"]] = (doc_a, doc_b)
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
            "avg_confidence": delta.avg_confidence(),
            "criticality_counts": delta.counts_by_criticality(),
            "ocr_accuracy": None,
        }

    # OCR accuracy: compare the scanned pair's OCR output against the native
    # pair's text-layer ground truth for the same underlying document (see
    # score_ocr_accuracy docstring). Only meaningful if both pairs are present.
    if "native" in docs_by_pair and "scanned" in docs_by_pair:
        native_a, native_b = docs_by_pair["native"]
        scanned_a, scanned_b = docs_by_pair["scanned"]
        acc_a = score_ocr_accuracy(native_a, scanned_a)
        acc_b = score_ocr_accuracy(native_b, scanned_b)
        out["scanned"]["ocr_accuracy"] = round((acc_a + acc_b) / 2, 4)

    return out


def run_chat_eval() -> dict:
    qa_spec = json.loads((HERE / "datasets" / "qa_pairs.json").read_text())
    doc_a = load(qa_spec["pid_a"])
    doc_b = load(qa_spec["pid_b"])
    delta = compute_delta(doc_a, doc_b)
    index = build_retriever(doc_a, doc_b, delta)

    chat_score = ChatScore()
    latencies_ms: list[float] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    model_used = None

    for qa in qa_spec["qa"]:
        with new_trace(kind="eval_chat", qa_id=qa["id"]) as trace:
            result = answer_question(qa["question"], index, trace)
        latencies_ms.append((trace.ended_at - trace.started_at) * 1000)
        total_input_tokens += result.input_tokens
        total_output_tokens += result.output_tokens
        total_cost += result.cost_usd
        if result.model:  # hedged (no-retrieval) answers carry no model — don't let them blank this out
            model_used = result.model
        chat_score.per_qa.append(score_chat_answer(qa, result))

    return {
        "accuracy": chat_score.accuracy,
        "groundedness_rate": chat_score.groundedness_rate,
        "citation_accuracy": chat_score.citation_accuracy,
        "model": model_used,
        "avg_latency_sec": round(sum(latencies_ms) / len(latencies_ms) / 1000, 3) if latencies_ms else 0.0,
        "total_tokens": total_input_tokens + total_output_tokens,
        "total_cost_usd": round(total_cost, 6),
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


def compute_pass_fail(delta_results: dict, chat_results: dict) -> tuple[bool, list[str]]:
    reasons = []
    native_f1 = delta_results.get("native", {}).get("f1", 0.0)
    if native_f1 < PASS_THRESHOLDS["delta_f1"]:
        reasons.append(f"native delta F1 {native_f1:.2f} < {PASS_THRESHOLDS['delta_f1']}")
    if chat_results["accuracy"] < PASS_THRESHOLDS["chat_accuracy"]:
        reasons.append(f"chat accuracy {chat_results['accuracy']:.2f} < {PASS_THRESHOLDS['chat_accuracy']}")
    if chat_results["groundedness_rate"] < PASS_THRESHOLDS["groundedness_rate"]:
        reasons.append(f"groundedness {chat_results['groundedness_rate']:.2f} < {PASS_THRESHOLDS['groundedness_rate']}")
    return (len(reasons) == 0, reasons)


def print_scorecard(delta_results: dict, chat_results: dict) -> None:
    passed, fail_reasons = compute_pass_fail(delta_results, chat_results)

    print("=" * 60)
    print("Evaluation Results")
    print("=" * 60)
    print()
    for name, r in delta_results.items():
        print(f"Document Pair    : {name}")
        print(f"Precision        : {r['precision']:.2f}")
        print(f"Recall           : {r['recall']:.2f}")
        print(f"F1 Score         : {r['f1']:.2f}")
        print(f"Avg Confidence   : {r['avg_confidence']:.2f}")
        crit = r["criticality_counts"]
        print(f"Criticality      : \U0001F534 {crit['red']}  \U0001F7E1 {crit['yellow']}  \U0001F7E2 {crit['green']}")
        if r["ocr_accuracy"] is not None:
            print(f"OCR Accuracy     : {r['ocr_accuracy'] * 100:.1f}%")
        if r["missed_gt_ids"]:
            print(f"  MISSED ground truth      : {r['missed_gt_ids']}")
        if r["spurious_predicted_ids"]:
            print(f"  SPURIOUS predictions (FP): {r['spurious_predicted_ids']}")
        print()

    print(f"Chat Correctness : {chat_results['accuracy']:.2f}")
    print(f"Groundedness     : {chat_results['groundedness_rate']:.2f}")
    print(f"Citation Accuracy: {chat_results['citation_accuracy']:.2f}")
    print(f"Model            : {chat_results['model']}")
    print(f"Latency          : {chat_results['avg_latency_sec']:.2f} sec/question (avg)")
    print(f"Tokens Used      : {chat_results['total_tokens']:,}")
    print(f"Estimated Cost   : ${chat_results['total_cost_usd']:.4f}")
    print()

    any_failure = False
    print("Failure table (incorrect or ungrounded chat answers):")
    for qa in chat_results["per_qa"]:
        if not qa["correct"]:
            any_failure = True
            print(f"  [{qa['id']}] FAIL — \"{qa['question']}\"")
            print(f"      answer: {qa['answer_preview']}...")
    if not any_failure:
        print("  (none)")

    print()
    print("=" * 60)
    if passed:
        print("PASS")
    else:
        print("FAIL")
        for reason in fail_reasons:
            print(f"  - {reason}")
    print("=" * 60)


def save_and_diff(delta_results: dict, chat_results: dict, passed: bool) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # latest_metrics.json (the flat DVC-metrics summary written below) isn't
    # a timestamped scorecard — excluded so it's never mistaken for "the
    # previous run" when computing the diff.
    prior_files = sorted(f for f in RESULTS_DIR.glob("*.json") if f.name != "latest_metrics.json")
    prior = json.loads(prior_files[-1].read_text()) if prior_files else None

    payload = {"timestamp": time.time(), "delta": delta_results, "chat": chat_results, "passed": passed}
    out_path = RESULTS_DIR / f"{int(time.time())}.json"
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\nSaved scorecard -> {out_path}")

    # Flat, stable-path summary for `dvc metrics show`/`dvc metrics diff` —
    # DVC diffs a metrics file against its previous git-committed content, so
    # it needs one fixed path, unlike the timestamped run-history files above
    # (which back the web UI's trend chart and shouldn't be flattened away).
    metrics_summary = {
        "delta_native_f1": delta_results.get("native", {}).get("f1"),
        "delta_native_precision": delta_results.get("native", {}).get("precision"),
        "delta_native_recall": delta_results.get("native", {}).get("recall"),
        "delta_scanned_f1": delta_results.get("scanned", {}).get("f1"),
        "delta_scanned_ocr_accuracy": delta_results.get("scanned", {}).get("ocr_accuracy"),
        "chat_accuracy": chat_results["accuracy"],
        "chat_groundedness_rate": chat_results["groundedness_rate"],
        "chat_citation_accuracy": chat_results["citation_accuracy"],
        "passed": passed,
    }
    (RESULTS_DIR / "latest_metrics.json").write_text(json.dumps(metrics_summary, indent=2))

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
    passed, _ = compute_pass_fail(delta_results, chat_results)
    save_and_diff(delta_results, chat_results, passed)
