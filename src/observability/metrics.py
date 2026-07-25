from __future__ import annotations

import json
from pathlib import Path

from src.config import settings


def load_traces() -> list[dict]:
    traces = []
    for f in sorted(Path(settings.traces_dir).glob("*.json")):
        try:
            traces.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            continue
    return traces


def summarize(traces: list[dict]) -> dict:
    if not traces:
        return {"count": 0}

    by_kind: dict[str, list[dict]] = {}
    for t in traces:
        by_kind.setdefault(t["kind"], []).append(t)

    summary = {"count": len(traces), "errors": sum(1 for t in traces if t.get("has_error")), "by_kind": {}}

    for kind, ts in by_kind.items():
        durations = [t["duration_ms"] for t in ts]
        tokens_in = sum(s["attrs"].get("input_tokens", 0) for t in ts for s in t["spans"] if s["name"] == "llm_call")
        tokens_out = sum(s["attrs"].get("output_tokens", 0) for t in ts for s in t["spans"] if s["name"] == "llm_call")
        cost = sum(s["attrs"].get("cost_usd", 0.0) for t in ts for s in t["spans"] if s["name"] == "llm_call")
        retrieval_hits = [
            s["attrs"].get("num_hits") for t in ts for s in t["spans"] if s["name"] == "retrieve" and "num_hits" in s["attrs"]
        ]
        delta_counts = [s["attrs"].get("total_changes") for t in ts for s in t["spans"] if s["name"] == "delta" and "total_changes" in s["attrs"]]
        summary["by_kind"][kind] = {
            "requests": len(ts),
            "errors": sum(1 for t in ts if t.get("has_error")),
            "avg_latency_ms": round(sum(durations) / len(durations), 1),
            "p95_latency_ms": round(sorted(durations)[int(0.95 * (len(durations) - 1))], 1) if durations else 0,
            "total_input_tokens": tokens_in,
            "total_output_tokens": tokens_out,
            "estimated_cost_usd": round(cost, 6),
            "avg_retrieval_hits": round(sum(retrieval_hits) / len(retrieval_hits), 2) if retrieval_hits else None,
            "avg_delta_count": round(sum(delta_counts) / len(delta_counts), 2) if delta_counts else None,
        }
    return summary


def print_summary() -> None:
    traces = load_traces()
    summary = summarize(traces)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    print_summary()
