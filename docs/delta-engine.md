# Delta engine & criticality

## Alignment is the hard part

There's no stable cross-revision ID for a text run in a re-exported PDF/DXF,
so `src/delta/align.py` infers correspondence between PID A and PID B in three
passes:

1. **Exact match** — identical text at (near-)identical position, same page → unchanged.
2. **Greedy best-score match** on what's left — score = 0.65 × text similarity
   (rapidfuzz) + 0.35 × spatial proximity (bbox-center distance), restricted
   to the same page. A deliberate trade-off over an optimal (Hungarian)
   bipartite match: P&ID sheets have hundreds of small elements, and greedy
   converges to the same alignment as optimal matching in practice for
   well-separated content — simpler to reason about and debug.
3. Anything left unmatched in A is a **removal** candidate; unmatched in B is
   an **addition** candidate.

## Classification & confidence

Matched pairs are classified (`src/delta/engine.py`) as **modified** (text
changed and/or moved beyond a small tolerance) or dropped as unchanged. Every
`DeltaItem` carries:

- a **type** (`ElementType`: tag / dimension / note / text / table_cell / geometry)
- a **location** (page + bounding box)
- **before/after text**
- a **confidence** score — blended match score × extraction confidence, so a
  low-confidence OCR match propagates a lower delta confidence, not a false `1.0`
- a **criticality** signal (below)

**Determinism**: the whole engine — alignment, classification, confidence — is
pure Python/regex/rapidfuzz, zero LLM calls. Same input → byte-identical
output, every time. LLM non-determinism is isolated entirely to the chat-answer layer.

Element classification into tag/dimension/note/text (`src/ingest/classify.py`)
is deterministic regex, not an LLM call — P&ID tag codes, pipe specs, and
numbered notes follow regular enough patterns that regex is free, instant, and
exactly as accurate as an LLM would be here.

## Criticality: the red/yellow/green signal

Confidence and criticality answer different questions:

- **Confidence** — *how certain* is the engine that this change was detected/matched correctly?
- **Criticality** (`src/delta/criticality.py`) — *how much does this change matter*, engineering-wise, independent of that certainty?

A confidently-detected note addition is still low criticality; a line-size
change is high criticality even if alignment only matched it at 0.7 confidence.

| Signal | Rule |
|---|---|
| 🔴 **Red** | A dimension (line size / pressure / temp spec / tolerance) was modified or removed, or a tag was removed entirely. Historically the class of change that gets missed in manual review and causes rework or mis-fabrication. |
| 🟡 **Yellow** | A tag was modified/added, a dimension was added, or a note/text item was removed. Worth a reviewer's attention, not spec-level on its own. |
| 🟢 **Green** | Everything else: added/modified notes or generic text, added geometry/table cells, moved-only changes. Informational. |

This is a heuristic classifier, not a physics-aware severity model — it
reacts to *what kind* of thing changed, not *by how much* (it doesn't parse
`3/4" -> 1"` and reason about the magnitude of that increase). A
magnitude-aware version is named as explicit future work, not hidden.

The signal is surfaced in the [delta report](output-reference.md), the
[markup overlay](ui.md) (boxes colored by criticality, not just change kind),
and the [web UI](ui.md) dashboard.

## Delta report

`src/delta/report.py` renders the same `DeltaResult` as both Markdown (with
per-item 🔴/🟡/🟢 signals, grouped Added/Removed/Modified sections, and a
per-sheet location view) and JSON — the JSON is what the eval harness and any
downstream tooling consume; the Markdown is also indexed as a first-class,
citable source for chat (see [Grounded chat](chat.md)).
