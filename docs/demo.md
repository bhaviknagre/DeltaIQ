# Demo walkthrough

!!! note "On the numbers and screenshots below"
    Every output on this page is real, captured from this repo's own sample
    pair (`26-9026-REV-A` / `26-9026-REV-B` — a synthesized Rev A → Rev B of a
    real supplied P&ID). Nothing here is a mockup or a hypothetical number.

## 1. Problem statement

Engineering teams re-issue P&IDs (Piping & Instrumentation Diagrams) across
revisions — a line size changes, a tag gets renumbered, a note is added per a
Management-of-Change record. Today that comparison is done **by eye**,
overlaying two large drawings page by page. It's slow, and the failure mode
is the expensive one: a missed dimension or tag change is exactly the class
of error that causes rework or mis-fabrication downstream. Compounding this,
the two revisions rarely arrive in the same format — native PDF, a scanned
paper copy, or CAD (DWG/DXF) — so any tool that only handles one format
doesn't solve the real problem.

## 2. What we built

**DeltaIQ**: given two PID revisions in *any* of those formats, it

1. **Ingests** both into one common `CanonicalDocument` shape, regardless of
   source format ([Ingestion & formats](formats.md)),
2. **Computes a structured delta** deterministically — alignment,
   classification, and a red/yellow/green **criticality** signal that flags
   *how much a change matters engineering-wise*, not just that something
   changed ([Delta engine & criticality](delta-engine.md)),
3. **Renders a human- and machine-readable report** (Markdown + JSON) and an
   optional redline markup overlay on the actual drawing,
4. **Answers questions** over both revisions and the delta, grounded with
   citations back to the source elements ([Grounded chat](chat.md)),
5. Runs with **zero infrastructure** by default (JSON file, local disk,
   BM25), with a full production-shaped stack (Mongo, Redis/Celery,
   Chroma/Pinecone, MinIO, Prometheus/Grafana, Langfuse) as an opt-in swap
   behind the same code path — see [Data & infrastructure](infrastructure.md).

The whole system is deliberately **candid about its own limits** rather than
tuned to look better than it is — see the "candid failures" callouts
throughout these docs and in the eval numbers below.

## 3. Repository walkthrough

```
src/
├── ingest/         format adapters (native PDF, scanned+OCR, DXF) -> canonical model
├── canonical/       the seam: CanonicalDocument, typed/located/confidence-scored elements
├── delta/           alignment, classification, criticality, report rendering
├── chat/            provider-agnostic LLM client, retrieval, grounded answer + citations
├── storage/         MetadataStore / BlobStore / VectorStore — each: zero-infra default + opt-in backend
├── observability/    homegrown tracer, structured logs, metrics, Prometheus, Langfuse
├── webapp/          FastAPI UI — dashboard, chat, eval scorecard, infra status
└── cli.py           run / chat / markup entry points

data/samples/         synthetic revision-pair generator + ground truth
eval/                 delta P/R/F1 + chat accuracy/groundedness/citation scorecard
docs/                 this MkDocs Material site
grafana/, prometheus/ dashboards + scrape/alert config for the opt-in infra stack
k8s/, terraform/       Kubernetes manifests + GCP IaC for a production deployment
```

One rule holds throughout: every storage/retrieval backend
(`src/storage/*.py`) has a **zero-infra default** that falls back gracefully
with a logged warning if the "real" backend isn't reachable — so nothing in
the opt-in stack below is required to run the system, only to run it
production-shaped.

## 4. UI demonstration

```bash
make ui   # http://localhost:8000
```

- **Dashboard (`/`, `/results`)** — pick two registered PIDs, run the delta,
  and see canonical summary cards, a changes-by-kind bar chart, a
  criticality donut, and the full delta table sorted red → yellow → green so
  the changes that matter most surface first. Links out to the
  Markdown/JSON report and the markup PDF download.
- **Chat (`/chat`)** — the same grounded `answer_question()` call the CLI
  uses, with citation chips, model used, token counts, and cost shown
  per answer.
- **Eval (`/eval`)** — a PASS/FAIL banner, gauges for delta F1 and chat
  accuracy, stat tiles, a 10-run trend chart, and a "Run new eval" button
  that calls the exact same scoring functions `make eval` does.
- **Infra status (`/infra`)** — live reachability probes (not just "is it
  configured") for every backend this deployment points at — Mongo, Redis,
  Celery, Chroma/Pinecone, Langfuse — with any connection string redacted
  before it's rendered.

Full page-by-page detail: [Web UI](ui.md).

## 5. Reading the outputs

### The delta report

```bash
python -m src.cli run 26-9026-REV-A 26-9026-REV-B --out-dir output/native
```

```
Delta: {'added': 2, 'removed': 1, 'modified': 3} (6 total changes)
Report: output/native/delta_report.md
Report (JSON): output/native/delta_report.json
```

```
- **[MODIFIED] [tag]** at (447, 404) — Changed and moved: '26-KA-902' -> '26-KA-902B' (confidence: 0.93)
- **[REMOVED] [text]** at (1117, 563) — Text removed: 'TO CLOSED DRAIN' (confidence: 1.00)
- **[ADDED] [tag]** at (900, 699) — New tag added: '26-PSV-9099' (confidence: 1.00)
```

Every line carries **two independent signals** — don't read them as the same
thing:

| Signal | Question it answers |
|---|---|
| **Confidence** (0–1, shown per item) | How *certain* is the engine that this change was detected/matched correctly? |
| **Criticality** (🔴/🟡/🟢, the "traffic light") | How much does this change *matter*, engineering-wise, independent of that certainty? |

### The red/yellow/green criticality signal

This is the chart/legend you'll see on the markup overlay, the dashboard
donut, and every delta-table row:

| | Meaning |
|---|---|
| 🔴 **Red** | A dimension (line size / pressure / temp / tolerance) was modified or removed, or a tag was removed entirely — the class of change that historically gets missed in manual review. |
| 🟡 **Yellow** | A tag was modified/added, a dimension was added, or a note/text item was removed — worth a reviewer's attention. |
| 🟢 **Green** | Everything else — added/modified notes or generic text, moved-only changes. Informational. |

### The eval gauges (F1 / accuracy)

The `/eval` page and `make eval` scorecard both color-code by the same
thresholds (`src/webapp/static/charts.js`):

| Color | Range | Meaning |
|---|---|---|
| 🟢 Green | ≥ 0.90 | Strong — trust it |
| 🟡 Amber | 0.75 – 0.89 | Acceptable, watch it |
| 🔴 Red | < 0.75 | Below the PASS bar |

The PASS/FAIL banner itself uses a 0.75 floor on delta F1, chat accuracy, and
groundedness (`eval/run_eval.py::PASS_THRESHOLDS`) — a judgment call chosen
to allow the honest, documented OCR/BM25 gaps below without masking a real
regression:

```
delta_native_f1            = 1.00   (exact — all 6 authored edits found, nothing invented)
delta_scanned_f1            = 0.75   (recall 1.00, precision 0.60 — 4 OCR-noise false positives)
chat_accuracy               = 0.857
chat_groundedness_rate      = 0.833
chat_citation_accuracy      = 0.667
passed                      = true
```

## 6. Flower, Grafana, Prometheus

```bash
make infra-up   # docker compose --profile full up -d
make flower     # :5555
```

- **Flower** (`:5555`) — Celery task monitor. Watch `delta`/`ingest` jobs
  move through received → started → succeeded in real time when the
  `worker` profile is up, with per-task runtime and args.
- **Prometheus** (`:9090`) — scrapes `/metrics` every 15s
  (`prometheus/prometheus.yml`). One real query to try in the Prometheus
  expression browser:

  ```promql
  sum by (provider) (deltachat_llm_cost_usd_total)
  ```

  — cumulative estimated LLM spend, grouped by provider (anthropic/openai/
  groq/mock), sourced straight from `src/observability/prometheus_metrics.py`.

- **Grafana** (`:3000`, anonymous viewer enabled) — the "DeltaIQ" dashboard
  (`grafana/provisioning/dashboards/delta-chat.json`) ships 9 panels. The one
  above ("Estimated LLM cost (USD)") is backed by the exact PromQL query
  shown; the others follow the same pattern:

  | Panel | Query |
  |---|---|
  | Request rate by kind | `sum by (kind) (rate(deltachat_requests_total[5m]))` |
  | Request error rate by kind | `sum by (kind) (rate(deltachat_request_errors_total[5m]))` |
  | Span duration p95 | `histogram_quantile(0.95, sum by (span_name, le) (rate(deltachat_span_duration_seconds_bucket[5m])))` |
  | LLM tokens/sec by provider+direction | `sum by (provider, direction) (rate(deltachat_llm_tokens_total[5m]))` |
  | Delta items by criticality | `sum by (criticality) (deltachat_delta_items_total)` |
  | Grounded vs ungrounded LLM calls | `sum by (provider, grounded) (rate(deltachat_llm_calls_total[5m]))` |
  | HTTP request rate by route+status | `sum by (path, status) (rate(deltachat_http_requests_total[5m]))` |
  | HTTP p95 duration by route | `histogram_quantile(0.95, sum by (path, le) (rate(deltachat_http_request_duration_seconds_bucket[5m])))` |

  `prometheus/alerts.yml` also defines 5 alerts (`DeltaChatDown`,
  `HighHTTPErrorRate`, `HighRequestLatencyP95`, `LLMCallErrorRateHigh`,
  `RequestErrorRateHigh`) that fire off these same metrics.

Full detail: [Observability](observability.md).

## 7. Langfuse (LLM-specific observability)

Set `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` (`LANGFUSE_HOST` defaults
to Langfuse Cloud) and every LLM call in `chat/answer.py` /
`chat/agentic.py` is additionally logged to Langfuse — prompt, completion,
token usage, latency, and cost per generation — on top of (not instead of)
the homegrown tracer, so nothing about request tracing depends on Langfuse
being configured. The `/infra` UI page probes it live via
`get_langfuse_client().auth_check()`, not just "is a key present." No-op
(silently skipped) if unset.

## 8. MinIO (blob storage)

Raw PDFs, scanned page images, OCR intermediate artifacts, and markup output
PDFs all go through one `BlobStore` interface
(`src/storage/blob_store.py`). By default that's SHA1-hashed files under
`data/blobs/` on local disk; set `BLOB_STORE=minio` and the identical code
path writes instead to an S3-compatible MinIO bucket
(`delta-chat`, per `MINIO_BUCKET`) — console at `:9001`
(`admin` / `MINIO_SECRET_KEY` from `.env`), object storage API at `:9000`.
Same interface, same call sites either way — the only thing that changes is
where the bytes land.

## 9. Closure

DeltaIQ takes a comparison problem that today costs an engineer time and
carries real downstream risk when done by eye, and replaces it with a
deterministic, explainable, cited pipeline — one that's honest about where it
still falls short (OCR precision on scanned input, BM25 paraphrase misses on
chat) rather than hiding those numbers. Everything demoed above — the delta
engine, the criticality signal, the grounded chat, and the full
Prometheus/Grafana/Flower/Langfuse/MinIO observability and infra stack — runs
from the same codebase with zero infrastructure required, and scales up to
the production-shaped stack (and the Kubernetes/Terraform deployment in
[Deployment](deployment.md)) by flipping env vars, not rewriting code.
