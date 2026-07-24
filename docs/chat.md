# Grounded chat

## Retrieval (`src/chat/index.py`)

BM25 (`rank_bm25`) over three chunk sources: every element in PID A, every
element in PID B, and every delta-report item — each chunk carries a
`Citation` back to its exact source (`pid_a:<pid>@p<page>`, `pid_b:...`, or
`delta:<delta_item_id>`).

**Why BM25, not embeddings**: no API key required (works fully offline, fully
deterministic — good for reproducible eval), and P&ID content is dominated by
exact tags/codes/dimensions where lexical match is *more* reliable than
semantic similarity ("26-KA-902" should match "26-KA-902", not something
merely related to it). The real cost is paraphrase queries that don't share
vocabulary with the source text — see [Evaluation](eval.md#candid-failures).

Two retrieval-quality fixes, found empirically via the eval harness and kept
because they're generally correct, not because they were needed to pass one test:

- A small domain-aware stopword filter (plus dropping 1-character tokens) —
  without it, generic tokens like `"id"` (from "P&ID" tokenizing to `p`+`id`)
  spuriously matched everywhere.
- Retrieval requires **at least one real content-token overlap** between
  query and chunk as a hard gate, not just a relative score threshold — a
  same-query-relative-max normalization meant the single best-of-a-bad-bunch
  chunk always cleared the confidence floor.
- Delta-report chunks get a modest ranking boost, and exact-duplicate chunks
  are de-duplicated within the top-k window, so three identical tag-label
  chunks don't crowd out the one delta-report entry that actually answers a
  "what changed" question.

**Optional vector/hybrid retrieval**: `RETRIEVAL_BACKEND=vector` or `hybrid`
(default `bm25`) route through a configured `VectorStore` (Chroma or
Pinecone) instead of, or blended with (`HYBRID_BM25_WEIGHT`), BM25 — see
[Data & infrastructure](infrastructure.md#storage-backends-srcstorage). Still
opt-in: nothing about the grounding/refusal/citation behavior below changes
based on which retrieval backend is active.

## Grounding & refusal (`src/chat/answer.py`)

If retrieval finds nothing with real lexical overlap, the LLM is **never
called** — the system hedges directly:
`"I don't have grounded evidence to answer that."`

When the LLM is called, the system prompt requires every claim to end with the
exact bracketed citation label it came from. The response is parsed for those
citations; an answer is only flagged `grounded=True` if it actually contains
at least one real citation.

A failed provider call (network error, rate limit, exhausted quota) degrades
to a single non-grounded answer instead of crashing the whole request — found
live when a valid-but-unbilled OpenAI key returned `insufficient_quota` and
took down the CLI process before this boundary existed.

## LLM providers (`src/chat/llm.py`)

One `LLMProvider` interface, four implementations:

| Provider | Notes |
|---|---|
| `AnthropicProvider` | `ANTHROPIC_API_KEY` |
| `OpenAIProvider` | `OPENAI_API_KEY` |
| `GroqProvider` | **Free option** — `GROQ_API_KEY`, no credit card required (console.groq.com/keys). It's literally `OpenAIProvider` pointed at Groq's OpenAI-compatible endpoint with a free open model (`llama-3.3-70b-versatile`) — no separate integration code. |
| `MockProvider` | Used automatically when no key is configured. Not a fake generative model — extracts and lists the retrieved, cited context verbatim, clearly labeled `[MOCK LLM]`, so `make eval` / `make chat` stay honestly runnable offline. |

Switching providers is a `.env` change (`LLM_PROVIDER` + the matching key),
never a code change.

## Example

```
$ python -m src.cli chat 26-9026-REV-A 26-9026-REV-B -q "What changed with tag 26-KA-902?"

The tag '26-KA-902' was changed and moved to '26-KA-902B' and was moved 5.6pt
[delta:mod-768f8edcbb84-ebfbd0945c2c].

(grounded=True, citations=1, model=llama-3.3-70b-versatile, cost=$0.000000)
```
