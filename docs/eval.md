# Evaluation

`make eval` runs `eval/run_eval.py` and prints a scorecard, then saves a
timestamped result under `eval/results/` and diffs it against the previous
run — so a change can be shown to help or hurt, not just asserted to.

## Ground truth

**Delta**: `data/samples/build_synthetic_pairs.py` produces Rev B from a real
source P&ID by applying 6 *exactly known* edits (2 tag renumbers, 1 dimension
change, 1 removed callout, 1 added tag, 1 added note) via PyMuPDF
redact+reinsert. Because the edits are authored, not guessed, ground truth is
exact. The same 6 edits are scored on both the native-PDF pair and a
rasterized scanned-PDF pair built from it, so the OCR path is scored against
identical ground truth.

**Chat**: `eval/datasets/qa_pairs.json` — 7 hand-written questions over the
native pair: 6 grounded content/change questions with expected keywords, plus
1 deliberately adversarial/off-topic question
(`"What color is the sky drawn in this P&ID?"`) that should trigger a
refusal, not a hallucinated answer.

## Latest scorecard

Real numbers, real LLM (Groq `llama-3.3-70b-versatile`, $0 cost, free tier):

```
Document Pair    : native
Precision        : 1.00    Recall : 1.00    F1 Score : 1.00
Avg Confidence   : 0.96
Criticality      : 🔴 1  🟡 3  🟢 2

Document Pair    : scanned
Precision        : 0.60    Recall : 1.00    F1 Score : 0.75
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

PASS
```

- **Delta P/R/F1**: matches predicted `DeltaItem`s to ground-truth edits by
  change-kind + text containment (robust across native line-granularity vs.
  OCR's coarser word-clustering).
- **OCR accuracy**: a *real*, computed word-level overlap between the OCR
  adapter's output and the native adapter's output on the same underlying
  document (`eval/metrics.py::score_ocr_accuracy`) — not a placeholder.
- **PASS/FAIL**: thresholds in `eval/run_eval.py::PASS_THRESHOLDS`
  (delta F1, chat accuracy, groundedness all ≥ 0.75) — a judgment call
  documented in code, chosen to allow the known OCR/BM25 gaps below without
  masking a real regression.

## Candid failures

- **Scanned-PDF precision (0.60)**: 4 of 10 predicted changes on the OCR path
  are noise — stray glyph misreads and one wrapping difference on a long
  boilerplate line. Recall is perfect; precision is the honest cost of OCR on
  a dense technical drawing. `--psm 11` was a large, measured improvement
  over Tesseract's default (92 spurious deltas → 10) but doesn't close the
  gap to zero.
- **Chat qa-6 (paraphrase miss)**: *"What full description appears next to
  tag 26-KA-902 on the base revision?"* shares zero content-tokens with its
  answer text ("3RD STAGE HP GAS EXPORT COMPRESSOR") — a real BM25/lexical-
  retrieval limitation, left unfixed on purpose rather than tuned away
  against this specific test.
- **Groundedness dropped when the mock provider was replaced with a real
  LLM** (1.00 → 0.83): the mock always echoed whatever was retrieved as if
  grounded; Groq correctly *refuses* on qa-6's retrieval gap per the system
  prompt's explicit hedge instruction. The eval harness catching its own
  earlier optimism bias is a feature, not a regression.
- **Citation-accuracy metric (0.60) is stricter than it should be**: it
  checks literal keyword containment in the cited chunk, which under-scores
  correct answers that cite a precise but short source. A better version
  would check semantic support, not string containment.

## Running it

```bash
make eval
```
