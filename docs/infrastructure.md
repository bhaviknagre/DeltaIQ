# Data & infrastructure

Every production backend in this section is **opt-in**: the system runs
end-to-end with zero infrastructure (a JSON manifest, local disk, and BM25)
by default. Setting the matching `.env` variable swaps in a real backend
behind the same interface — nothing downstream changes.

## Storage backends (`src/storage/`)

Three interfaces, each with a zero-infra default and a real-backend option.
Every real backend falls back to its zero-infra default (with a logged
warning) if it can't connect at construction time — a misconfigured or
unreachable service degrades the system, it doesn't crash it.

| Interface | Default (zero-infra) | Real backend(s) | Selected via |
|---|---|---|---|
| `MetadataStore` (`metadata_store.py`) | `JsonFileMetadataStore` — `data/pid_store/pids.json` + sibling caches | `MongoMetadataStore` — 6 collections: `pids`, `canonical_documents`, `delta_results`, `chat_sessions`, `processing_jobs`, `eval_runs` | `METADATA_STORE=json\|mongo` |
| `BlobStore` (`blob_store.py`) | `LocalDiskBlobStore` — SHA1-hashed files under `data/blobs/` | `MinioBlobStore` (S3-compatible), `MongoGridFSBlobStore` (GridFS) | `BLOB_STORE=local\|minio\|mongo_gridfs` |
| `VectorStore` (`vector_store.py`) | `NullVectorStore` (BM25-only, no vectors) | `ChromaVectorStore` (embedded or `CHROMA_HOST` server), `PineconeVectorStore` (serverless index, auto-created) | `VECTOR_STORE=none\|chroma\|pinecone` |

`ChatSessionStore` (`session_store.py`) is a Redis-backed, 6-hour TTL hot
cache over `MetadataStore` (cache-aside), falling back to an in-memory dict
if Redis is unreachable.

**Retrieval backend**: independent of the vector store choice,
`RETRIEVAL_BACKEND=bm25|vector|hybrid` picks whether chat retrieval uses BM25
alone (default), the configured vector store alone, or a weighted blend
(`HYBRID_BM25_WEIGHT`). See [Grounded chat](chat.md) for why BM25 is the
default for this content, and when the vector/hybrid path is worth it.

## Background jobs (`src/tasks/`)

Celery, with Redis as both broker and result backend
(`celery_app.py`: `Celery("delta_chat", broker=settings.redis_url, backend=settings.redis_url)`).
Three tasks (`jobs.py`), each wrapping existing synchronous logic unchanged
and mirroring lifecycle (`queued → running → success/failure`) into
`MetadataStore.processing_jobs`:

- `ingest_and_delta_task` — OCR ingestion is the slow path (~6s); a request
  dispatches the task and polls rather than blocking.
- `render_markup_task` — the redline overlay PDF.
- `run_eval_task` — a full eval run (~30s+).

`CELERY_TASK_ALWAYS_EAGER=true` runs tasks synchronously in-process — used
by the check scripts and tests so nothing requires a live worker. In normal
operation, background work is optional/async: nothing in the main request
path blocks on a worker being up.

```bash
make worker   # celery -A src.tasks.celery_app worker --concurrency=2
make flower   # Flower dashboard at :5555 — task inspection/monitoring
```

## Running the real stack locally

```bash
make infra-up    # docker compose --profile full up -d
# mongo:27017  redis:6379  minio:9000 (console :9001)  chroma:8100  prometheus:9090  grafana:3000
make infra-down
make infra-logs
```

`docker-compose.yml` profiles:

| Profile | Services |
|---|---|
| *(default)* | `delta-chat` — one-shot reproducible CLI run |
| `chat` | interactive CLI chat REPL |
| `eval` | eval harness |
| `ui` | FastAPI web UI at `:8000` |
| `full` | `mongo`, `redis`, `minio`, `chroma`, `prometheus`, `grafana` |
| `worker` | `celery-worker`, `flower` (`:5555`) |

## LLM observability (Langfuse)

`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` — no-op if
unset. When configured, LLM calls in `chat/answer.py` are additionally traced
to Langfuse; the homegrown tracer (see [Observability](observability.md))
keeps running regardless, so this is a supplement, not a replacement.

## DVC pipeline (`dvc.yaml`)

Two stages, reproducible via `dvc repro` (only re-runs a stage whose deps or
tracked params actually changed):

1. **`samples`** — `python -m data.samples.build_synthetic_pairs`; deps on
   `data/samples/raw/` and the build script; outputs the native/scanned pairs
   and `ground_truth.json`.
2. **`eval`** — `python -m eval.run_eval`; deps on the sample pairs plus
   `eval/`, `src/delta`, `src/chat`; tracked params from `params.yaml`
   (`delta.fuzzy_match_threshold`, `delta.spatial_match_max_dist`,
   `delta.modified_text_threshold`, `retrieval.top_k`, `retrieval.min_score`);
   metric output `eval/results/latest_metrics.json`.

```bash
make dvc-repro    # dvc repro
make dvc-dag      # dvc dag
make dvc-metrics  # dvc metrics show
```

The configured remote (`.dvc/config`, `core.remote = localstorage`) is a
local-filesystem remote at `.dvc-local-remote/` — a real DVC remote, just not
a cloud one, matching this project's "opt-in infra, nothing required to run"
posture. Swapping in S3/GCS is a one-line remote config change, not a
pipeline change.

## Credential handling

`settings.mongodb_uri` and `settings.redis_url` can carry a password
(`mongodb+srv://user:pass@...`). Every place that logs or displays either —
`blob_store.py`, `metadata_store.py`, `session_store.py`, and the `/infra`
web UI page — passes it through `src/config.py::redact_uri()` first, which
strips `user:pass@` down to `***:***@` before it's ever written to a log line
or rendered to a browser. Regression-tested in
`tests/test_config_redact_uri.py` against synthetic fixture credentials, not
real ones — see that file's docstring for why a secret-redaction test is
exactly the wrong place to hardcode a real secret.
