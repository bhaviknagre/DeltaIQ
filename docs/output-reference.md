# Output reference

!!! note "On the numbers below"
    Every JSON/output block on this page is **real output from this system**,
    captured from `26-9026-REV-A` / `26-9026-REV-B` (a synthesized Rev A → Rev
    B of a real supplied P&ID — see `data/samples/build_synthetic_pairs.py`).
    They are not placeholder or hypothetical numbers. Where a field is
    honestly `0` or lower than you might expect (e.g. `tables: 0`, OCR
    accuracy 87% not 99%), that's a documented, known gap — see each page's
    "candid failures" section — not an oversight in this reference.

## 1. Canonical representation

`CanonicalDocument.summary()` — same shape for every format adapter:

```json
{
  "pid": "26-9026-REV-A",
  "format": "pdf_native",
  "revision_label": "Rev A",
  "pages": 1,
  "elements": 695,
  "tags": 56,
  "dimensions": 108,
  "notes": 58,
  "tables": 0,
  "text": 473,
  "geometry": 0
}
```

`tables: 0` — `ElementType.TABLE_CELL` exists in the canonical model but no
current adapter detects tabular regions; neither sample document has a clear
table region to validate against (documented cut, not a bug).

## 2. Structured delta

`DeltaResult.counts_by_kind()` + `avg_confidence()`:

```json
{
  "added": 2,
  "removed": 1,
  "modified": 3,
  "confidence": 0.961
}
```

Plus the criticality breakdown that isn't in a generic delta summary but is
core to this system:

```json
{ "red": 1, "yellow": 3, "green": 2 }
```

## 3. Delta report (Markdown + JSON)

```markdown
## Added
- 🟡 **[YELLOW] [ADDED] [tag]** `add-761de8b05f02` — New tag added: '26-PSV-9099' (confidence: 1.00)
- 🟢 **[GREEN] [ADDED] [note]** `add-09de55de4eb3` — New note added: 'NOTE 99 ADDED PSV PER MOC-1042.' (confidence: 1.00)

## Removed
- 🟡 **[YELLOW] [REMOVED] [text]** `rem-2f812c6ac76f` — Text removed: 'TO CLOSED DRAIN' (confidence: 1.00)

## Modified
- 🟡 **[YELLOW] [MODIFIED] [tag]** `mod-768f8edcbb84-ebfbd0945c2c` — Changed and moved: '26-KA-902' -> '26-KA-902B' (moved 5.6pt) (confidence: 0.93)
- 🟢 **[GREEN] [MODIFIED] [text]** `mod-16b01b4b47f9-a9b591f7c23f` — Text changed: '57-9005' -> '57-9006' (confidence: 0.90)
- 🔴 **[RED] [MODIFIED] [dimension]** `mod-a357c3582f16-fa7eac266fa4` — Text changed: '3/4"-DC-26-9026-FC11S-00' -> '1"-DC-26-9026-FC11S-00' (confidence: 0.93)
```

The JSON form (`/report/json` or `output/native/delta_report.json`) is the
full `DeltaResult` — every field above plus page index, bounding box, and
match method per item.

## 4. Chat output

```
$ python -m src.cli chat 26-9026-REV-A 26-9026-REV-B \
    -q "What changed with tag 26-KA-902, and was anything removed near the closed drain?"

The tag '26-KA-902' was changed to '26-KA-902B' [delta:mod-768f8edcbb84-ebfbd0945c2c].
The callout 'TO CLOSED DRAIN' was removed [delta:rem-2f812c6ac76f].

(grounded=True, citations=2, model=llama-3.3-70b-versatile, cost=$0.000000)
```

Citations resolve to either a delta-report entry (`delta:<id>`) or a specific
PID + page (`pid_a:<pid>@p<page>` / `pid_b:...`) — never a bare, unsourced claim.

## 5. Evaluation scorecard

```
============================================================
Evaluation Results
============================================================

Document Pair    : native
Precision        : 1.00
Recall           : 1.00
F1 Score         : 1.00
Avg Confidence   : 0.96
Criticality      : 🔴 1  🟡 3  🟢 2

Document Pair    : scanned
Precision        : 0.60
Recall           : 1.00
F1 Score         : 0.75
Avg Confidence   : 0.73
Criticality      : 🔴 1  🟡 3  🟢 6
OCR Accuracy     : 87.0%

Chat Correctness : 0.86
Groundedness     : 0.83
Citation Accuracy: 0.60
Model            : llama-3.3-70b-versatile
Latency          : 0.41 sec/question (avg)
Tokens Used      : 2,687
Estimated Cost   : $0.0000

============================================================
PASS
============================================================
```

Full breakdown and the honest "why" behind each number in
[Evaluation](eval.md#candid-failures).
