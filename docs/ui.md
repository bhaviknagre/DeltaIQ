# Web UI

A minimal FastAPI + server-rendered UI (`src/webapp/`) — not the system of
record; every route is a thin view over the same ingest → delta → chat → eval
calls the CLI makes. Charts are hand-rolled vanilla SVG
(`static/charts.js`), so the whole UI has zero external/CDN dependencies and
works offline.

```bash
make ui   # http://localhost:8000
```

## Dashboard (`/`, `/results`)

Pick two registered PIDs, run the delta, and see:

- **Canonical representation** summary cards per document — pages, elements,
  tables, dimensions, tags, notes (`CanonicalDocument.summary()`). Tables
  honestly show `0` — no adapter currently detects tabular regions, and the
  UI says so rather than hiding it.
- A **changes-by-kind** bar chart (added / removed / modified).
- A **criticality donut** — the same 🔴/🟡/🟢 signal from the delta engine
  (see [Delta engine & criticality](delta-engine.md)), plus average
  confidence and unchanged-element count.
- The full delta table, each row tagged with its criticality chip, sorted
  red → yellow → green so the changes that matter most surface first.
- Links to the Markdown/JSON report, a **markup PDF download** (the redline
  overlay, bonus capability), and a shortcut into chat scoped to this pair.

## Chat (`/chat`)

A fetch-based chat UI hitting `POST /api/chat` — same `answer_question()`
call the CLI uses. Each answer shows citation chips, the model used, token
counts, and cost, so grounding is visible in the UI, not just in logs.

## Eval (`/eval`)

- A **PASS/FAIL banner** driven by the same thresholds as `make eval`.
- Gauges for delta F1 (native + scanned) and chat accuracy, color-coded
  green/yellow/red by value.
- Stat tiles for OCR accuracy, average latency, tokens used, and estimated
  cost — all real numbers from the underlying `eval/results/*.json`.
- A multi-run **trend chart** (native F1 / scanned F1 / chat accuracy over
  the last 10 runs), so a regression is visible, not just asserted.
- The candid chat failure table, unchanged from the CLI scorecard.
- A **"Run new eval"** button that calls the exact same
  `run_delta_eval()` / `run_chat_eval()` functions `make eval` does — the UI
  never has its own separate scoring logic to drift out of sync.

## Design notes

- **In-memory caching**: `src/webapp/app.py` caches ingested documents,
  computed deltas, and retrieval indexes per `(pid_a, pid_b)` in a process
  dict, so navigating between pages doesn't re-run OCR/alignment every time.
  Documented as a demo-scope simplification — a real deployment would back
  this with a proper cache/store.
- **Server-rendered, not a JS framework**: Jinja2 templates + a handful of
  small vanilla-JS files (`charts.js`, `chat.js`). Kept intentionally simple
  so the whole UI stays inspectable and dependency-free.
