# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

The single source of truth for the current version is `src/_version.py`;
`python -m src.cli --version`, the web UI footer, and `GET /api/version` all
read from it. Every release here has a matching annotated git tag.

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
