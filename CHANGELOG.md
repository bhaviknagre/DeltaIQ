# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

The single source of truth for the current version is `src/_version.py`;
`python -m src.cli --version`, the web UI footer, and `GET /api/version` all
read from it. Every release here has a matching annotated git tag.

## [2.1.0] — 2026-07-25

### Added
- **Kubernetes manifests** (`k8s/`): namespace, api/worker/redis/chroma/minio/
  monitoring/flower deployments+services, an HPA (CPU+memory, the applied
  default) plus a ready-but-uninstalled KEDA `ScaledObject` alternative
  (scales on Redis list length), an nginx ingress, and a `secrets.yaml`
  template with `REPLACE_ME` placeholders only. Creation-only — validated
  offline, not deployed to a live cluster.
- **GCP Terraform IaC** (`terraform/`): GKE cluster (Workload Identity,
  autoscaling node pool), Artifact Registry, IAM, custom VPC + Memorystore
  Redis, Secret Manager (containers only, no values), a versioned GCS bucket.
  No remote state backend configured — local state only, no `.tfstate`
  committed, matching the "create the IaC, don't deploy" scope.
- **`scripts/checks/check_k8s.py`** (`make check-k8s`): offline `kubeconform`
  schema validation across every `k8s/**/*.yaml`, including the KEDA CRD via
  the community CRDs-catalog schema; also asserts the secrets template holds
  only placeholders (checks for real-key-shaped strings like `sk-ant-`/`gsk_`)
  and that MinIO/Grafana deployments pull credentials via `secretKeyRef`.
  Wired into `check_all.py` / `make check`.
- Product renamed to **DeltaIQ** across the web UI, FastAPI app title, and
  Grafana dashboard; sample PID identifiers renamed from placeholder
  `demo-native-a/b` to realistic engineering revision codes
  (`26-9026-REV-A/B`) across docs, tests, and fixtures.

### Fixed
- **Credential redaction**: `MONGODB_URI`/`REDIS_URL` (which can carry a
  password) were being logged in full at every connection
  (`metadata_store.py`, `blob_store.py`) and rendered directly into the
  `/infra` status page's HTML — never committed to git, but a real leak into
  log files, terminal scrollback, and the browser regardless. Added
  `src/config.py::redact_uri()` and applied it at every call site that logs
  or displays either setting (`metadata_store.py`, `blob_store.py`,
  `session_store.py`, all three `/infra` probes). Regression test:
  `tests/test_config_redact_uri.py` (synthetic fixture credentials only).

## [2.0.0] — 2026-07-24

### Added
- **Production data/infra stack, opt-in**: `MetadataStore` (`JsonFileMetadataStore`
  default, `MongoMetadataStore` real option — 6 collections), `BlobStore`
  (`LocalDiskBlobStore` default, `MinioBlobStore`/`MongoGridFSBlobStore` real
  options), `VectorStore` (`NullVectorStore` default, `ChromaVectorStore`/
  `PineconeVectorStore` real options), and a Redis-backed `ChatSessionStore`
  (6h TTL, cache-aside, in-memory fallback). Every real backend falls back to
  its zero-infra default with a logged warning if it can't connect.
- **Optional vector/hybrid retrieval** (`RETRIEVAL_BACKEND=bm25|vector|hybrid`):
  a new `Embedder` interface (`HashingEmbedder` — deterministic, offline,
  hashing-trick; `OpenAIEmbedder` — real semantic embeddings) feeding the new
  `VectorStore`s; BM25 stays the default for this tag/code-dominated corpus.
- **Background jobs** (`src/tasks/`): Celery (Redis broker+backend),
  `ingest_and_delta`/`render_markup`/`run_eval` tasks mirroring lifecycle into
  `MetadataStore.processing_jobs`; `CELERY_TASK_ALWAYS_EAGER` for synchronous
  in-process execution without a live worker. `make worker` / `make flower`.
- **API schemas + request middleware** (`src/webapp/schemas.py`,
  `src/webapp/middleware.py`): Pydantic models for `/api/chat` (previously a
  raw dict, so a missing field surfaced as an unhandled 500 instead of a 422);
  `RequestContextMiddleware` for `X-Request-ID` propagation, per-request
  timing, and Prometheus counters/histograms mounted at `/metrics`.
- **Prometheus + Grafana, opt-in**: `prometheus/alerts.yml` (5 alert rules:
  `DeltaChatDown`, `HighHTTPErrorRate`, `HighRequestLatencyP95`,
  `LLMCallErrorRateHigh`, `RequestErrorRateHigh`) and a 9-panel Grafana
  dashboard (`grafana/provisioning/dashboards/delta-chat.json`) covering
  request rate/errors, span p95, LLM tokens/cost, and delta criticality.
- **Langfuse, opt-in**: LLM-call tracing alongside the existing homegrown
  tracer; no-op if unconfigured.
- **Real DVC pipeline** (`dvc.yaml`/`dvc.lock`): `samples` → `eval` stages,
  params tracked in `params.yaml`, a local-filesystem remote
  (`.dvc/config` → `.dvc-local-remote/`). `make dvc-repro` / `dvc-dag` /
  `dvc-metrics`.
- `docker-compose.yml` profiles for the new stack: `full` (mongo, redis,
  minio, chroma, prometheus, grafana) and `worker` (celery-worker, flower).
- `/infra` web UI page: live reachability probes (not just "is it
  configured") against Mongo, Redis, Celery-via-Redis, and the configured
  vector store.

### Fixed
- Pinecone upserts above ~1000 vectors/request returned a 400 — found during
  live key verification; batched at 100 vectors per request.
- `docker-compose.yml` MinIO credentials were hardcoded rather than reading
  `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` from `.env` — one value now feeds both
  the Python app and the MinIO container's root credentials.
- Full-project audit: a gap in the Grafana dashboard's panel-to-metric
  mapping, a stale docstring, and a DVC remote that had drifted out of sync
  with `dvc.lock`.

## [1.1.0] — 2026-07-24

### Added
- **Criticality signal** (`src/delta/criticality.py`): a deterministic
  🔴/🟡/🟢 rating on every `DeltaItem`, separate from `confidence` — dimension
  modifications/removals and tag removals are red, tag/dimension additions
  and note/text removals are yellow, everything else green. Surfaced in the
  delta report, the markup overlay (boxes now colored by criticality, not
  just change kind), the eval scorecard, and the web UI.
- **Web UI** (`src/webapp/`): FastAPI + server-rendered Jinja2 + hand-rolled
  vanilla-SVG charts (no CDN dependency). Dashboard (canonical-representation
  summary cards, changes-by-kind bar chart, criticality donut, signal-chip
  delta table, markup PDF download), chat (fetch-based, citation chips,
  cost/token/model per answer), and eval (PASS/FAIL banner, F1/accuracy
  gauges, OCR-accuracy/latency/token/cost stats, multi-run trend chart,
  candid failure table, "run new eval" button). `make ui`.
- **Groq LLM provider** (`src/chat/llm.py::GroqProvider`): a free-tier,
  no-credit-card-required real LLM option — `OpenAIProvider` pointed at
  Groq's OpenAI-compatible endpoint with a free open model
  (`llama-3.3-70b-versatile`), no separate integration code.
- **MkDocs documentation site** (`mkdocs.yml`, `docs/`): architecture (with
  mermaid request-flow diagrams), formats, delta engine + criticality,
  grounded chat, observability, evaluation, the web UI, and an output
  reference page with real captured output. `make docs` / `make docs-build`.
- **Reshaped eval scorecard** (`eval/run_eval.py`): Precision/Recall/F1,
  Chat Correctness/Groundedness/Citation Accuracy, a real computed
  **OCR-accuracy metric** (`eval/metrics.py::score_ocr_accuracy` — word-level
  overlap between the OCR adapter's output and the native adapter's output on
  identical underlying content), real per-question latency/token/cost from
  live LLM calls, and a **PASS/FAIL banner** against documented thresholds.
- **Per-subsystem check scripts** (`scripts/checks/`): env, ingestion, delta
  engine, delta report + markup, retrieval, observability, chat, web UI,
  eval harness, and MkDocs build — each independently runnable so a failure
  is isolated to one subsystem. `scripts/check_all.py` (`make check` /
  `make check-fast`) runs all of them in dependency order with a final
  pass/fail summary; `make check-<subsystem>` runs just one.
- `CanonicalDocument.summary()` — the pages/elements/tables/dimensions shape
  the web UI dashboard reads, honestly reporting `tables: 0` since no adapter
  currently detects tabular regions.
- Versioning: `src/_version.py`, `--version` on the CLI, `/api/version` +
  footer on the web UI, this changelog, and a matching git tag per release.

### Fixed
- A failed LLM provider call (network error, rate limit, exhausted quota)
  previously crashed the whole request with a raw traceback — discovered
  live against a valid-but-unbilled OpenAI key. `chat/answer.py` now
  catches it, logs and traces the failure (which was already being recorded
  correctly), and degrades to a single non-grounded answer instead of
  taking down the request (or, for `make eval`, every remaining question).
- `ingest/classify.py`'s numbered-note regex had a dead `\b` after a literal
  `.` (a word boundary can't exist between two non-word characters), which
  silently misclassified bare-numbered notes like `"1. FIRST NOTE"` as plain
  text. Fixed and covered by a regression test.
- Retrieval (`chat/index.py`) had two related bugs, both found via the eval
  harness: (1) confidence-floor normalization was relative to the current
  query's own top score, so the single best-of-a-bad-bunch result always
  passed the floor regardless of actual relevance — an off-topic/adversarial
  question could still return a "confident" answer instead of refusing; (2)
  no stopword filtering meant generic tokens (`"id"` from "P&ID" splitting
  into `p`+`id`) spuriously matched everywhere. Fixed with a hard lexical-
  overlap gate and a small domain-aware stopword list.

## [1.0.0] — 2026-07-24

Initial submission: format-agnostic ingestion (native PDF, scanned PDF/OCR,
DXF-as-DWG-seam), deterministic delta engine with alignment/classification/
confidence, Markdown+JSON delta report, BM25-grounded chat with citations
and a provider-agnostic LLM client (Anthropic/OpenAI/mock fallback), redline
markup overlay, homegrown tracing/structured logging/metrics, and an eval
harness (delta P/R/F1 + chat accuracy/groundedness/citation accuracy) with
labeled ground truth built from the supplied sample P&IDs.
