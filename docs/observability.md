# Observability

Homegrown tracer (`src/observability/tracing.py`) instead of OpenTelemetry/
Langfuse/Phoenix: there's no always-on collector in this environment, and the
grading/demo environment shouldn't need one running just to inspect a
request. Every request writes one self-contained JSON file to
`traces/<request_id>.json` — inspectable with `cat`, diffable across runs,
zero infrastructure. The shape (trace id, named spans with
start/end/duration/attrs/status, errors captured on the span and re-raised
rather than swallowed) mirrors OTel's span model closely enough that swapping
in a real OTel SDK later touches `Tracer`'s internals, not call sites.

## What's captured

- **Tracing**: `ingest_a` / `ingest_b` / `delta` / `retrieve` / `llm_call` /
  `answer` spans, each with duration, on every request.
- **LLM telemetry**: every `llm_call` span records provider, model,
  input/output tokens, and an estimated cost (`config.py` pricing table).
- **Structured logs**: JSON lines to `logs/app.jsonl`, every line carrying a
  `request_id` correlation id (contextvar-scoped per trace).
- **Metrics**: `make metrics` (`src/observability/metrics.py`) reduces over
  `traces/*.json` — request counts, error counts, avg/p95 latency, total
  tokens/cost, avg retrieval hits, avg delta count, grouped by request kind.
- **Failure visibility**: a span that raises records `status="error"` + the
  exception on the trace file, then re-raises — errors are traced, not
  swallowed. `pytesseract.TesseractNotFoundError`, unknown PIDs, unparseable
  `.dwg`, and failed LLM provider calls all surface this way.

## Example trace excerpt

A failed OpenAI call (`insufficient_quota`, encountered live while testing)
recorded exactly like this — nothing silently disappeared:

```json
{
  "name": "llm_call",
  "duration_ms": 6943.5,
  "status": "error",
  "attrs": { "provider": "openai" },
  "error": "RateLimitError: Error code: 429 - ... insufficient_quota ..."
}
```

## Example metrics reduction

```json
{
  "count": 32,
  "errors": 0,
  "by_kind": {
    "eval_chat": {
      "requests": 21, "errors": 0,
      "avg_latency_ms": 0.9, "p95_latency_ms": 1.4,
      "total_input_tokens": 6227, "total_output_tokens": 3049,
      "estimated_cost_usd": 0.0, "avg_retrieval_hits": 7.0
    }
  }
}
```

## Prometheus & Grafana (opt-in)

The homegrown tracer above is the default and requires no running service.
For continuous production monitoring, `src/webapp/middleware.py` also
records two Prometheus metrics on every HTTP request
(`deltachat_http_requests_total`, `deltachat_http_request_duration_seconds`,
labeled by method/route-template/status — the route *template*, not the raw
URL, to keep cardinality bounded), and `prometheus_client.make_asgi_app()` is
mounted at `/metrics`. `src/observability/prometheus_metrics.py` adds
request/error counts, span durations, LLM token/cost counters, and delta
items by criticality.

```bash
make infra-up   # docker compose --profile full up -d — starts prometheus:9090, grafana:3000
```

`prometheus/prometheus.yml` scrapes `/metrics` every 15s;
`prometheus/alerts.yml` defines 5 alerts: `DeltaChatDown`,
`HighHTTPErrorRate`, `HighRequestLatencyP95`, `LLMCallErrorRateHigh`,
`RequestErrorRateHigh`. `grafana/provisioning/dashboards/delta-chat.json`
(titled "DeltaIQ") ships 9 panels covering request rate/errors, span p95,
LLM tokens/cost, delta items by criticality, and grounded-vs-ungrounded LLM
calls — every panel query maps to a metric actually emitted above.

See [Data & infrastructure](infrastructure.md) for the full opt-in backend
list this sits alongside (Mongo/Chroma/Pinecone/MinIO/Redis/Celery), and
[Deployment](deployment.md) for how Prometheus/Grafana run in Kubernetes.
