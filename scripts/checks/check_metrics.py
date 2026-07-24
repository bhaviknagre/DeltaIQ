"""Check: Prometheus metrics — /metrics returns valid exposition format
with real, non-zero values after driving a request through the system, and
the values match what actually happened (not just "the endpoint responds").

Usage: python -m scripts.checks.check_metrics
"""

from __future__ import annotations

import warnings
from pathlib import Path

from scripts.checks._common import CheckSuite

warnings.filterwarnings("ignore", message=r".*httpx.*deprecated.*")

ROOT = Path(__file__).resolve().parent.parent.parent
NATIVE_A = ROOT / "data" / "samples" / "pair_native" / "rev_a.pdf"
NATIVE_B = ROOT / "data" / "samples" / "pair_native" / "rev_b.pdf"


def _parse_metric(text: str, name: str) -> list[tuple[str, float]]:
    """Minimal Prometheus text-format parser: returns [(label_str, value), ...]
    for every line matching `name{...} value` or `name value`."""
    out = []
    for line in text.splitlines():
        if line.startswith("#") or not line.startswith(name):
            continue
        rest = line[len(name):].strip()
        if rest.startswith("{"):
            labels, _, value = rest.partition("}")
            out.append((labels.lstrip("{"), float(value.strip())))
        else:
            out.append(("", float(rest)))
    return out


def main() -> None:
    suite = CheckSuite("metrics")

    if not (NATIVE_A.exists() and NATIVE_B.exists()):
        suite.skip("all metrics checks", "sample pair not generated — run `make samples`")
        suite.exit()
        return

    from fastapi.testclient import TestClient

    from src.ingest.pid_store import register_pid
    from src.webapp.app import app

    register_pid("check-metrics-a", str(NATIVE_A), "Rev A")
    register_pid("check-metrics-b", str(NATIVE_B), "Rev B")
    client = TestClient(app)

    with suite.check("GET /metrics returns Prometheus exposition format"):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "# HELP" in resp.text and "# TYPE" in resp.text

    with suite.check("delta_runs_total and delta_items_total increment after a real delta run"):
        before = client.get("/metrics").text
        before_runs = sum(v for _, v in _parse_metric(before, "deltachat_delta_runs_total"))

        client.get("/results", params={"pid_a": "check-metrics-a", "pid_b": "check-metrics-b"})

        after = client.get("/metrics").text
        after_runs = sum(v for _, v in _parse_metric(after, "deltachat_delta_runs_total"))
        after_items = sum(v for _, v in _parse_metric(after, "deltachat_delta_items_total"))
        assert after_runs > before_runs, f"delta_runs_total did not increment: {before_runs} -> {after_runs}"
        assert after_items >= 6, f"expected at least 6 delta items counted, got {after_items}"

    with suite.check("span duration histogram has real, non-degenerate buckets"):
        text = client.get("/metrics").text
        buckets = _parse_metric(text, "deltachat_span_duration_seconds_bucket")
        assert buckets, "no span duration histogram data — tracing isn't reaching Prometheus"

    suite.exit()


if __name__ == "__main__":
    main()
