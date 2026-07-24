# Document Delta & Grounded Chat

Given two PIDs (revisions of the same engineering document), this system ingests
both regardless of format, computes a structured delta, renders a human- and
machine-readable delta report, and answers questions over both revisions and the
delta with citations.

## Quickstart

```bash
make setup     # venv + deps + checks for tesseract (brew install tesseract / apt-get install tesseract-ocr)
make samples   # synthesize the demo revision pairs (see "Sample data" below)
make run       # ingest -> delta -> report on the native-PDF pair (reproducible run)
make chat      # grounded chat REPL over that pair + its delta
make markup    # bonus: redline overlay PDF
make eval      # scorecard: delta P/R/F1 + chat correctness/groundedness/citation accuracy
make test      # unit + integration tests
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
  Satisfies "inspectable metrics" without standing up Prometheus/Grafana; those
  are named as future work if this needed to run continuously in prod.
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

**Latest scorecard** (mock LLM provider — no API key in this environment):

```
DELTA ENGINE SCORECARD
  [native]  precision=1.00 recall=1.00 f1=1.00  (TP=6 FN=0 FP=0)
  [scanned] precision=0.60 recall=1.00 f1=0.75  (TP=6 FN=0 FP=4)

CHAT SCORECARD
  accuracy=0.86  groundedness_rate=1.00  citation_accuracy=0.22
```

- **Delta P/R/F1**: matches predicted `DeltaItem`s to ground-truth edits by
  change-kind + text containment (robust across native line-granularity vs.
  OCR's coarser word-clustering), then precision/recall/F1 over matched vs.
  missed vs. spurious.
- **Chat accuracy**: keyword match in the answer AND `grounded=True` (or, for
  the adversarial question, a correct refusal).
- **Citation accuracy**: for correct, non-hedge answers, checks that cited
  chunks *actually contain* an expected keyword — verifies citations aren't
  just decorative. Low here (0.22) mostly because many correct answers cite
  short single-tag chunks that don't literally contain the full expected phrase
  even when they're the right source — noted as a metric-design limitation, see
  below.

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
- **Embedding-based retrieval** — BM25 chosen deliberately for a
  tag/code-dominated corpus (see "Grounded chat"); embeddings would help
  paraphrase queries (the qa-6 failure above) at the cost of needing an
  embedding API key and losing full offline determinism. Straightforward to
  add as a second retriever behind the same `RetrievalIndex.search` interface.
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
- **Served dashboard / Prometheus+Grafana** — `make metrics` (JSON reduction
  over trace files) chosen instead; sufficient for a single local run,
  explicitly insufficient for continuous production monitoring.
- **Table-cell extraction** — `ElementType.TABLE_CELL` exists in the canonical
  model but no adapter currently detects tabular regions; neither sample
  document has a clear table region to validate against.

## What's next with more time

1. Embedding-based (or hybrid BM25+embedding) retrieval to close the paraphrase
   gap found in eval, with retrieval-quality metrics (MRR/recall@k) added to
   the scorecard.
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

## Config

All thresholds, model choice, and paths are env-driven — see `.env.example`.
Nothing above is hardcoded at call sites; `src/config.py` is the single source.
