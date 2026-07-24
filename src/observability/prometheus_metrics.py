"""Prometheus metrics — a second, complementary observability surface
alongside the existing homegrown per-request trace files (tracing.py) and
JSON logs (logging.py). Those two answer "what happened on this specific
request"; Prometheus answers "how is the system behaving in aggregate, over
time" — the question the trace-file-reduction in metrics.py can only answer
retroactively by scanning files after the fact, not continuously.

Named `deltachat_*` throughout. Scraped via GET /metrics on the FastAPI app
(src/webapp/app.py, mounted with prometheus_client's ASGI app) — see
prometheus/prometheus.yml for the scrape config and the "grafana/" directory for a
starter dashboard against these exact metric names.

Wired into src/observability/tracing.py generically (every span's duration
and error status are recorded here automatically, for every request kind,
with no per-call-site instrumentation needed) plus two targeted spots that
need data span attrs don't generically expose: LLM token/cost counters in
chat/answer.py, and delta criticality counts in delta/engine.py.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

REQUESTS_TOTAL = Counter("deltachat_requests_total", "Total traced requests", ["kind"])
REQUEST_ERRORS_TOTAL = Counter("deltachat_request_errors_total", "Traced requests with at least one span error", ["kind"])

SPAN_DURATION_SECONDS = Histogram(
    "deltachat_span_duration_seconds", "Duration of individual trace spans", ["span_name"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
SPAN_ERRORS_TOTAL = Counter("deltachat_span_errors_total", "Span-level errors", ["span_name"])

LLM_TOKENS_TOTAL = Counter("deltachat_llm_tokens_total", "LLM tokens consumed", ["provider", "direction"])
LLM_COST_USD_TOTAL = Counter("deltachat_llm_cost_usd_total", "Estimated LLM cost in USD", ["provider"])
LLM_CALLS_TOTAL = Counter("deltachat_llm_calls_total", "LLM calls made", ["provider", "grounded"])

DELTA_ITEMS_TOTAL = Counter("deltachat_delta_items_total", "Delta items produced, by criticality", ["criticality"])
DELTA_RUNS_TOTAL = Counter("deltachat_delta_runs_total", "compute_delta() invocations")
