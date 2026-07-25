# DeltaIQ

Given two PIDs (revisions of the same engineering document), DeltaIQ ingests
both regardless of format, computes a structured delta, renders a human- and
machine-readable delta report, and answers questions over both revisions and the
delta with citations.

📖 Full documentation: **[bhaviknagre.github.io/DeltaIQ](https://bhaviknagre.github.io/DeltaIQ/)**
(MkDocs Material — architecture diagrams, the production data/infra stack,
Kubernetes & Terraform, observability, evaluation, and an output reference
with real captured output). `make docs` serves the same site locally.

## Quickstart

```bash
make setup     # venv + deps (app + docs) + checks for tesseract (brew install tesseract / apt-get install tesseract-ocr)
make samples   # synthesize the demo revision pairs (see "Sample data" below)
make run       # ingest -> delta -> report on the native-PDF pair (reproducible run)
make chat      # grounded chat REPL over that pair + its delta
make ui        # web dashboard + chat + eval scorecard, at http://localhost:8000
make markup    # bonus: redline overlay PDF
make eval      # scorecard: delta P/R/F1 + chat correctness/groundedness/citation accuracy
make test      # unit + integration tests
make docs      # MkDocs documentation site, served locally
```

Everything above runs with **zero infrastructure** — a JSON file, local disk,
and BM25. A real data/infra stack (MongoDB, Redis/Celery, Chroma/Pinecone,
MinIO, Prometheus/Grafana) is opt-in on top of the same code path:

```bash
make infra-up   # docker compose --profile full up -d — see "Data & infrastructure"
```

Or via Docker (also installs tesseract, so it sidesteps the local OCR dependency):

```bash
cp .env.example .env   # fill in a key if you have one; runs fine without one (see LLM section)
docker compose up               # reproducible run
docker compose --profile chat up chat
docker compose --profile eval up eval
```

No API key is required to run any of the above — see "LLM provider" below.

## Architecture

```
PID A, PID B (bytes + metadata)
        |
   FormatAdapter (one interface: sniff() + parse())
   ├─ NativePdfAdapter   (PyMuPDF text layer)
   ├─ ScannedPdfAdapter  (rasterize + Tesseract OCR)
   └─ DwgAdapter         (ezdxf; DXF today, DWG via a conversion pre-step)
        |
        v
   CanonicalDocument      <- the seam. Pages -> Elements, each with a type
   (canonical/model.py)      (tag/dimension/note/text/table_cell/geometry),
        |                    a bounding box, source, and confidence.
        v
   align(doc_a, doc_b)     -> AlignmentResult (matched / added / removed)
   compute_delta(...)      -> DeltaResult: typed, located, confidence-scored
        |                    DeltaItems (deterministic, no LLM involved)
        v
   delta/report.py         -> Markdown + JSON delta report
        |
        v
   chat/index.py            BM25 retrieval over PID A + PID B + delta report,
   chat/answer.py            each chunk citation-labeled back to its exact source
   chat/llm.py               -> provider-agnostic LLM call -> cited answer
   chat/agentic.py           (opt-in) LangGraph: + verify-citations -> retry
```

Everything below `CanonicalDocument` — alignment, delta, report, retrieval, chat —
never imports a format-specific adapter. Adding a 4th format means writing one
class with `sniff()` + `parse() -> CanonicalDocument`; nothing else changes.

## Format support

| Format | Status | How |
|---|---|---|
| Native PDF | **Fully working** | PyMuPDF `get_text("dict")` line-level extraction with real bounding boxes. Deterministic, no OCR. |
| Scanned PDF | **Fully working** | Rasterize at 300dpi -> Tesseract OCR (`--psm 11`, sparse-text mode — see "OCR tuning" below) -> word-grouped, line-level elements with OCR confidence carried through. |
| DWG | **Real stub behind the same interface** | `ezdxf` parses real DXF (TEXT/MTEXT/LINE/LWPOLYLINE/CIRCLE -> typed elements with bounding boxes and layer metadata). `.dwg` itself needs conversion to `.dxf` first (ODA File Converter or Autodesk SDK — no license-free pure-Python DWG reader exists); the adapter raises a clear `NotImplementedError` naming that pre-step. The seam is real: point it at a `.dxf` and it ingests into the exact same `CanonicalDocument` the PDF adapters produce. |

Two of three formats are fully working end-to-end (native + scanned PDF), which
is the assignment's minimum bar; DWG is a genuine stub, not a hypothetical one.

## Delta engine

Alignment (`delta/align.py`) is the hard part, not diffing. There's no stable
cross-revision ID for a text run in a re-exported PDF/DXF, so correspondence is
inferred:

1. **Exact match** — identical text at (near-)identical position, same page -> unchanged.
2. **Greedy best-score match** on what's left — score = 0.65 × text similarity
   (rapidfuzz) + 0.35 × spatial proximity (bbox-center distance), restricted to
   the same page, taken greedily highest-score-first. This is a deliberate
   trade-off over an optimal (Hungarian) bipartite match: P&ID sheets have
   hundreds of small elements, greedy converges to the same alignment as optimal
   matching in practice for well-separated content, and is much simpler to
   reason about and debug.
3. Anything left unmatched in A is a **removal** candidate; unmatched in B is an
   **addition** candidate.

Matched pairs are then classified (`delta/engine.py`) as **modified** (text
changed and/or moved beyond a small tolerance) or dropped as unchanged. Every
`DeltaItem` carries a type (reusing the domain `ElementType`: tag / dimension /
note / text / table_cell / geometry), a page + bounding box, before/after text,
a human description, and a confidence score (blended match score × extraction
confidence — so a low-confidence OCR match propagates a lower delta confidence,
not a false "1.0").

**Determinism**: the whole delta engine — alignment, classification, confidence
— is pure Python/regex/rapidfuzz, zero LLM calls. Same input -> byte-identical
output, every time (see `tests/test_delta_engine.py::test_confidence_is_reproducible_across_runs`).
LLM non-determinism is isolated entirely to `chat/answer.py`.

Classification of raw text into tag/dimension/note/text (`ingest/classify.py`)
is deterministic regex, not an LLM call — a judgment call worth stating
explicitly: P&ID tag codes, pipe specs, and numbered notes follow regular
enough patterns that regex is free, instant, and exactly as accurate as an LLM
would be here, and LLM effort is better spent on chat answers where genuine
language understanding is needed.

**Criticality signal (red/yellow/green)**: `delta/criticality.py` adds a
second, deliberately separate score to every `DeltaItem` — `confidence`
answers "how sure are we this was detected correctly," `criticality` answers
"how much does it matter" (independent of that certainty). Deterministic
rules: a dimension modified/removed or a tag removed → 🔴 red (the class of
change that historically gets missed in manual review and causes rework); a
tag modified/added, dimension added, or note/text removed → 🟡 yellow;
everything else → 🟢 green. It's a heuristic classifier, not a
magnitude-aware one (it reacts to *what* changed, not *by how much* — see
"what's next"). Surfaced in the delta report, the markup overlay (boxes now
colored by criticality, not just change kind), and the [web UI](#web-ui--documentation).

## Grounded chat

Retrieval (`chat/index.py`) is BM25 (`rank_bm25`) over three chunk sources: every
element in PID A, every element in PID B, and every delta-report item — each
chunk carries a `Citation` back to its exact source (`pid_a:<pid>@p<page>`,
`pid_b:...`, or `delta:<delta_item_id>`).

**Why BM25, not embeddings**: no API key required (works fully offline, fully
deterministic — good for reproducible eval), and P&ID content is dominated by
exact tags/codes/dimensions where lexical match is *more* reliable than
semantic similarity ("26-KA-902" should match "26-KA-902", not something merely
related to it). The real cost of this choice is paraphrase queries that don't
share vocabulary with the source text — see "Known limitations" below; named as
explicit future work, not a hidden gap.

Two retrieval-quality fixes, found empirically via the eval harness and kept
because they're generally correct, not because they were needed to pass one
test:
- A small domain-aware stopword filter (plus dropping 1-character tokens) —
  without it, generic tokens like `"id"` (from "P&ID" tokenizing to `p`+`id`)
  spuriously matched everywhere, so a completely off-topic query still returned
  a "confident" top hit.
- Retrieval requires **at least one real content-token overlap** between query
  and chunk as a hard gate, not just a relative score threshold — a
  same-query-relative-max normalization meant the single best-of-a-bad-bunch
  chunk always cleared the confidence floor, which defeats the point of having one.
- Delta-report chunks get a modest ranking boost and exact-duplicate chunks are
  de-duplicated within the top-k window, so three identical tag-label chunks
  don't crowd out the one delta-report entry that actually answers a
  "what changed" question.

**Grounding & refusal**: if retrieval finds nothing with real lexical overlap,
the LLM is never called — the system hedges directly
(`"I don't have grounded evidence to answer that"`). When the LLM is called, the
system prompt requires every claim to end with the exact bracketed citation
label it came from; `chat/answer.py` parses those citations back out and flags
an answer "grounded" only if it actually contains ≥1 real citation.

**LLM provider** (`chat/llm.py`): one `LLMProvider` interface, four
implementations — Anthropic, OpenAI, Groq, and a `MockProvider`. No key was
available in the environment this was built in, so `LLM_PROVIDER` defaults to
whichever provider *has* a key configured, and falls back to `MockProvider` if
none does. The mock is not a fake generative model — it extracts and lists the
retrieved, cited context verbatim, clearly labeled `[MOCK LLM]`, so `make eval`
/ `make chat` stay honestly runnable offline for grading. Set
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GROQ_API_KEY` (+`LLM_PROVIDER`) in
`.env` to get real generated answers — no code changes needed.

**Free option**: Groq's free developer tier (console.groq.com/keys, no credit
card) is genuinely free within its rate limits. `GroqProvider` is just
`OpenAIProvider` pointed at Groq's OpenAI-compatible endpoint
(`https://api.groq.com/openai/v1`) with a free open model
(`llama-3.3-70b-versatile`) — no separate integration code, same
citations/grounding/tracing behavior as the paid providers. Set
`LLM_PROVIDER=groq` + `GROQ_API_KEY` in `.env`.

### Agentic mode (LangGraph)

`chat/answer.py` above is one retrieve → LLM → parse-citations round trip: it
trusts whatever citations the LLM attaches to its answer. `chat/agentic.py`
is an additive alternative — a small LangGraph `StateGraph` that adds one
real self-correction step on top:

```
retrieve -> generate -> verify_citations -+-> END (verified, or a clean hedge)
               ^                          |
               +---- widen + retry <------+  (citation not among retrieved evidence)
```

**What verification actually checks**: every bracketed citation label the LLM
used (`[pid_a:...]`, `[delta:...]`) must belong to a chunk that was really
retrieved for this question. An LLM can produce a citation that's
well-formed but not grounded in anything retrieved — right shape, wrong (or
no) source — which the simple pipeline has no way to notice since it only
checks that *a* citation-shaped string is present. On a failed verification,
retrieval is widened (3x `top_k`, half `min_score`) and the question is
re-answered, up to `AGENTIC_MAX_RETRIES` (default 2) times, before returning
the last answer produced with `verified=False` rather than looping forever.

This is genuinely additive, not a rename of the same logic: `chat/llm.py`
still owns every provider integration, the mock/no-key fallback, and cost
telemetry, unchanged. `chat/langchain_llm.py` adds one seam —
`ProviderBackedChatModel`, a LangChain `BaseChatModel` that delegates
`_generate` straight to `LLMProvider.complete` — so the LangGraph nodes get
a message-based interface without a second, competing LLM integration.

Opt in via:
- CLI: `python -m src.cli chat <pid_a> <pid_b> --agentic -q "..."`
- API: `POST /api/chat` with `"agentic": true` in the JSON body
- Globally: `CHAT_BACKEND=agentic` in `.env` (both call sites default to this
  when the flag/field is omitted)

`AnswerResult` gains `verified: bool` and `attempts: int` in this mode
(`AgenticAnswerResult`, a strict superset — `chat/answer.py` and its callers
are untouched). Covered by `tests/test_agentic_chat.py` (happy path,
hallucinated-citation retry-then-give-up, provider-failure degradation, and
the no-evidence hedge) and by `scripts/checks/check_chat.py` against
whichever real provider is configured.

## Observability

Homegrown tracer (`observability/tracing.py`) instead of OpenTelemetry/Langfuse/
Phoenix: there's no always-on collector in this environment, and the grading
environment shouldn't need one running just to inspect a request. Every request
writes one self-contained JSON file to `traces/<request_id>.json` — inspectable
with `cat`, diffable across runs, zero infrastructure. The shape (trace id,
named spans with start/end/duration/attrs/status, errors captured on the span
and re-raised rather than swallowed) mirrors OTel's span model closely enough
that swapping in a real OTel SDK later touches `Tracer`'s internals, not call
sites.

- **Tracing**: `ingest_a` / `ingest_b` / `delta` / `retrieve` / `llm_call` /
  `answer` spans, each with duration.
- **LLM telemetry**: every `llm_call` span records provider, model,
  input/output tokens, and an estimated cost (`config.py` pricing table).
- **Structured logs**: JSON lines to `logs/app.jsonl`, every line carrying a
  `request_id` correlation id (contextvar-scoped per trace).
- **Metrics**: `make metrics` (`observability/metrics.py`) reduces over
  `traces/*.json` — request counts, error counts, avg/p95 latency, total
  tokens/cost, avg retrieval hits, avg delta count, grouped by request kind.
  Satisfies "inspectable metrics" with zero running services.
- **Prometheus/Grafana (opt-in)**: `src/webapp/middleware.py`
  (`RequestContextMiddleware`) records per-request Prometheus counters/
  histograms (route-template-labeled, not raw URL, to bound cardinality);
  `prometheus_client.make_asgi_app()` is mounted at `/metrics`.
  `make infra-up` starts Prometheus (`:9090`, 5 alert rules in
  `prometheus/alerts.yml`) and Grafana (`:3000`, a 9-panel dashboard in
  `grafana/provisioning/dashboards/delta-chat.json`) for continuous
  monitoring — genuinely wired up now, not a placeholder. See
  [docs/observability.md](docs/observability.md).
- **Langfuse (opt-in)**: `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` add
  LLM-call tracing to Langfuse on top of the homegrown tracer; no-op if
  unset.

## Data & infrastructure

Every backend below is opt-in — the system runs with zero infrastructure by
default (a JSON manifest, local disk, BM25), and each real backend falls back
to its zero-infra default with a logged warning if it can't connect.

| Interface | Zero-infra default | Real backend(s) | Env var |
|---|---|---|---|
| `MetadataStore` | `JsonFileMetadataStore` | `MongoMetadataStore` (6 collections) | `METADATA_STORE=json\|mongo` |
| `BlobStore` | `LocalDiskBlobStore` | `MinioBlobStore`, `MongoGridFSBlobStore` | `BLOB_STORE=local\|minio\|mongo_gridfs` |
| `VectorStore` | `NullVectorStore` | `ChromaVectorStore`, `PineconeVectorStore` | `VECTOR_STORE=none\|chroma\|pinecone` |
| Retrieval | BM25 | vector (via `VectorStore`) or hybrid (weighted blend) | `RETRIEVAL_BACKEND=bm25\|vector\|hybrid` |
| Chat sessions | in-memory dict | Redis, 6h TTL, cache-aside over `MetadataStore` | `REDIS_URL` |
| Background jobs | — | Celery (Redis broker+backend): `ingest_and_delta`, `render_markup`, `run_eval` — `CELERY_TASK_ALWAYS_EAGER=true` runs them synchronously | `make worker` / `make flower` (`:5555`) |

```bash
make infra-up   # docker compose --profile full up -d
# mongo:27017  redis:6379  minio:9000 (console :9001)  chroma:8100  prometheus:9090  grafana:3000
```

**DVC pipeline** (`dvc.yaml`): `samples` → `eval` stages, tracked params in
`params.yaml`, reproducible via `make dvc-repro` / `dvc dag` / `dvc metrics show`.
The configured remote is local-filesystem (`.dvc/config` →
`.dvc-local-remote/`) — a real DVC remote, just not a cloud one, matching the
"opt-in infra, nothing required to run" posture throughout this project.

**Credential handling**: `mongodb_uri`/`redis_url` can carry a password.
Every call site that logs or displays either (`blob_store.py`,
`metadata_store.py`, `session_store.py`, the `/infra` web UI page) passes it
through `src/config.py::redact_uri()` first — `user:pass@` becomes `***:***@`
before it ever reaches a log line or a browser. Regression-tested in
`tests/test_config_redact_uri.py` against synthetic fixture credentials, not
real ones.

Full backend matrix, config, and rationale: [docs/infrastructure.md](docs/infrastructure.md).

## Deployment: Kubernetes & Terraform

**Creation-only, not deployed** — both layers are written and validated
offline; neither has touched a live cluster or a real GCP project.

- **Kubernetes** (`k8s/`): namespace, api/worker/redis/chroma/minio/monitoring/
  flower manifests, an HPA (2–8 / 2–10 replicas, the applied default) plus a
  ready-but-uninstalled KEDA `ScaledObject` alternative, an nginx ingress, and
  a secrets template where every value is `REPLACE_ME`. Validated offline via
  `make check-k8s` (`kubeconform` schema validation across all manifests,
  including the KEDA CRD — never `kubectl apply`, never a live cluster; also
  asserts the secrets template holds no real-key-shaped strings).
- **Terraform** (`terraform/`): GKE cluster (Workload Identity, autoscaling
  node pool), Artifact Registry, IAM, custom VPC + Memorystore Redis, Secret
  Manager (containers only, no values — kept out of `.tfstate` on purpose), a
  versioned GCS bucket. No remote state backend configured; no `.tfstate`
  anywhere in the repo — `terraform plan` against a real project is the
  honest way to verify this without provisioning anything.

Full manifest/resource inventory: [docs/deployment.md](docs/deployment.md).
- **Failure visibility**: a span that raises records `status="error"` +
  the exception on the trace file, then re-raises — errors are traced, not
  swallowed. (`pytesseract.TesseractNotFoundError`, unknown PIDs, and unparseable
  `.dwg` all surface this way rather than failing silently.)

## Evaluation harness

`make eval` runs `eval/run_eval.py` and prints a scorecard, then saves a
timestamped result under `eval/results/` and diffs it against the previous run
— so a change can be shown to help or hurt, not just asserted to.

**Delta ground truth**: `data/samples/build_synthetic_pairs.py` produces Rev B
from a real source P&ID by applying 6 *exactly known* edits (2 tag renumbers, 1
dimension change, 1 removed callout, 1 added tag, 1 added note — see `EDITS` in
that file) via PyMuPDF redact+reinsert. Because the edits are authored, not
guessed, ground truth is exact — not "what a human thought they saw." The same
6 edits are scored on both the native-PDF pair and a rasterized scanned-PDF pair
built from it, so the OCR path is scored against identical ground truth.

**Chat ground truth**: `eval/datasets/qa_pairs.json` — 7 hand-written
questions over the native pair: 6 grounded content/change questions with
expected keywords, plus 1 deliberately adversarial/off-topic question
(`"What color is the sky drawn in this P&ID?"`) that should trigger a refusal,
not a hallucinated answer.

**Latest scorecard** (real LLM — Groq `llama-3.3-70b-versatile`, free tier, $0 cost):

```
Document Pair    : native
Precision        : 1.00    Recall : 1.00    F1 Score : 1.00
Avg Confidence   : 0.96    Criticality: 🔴 1  🟡 3  🟢 2

Document Pair    : scanned
Precision        : 0.60    Recall : 1.00    F1 Score : 0.75
Avg Confidence   : 0.73    Criticality: 🔴 1  🟡 3  🟢 6
OCR Accuracy     : 87.0%

Chat Correctness : 0.86    Groundedness : 0.83    Citation Accuracy : 0.60
Latency          : 0.41 sec/question (avg)   Tokens Used : 2,687   Cost : $0.0000

PASS
```

- **Delta P/R/F1**: matches predicted `DeltaItem`s to ground-truth edits by
  change-kind + text containment (robust across native line-granularity vs.
  OCR's coarser word-clustering), then precision/recall/F1 over matched vs.
  missed vs. spurious. `avg_confidence` and the 🔴/🟡/🟢 criticality counts are
  the same signal shown in the delta report and web UI (see "Delta engine").
- **OCR accuracy**: a *real*, computed word-level overlap between the OCR
  adapter's output and the native adapter's output on the identical
  underlying document (`eval/metrics.py::score_ocr_accuracy`) — not asserted,
  measured.
- **Chat accuracy**: keyword match in the answer AND `grounded=True` (or, for
  the adversarial question, a correct refusal).
- **Citation accuracy**: for correct, non-hedge answers, checks that cited
  chunks *actually contain* an expected keyword — verifies citations aren't
  just decorative. Low here (0.60) mostly because many correct answers cite
  short single-tag chunks that don't literally contain the full expected phrase
  even when they're the right source — noted as a metric-design limitation, see
  below.
- **PASS/FAIL**: a banner against documented thresholds
  (`eval/run_eval.py::PASS_THRESHOLDS` — delta F1, chat accuracy, and
  groundedness all ≥ 0.75), chosen to tolerate the known OCR/BM25 gaps below
  without masking an actual regression.
- **Groundedness dropped 1.00 → 0.83 when the mock LLM was replaced with a
  real one** — not a regression: the mock always echoed whatever was
  retrieved as "grounded," while Groq correctly *refuses* on the qa-6
  retrieval gap per the system prompt's hedge instruction. The eval harness
  catching its own earlier optimism bias, live.

### Candid failures

- **Scanned-PDF precision (0.60)**: 4 of 10 predicted changes on the OCR path
  are noise — stray glyph misreads (`'ant' -> 'at'`, `'Sat' -> 'Oat'`) and one
  wrapping difference on a long boilerplate line. Recall is perfect (all 6 real
  edits found); precision is the honest cost of OCR on a dense technical
  drawing. `--psm 11` (sparse text) was a large, measured improvement over
  Tesseract's default `--psm 3` (92 spurious deltas -> 10) but doesn't close
  the gap to zero.
- **Chat qa-6 (paraphrase miss)**: *"What full description appears next to tag
  26-KA-902 on the base revision?"* shares zero content-tokens with its answer
  text ("3RD STAGE HP GAS EXPORT COMPRESSOR") — a real BM25/lexical-retrieval
  limitation, not something patched away, since doing so would mean tuning
  against my own eval set rather than fixing a general weakness. Named
  explicitly as the reason to add embedding-based retrieval next.
- **Citation-accuracy metric is stricter than it should be**: it checks literal
  keyword containment in the cited chunk, which under-scores correct answers
  that cite a precise but short source (e.g., citing the bare tag chunk
  `"57-9006"` for a question whose expected keyword is the full renumbering
  claim). A better version would check semantic support, not string
  containment — listed under "what's next."

## Web UI & documentation

```bash
make ui     # http://localhost:8000 — dashboard, chat, eval scorecard
make docs   # MkDocs site (mkdocs-material), served locally
```

**Web UI** (`src/webapp/`, FastAPI + server-rendered Jinja2 + hand-rolled
vanilla-SVG charts — no CDN/chart-library dependency, works offline):

- **Dashboard**: pick two PIDs, run the delta, see canonical-representation
  summary cards (pages/elements/tables/dimensions per doc), a changes-by-kind
  bar chart, a criticality donut, and the full delta table sorted red → yellow
  → green with signal chips per row — plus links to the Markdown/JSON report
  and a markup-PDF download.
- **Chat**: fetch-based UI over `/api/chat` — the same `answer_question()`
  call the CLI uses, citations shown as chips, model/tokens/cost per answer.
- **Eval**: a PASS/FAIL banner, F1/accuracy gauges, an OCR-accuracy/latency/
  token/cost stat row, a multi-run trend chart, and the candid chat failure
  table — reading real `eval/results/*.json`, with a "run new eval" button
  wired to the exact same scoring functions `make eval` uses (no separate UI
  scoring logic to drift out of sync). Verified live end-to-end: all routes
  return 200, chat returns real Groq-generated grounded answers with correct
  citations, and a live eval run produces a genuine PASS from real numbers
  (`tests/test_webapp.py`).
- **Infra status** (`/infra`): live reachability probes (not just "is it
  configured") against every backend this deployment points at — Mongo,
  Redis, Celery-via-Redis, Chroma/Pinecone. Any connection string shown here
  goes through `redact_uri()` first (see "Data & infrastructure").

Demo-scope simplification, stated plainly: ingested documents/deltas/indexes
are cached in an in-process dict keyed by `(pid_a, pid_b)` so page navigation
doesn't re-run OCR/alignment every request — a real deployment would back
this with a proper cache/store, not a process dict.

**Documentation site** (`docs/`, `mkdocs.yml`, mkdocs-material theme,
published at [bhaviknagre.github.io/DeltaIQ](https://bhaviknagre.github.io/DeltaIQ/)):
architecture (with request-flow diagrams), format support, delta engine +
criticality signal, grounded chat, data & infrastructure, Kubernetes &
Terraform deployment, observability, evaluation, the web UI, and an
[output reference](docs/output-reference.md) page documenting the exact
shape of every artifact this system produces — populated with real captured
output, not placeholder numbers.

## Sample data & provenance

`data/samples/raw/` holds two real, born-digital P&ID export sheets supplied
for this assignment (`export_gas_compressor.pdf`, `lift_gas_compressor.pdf`).
They're two *different* drawings, not two revisions of one drawing, so they
can't directly serve as a PID-A/PID-B pair — the assignment needs revisions of
the *same* document with a knowable delta. Per the assignment's own FAQ
("edit a PDF and re-export... document provenance"), two pairs were
synthesized from the real material:

- `data/samples/pair_native/` — `export_gas_compressor.pdf` duplicated as Rev
  A, then edited in place (PyMuPDF redact + re-insert at the same
  font/size/position) into Rev B with the 6 authored edits in
  `data/samples/ground_truth.json`.
- `data/samples/pair_scanned/` — both revisions of the above, rasterized to
  300dpi image-only PDFs (no text layer), simulating a scan/photograph of the
  same revision pair on identical ground truth.

Regenerate both with `make samples` (`python -m data.samples.build_synthetic_pairs`).

## What was cut, and why

- **Real `.dwg` binary parsing** — no license-free pure-Python reader exists;
  would need the ODA File Converter or Autodesk SDK as an external
  dependency/service. Built a real DXF adapter behind the identical interface
  instead, so the seam is proven even though the binary format isn't.
- **Hungarian/optimal bipartite alignment** — greedy scoring used instead;
  documented trade-off in `delta/align.py`, not a silent shortcut.
- **Multi-page/multi-sheet delta continuity** (e.g. tracking an element that
  moves from sheet 2 to sheet 3) — alignment is restricted to same-page
  matching; both sample documents are single-sheet, so this wasn't exercised.
- **LLM-as-judge for chat eval** — the assignment allows it "if validated";
  given no LLM key was available to build and validate a judge against, chat
  scoring uses a keyword+groundedness heuristic instead, with a documented
  limitation section above rather than an unvalidated judge presented as ground
  truth.
- **GCS blob-storage backend** — `terraform/storage.tf` provisions the GCS
  bucket, but `src/storage/blob_store.py` only implements local disk, MinIO,
  and MongoDB GridFS; a `GcsBlobStore` behind the same `BlobStore` interface
  is straightforward but not yet written.
- **Table-cell extraction** — `ElementType.TABLE_CELL` exists in the canonical
  model but no adapter currently detects tabular regions; neither sample
  document has a clear table region to validate against.
- **Kubernetes/Terraform actually deployed** — both are creation-only (see
  "Deployment"); genuinely runnable (`make check-k8s`, `terraform plan`), but
  neither has touched a live cluster or a real GCP project.

**Now built, previously listed here as cut**: embedding-based retrieval
(`RETRIEVAL_BACKEND=vector`/`hybrid`, `Embedder`/`VectorStore` interfaces —
still optional, BM25 stays the tag/code-dominated-corpus default) and
Prometheus/Grafana (`make infra-up` — see "Observability") — both landed in
v2.0.0. Agentic chat (`chat/agentic.py`, LangGraph retrieve → verify → retry,
`CHAT_BACKEND=agentic` — see "Agentic mode") landed alongside this.

## What's next with more time

1. Close the paraphrase-query gap the eval harness measures (qa-6) with a
   real semantic embedder (`OpenAIEmbedder` is already wired for this;
   `RETRIEVAL_BACKEND=vector`/`hybrid` just isn't the default yet), plus
   retrieval-quality metrics (MRR/recall@k) added to the scorecard.
2. A validated LLM-judge for chat correctness once a real key is available,
   cross-checked against the current heuristic scorer to see where they
   disagree.
3. Real `.dwg` support via an ODA File Converter pre-step (shell out to convert
   `.dwg` -> `.dxf`, then reuse the existing `DwgAdapter.parse()` unchanged).
4. Multi-page delta continuity (element tracked across sheets, not just within one).
5. A cost/latency budget analysis now that real LLM telemetry can be captured
   (currently $0 — no key was available to generate real numbers to analyze).
6. OCR quality: try layout-aware OCR (e.g. a vision-LLM pass) as a second
   ScannedPdfAdapter strategy and compare precision against Tesseract on the
   same ground truth, rather than assuming one wins.
7. `GcsBlobStore` to match the GCS bucket Terraform already provisions.
8. Actually apply the Terraform and deploy the Kubernetes manifests to a real
   GKE cluster, replacing `REPLACE_ME` secrets with real Secret Manager values.
9. Run the eval harness through the agentic pipeline too (currently
   `eval/run_eval.py` only exercises `chat/answer.py`), so citation-accuracy
   and groundedness scores can be compared simple-vs-agentic side by side
   instead of only spot-checked via `scripts/checks/check_chat.py`.

## Config

All thresholds, model choice, and paths are env-driven — see `.env.example`.
Nothing above is hardcoded at call sites; `src/config.py` is the single source.
