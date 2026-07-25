"""Minimal web UI: FastAPI + server-rendered Jinja2 templates + hand-rolled
SVG charts (static/charts.js, no CDN dependency — keeps the whole thing
self-contained and usable offline). Not the system of record: it's a thin
view over the same src/cli.py-equivalent calls (ingest -> delta -> report,
chat, eval), so nothing here duplicates business logic.

Run: make ui  (uvicorn src.webapp.app:app --reload --port 8000)
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import make_asgi_app

from src._version import __version__
from src.canonical.model import CanonicalDocument
from src.chat.agentic import answer_question_agentic
from src.chat.answer import answer_question
from src.chat.vector_index import build_retriever
from src.config import redact_uri, settings
from src.delta.engine import DeltaResult, compute_delta
from src.delta.report import to_markdown
from src.ingest.pid_store import _load_manifest, load
from src.markup.overlay import render_markup
from src.observability.logging import get_logger
from src.observability.tracing import new_trace
from src.webapp.middleware import RequestContextMiddleware
from src.webapp.schemas import ChatRequest, ChatResponse, VersionResponse

logger = get_logger("webapp")

HERE = Path(__file__).resolve().parent
app = FastAPI(title="DeltaIQ", version=__version__)
app.add_middleware(RequestContextMiddleware)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
# Prometheus scrape target — see prometheus/prometheus.yml + grafana/ for the dashboard
# that reads these exact deltachat_* metric names (observability/prometheus_metrics.py).
app.mount("/metrics", make_asgi_app())
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.globals["app_version"] = __version__

# Demo-scope in-memory cache: ingest+delta recomputation is cheap for a
# single-sheet sample but not something to redo on every page navigation.
# A real deployment would back this with a proper cache/store, not a process
# dict — documented as a scope simplification, not hidden.
_doc_cache: dict[str, CanonicalDocument] = {}
_delta_cache: dict[tuple[str, str], DeltaResult] = {}
_index_cache: dict[tuple[str, str], object] = {}  # whichever retriever RETRIEVAL_BACKEND selects


def _get_doc(pid: str) -> CanonicalDocument:
    if pid not in _doc_cache:
        _doc_cache[pid] = load(pid)
    return _doc_cache[pid]


def _get_delta(pid_a: str, pid_b: str) -> DeltaResult:
    key = (pid_a, pid_b)
    if key not in _delta_cache:
        _delta_cache[key] = compute_delta(_get_doc(pid_a), _get_doc(pid_b))
    return _delta_cache[key]


def _get_index(pid_a: str, pid_b: str):
    key = (pid_a, pid_b)
    if key not in _index_cache:
        _index_cache[key] = build_retriever(_get_doc(pid_a), _get_doc(pid_b), _get_delta(pid_a, pid_b))
    return _index_cache[key]


def _known_pids() -> list[dict]:
    manifest = _load_manifest()
    return [{"pid": pid, **meta} for pid, meta in sorted(manifest.items())]


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"pids": _known_pids()})


@app.post("/run")
def run(pid_a: str = Form(...), pid_b: str = Form(...)):
    _get_delta(pid_a, pid_b)  # populate cache; failures surface as a 500 with traceback (see below)
    return RedirectResponse(url=f"/results?pid_a={pid_a}&pid_b={pid_b}", status_code=303)


@app.get("/results", response_class=HTMLResponse)
def results(request: Request, pid_a: str, pid_b: str):
    with new_trace(kind="ui_results", pid_a=pid_a, pid_b=pid_b) as trace:
        with trace.span("ingest_a", pid=pid_a):
            doc_a = _get_doc(pid_a)
        with trace.span("ingest_b", pid=pid_b):
            doc_b = _get_doc(pid_b)
        with trace.span("delta") as span:
            delta = _get_delta(pid_a, pid_b)
            span.attrs["total_changes"] = len(delta.items)

    items = sorted(delta.items, key=lambda it: {"red": 0, "yellow": 1, "green": 2}[it.criticality.value])

    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "pid_a": pid_a,
            "pid_b": pid_b,
            "summary_a": doc_a.summary(),
            "summary_b": doc_b.summary(),
            "delta": delta,
            "items": items,
            "counts_by_kind": delta.counts_by_kind(),
            "counts_by_criticality": delta.counts_by_criticality(),
            "avg_confidence": delta.avg_confidence(),
            "chart_kind_json": json.dumps(delta.counts_by_kind()),
            "chart_crit_json": json.dumps(delta.counts_by_criticality()),
        },
    )


@app.get("/report/markdown", response_class=HTMLResponse)
def report_markdown(pid_a: str, pid_b: str):
    delta = _get_delta(pid_a, pid_b)
    md = to_markdown(delta, pid_a, pid_b)
    return HTMLResponse(f"<pre style='white-space:pre-wrap;font-family:ui-monospace,monospace;padding:24px'>{md}</pre>")


@app.get("/report/json")
def report_json(pid_a: str, pid_b: str):
    delta = _get_delta(pid_a, pid_b)
    return JSONResponse(json.loads(delta.model_dump_json()))


@app.get("/markup/download")
def markup_download(pid_a: str, pid_b: str):
    delta = _get_delta(pid_a, pid_b)
    b_path = Path(_load_manifest()[pid_b]["path"])
    out_path = Path("output") / "webapp" / f"markup_{pid_a}_{pid_b}.pdf"
    render_markup(b_path, delta, out_path)
    return FileResponse(out_path, media_type="application/pdf", filename=out_path.name)


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request, pid_a: str | None = None, pid_b: str | None = None):
    pids = _known_pids()
    if not pid_a or not pid_b:
        pid_a = pid_a or "26-9026-REV-A"
        pid_b = pid_b or "26-9026-REV-B"
    return templates.TemplateResponse(request, "chat.html", {"pid_a": pid_a, "pid_b": pid_b, "pids": pids})


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(payload: ChatRequest) -> ChatResponse:
    import uuid

    session_id = payload.session_id or str(uuid.uuid4())
    index = _get_index(payload.pid_a, payload.pid_b)
    use_agentic = settings.chat_backend == "agentic" if payload.agentic is None else payload.agentic
    with new_trace(
        kind="ui_chat", pid_a=payload.pid_a, pid_b=payload.pid_b, question=payload.question,
        session_id=session_id, agentic=use_agentic,
    ) as trace:
        if use_agentic:
            result = answer_question_agentic(payload.question, index, trace)
        else:
            result = answer_question(payload.question, index, trace)

    from src.storage.session_store import get_session_store

    get_session_store().append_turn(
        session_id, payload.question, result.answer, pid_a=payload.pid_a, pid_b=payload.pid_b,
        grounded=result.grounded, model=result.model, request_id=trace.request_id,
    )

    return ChatResponse(
        answer=result.answer,
        grounded=result.grounded,
        citations=result.citations_used,
        model=result.model,
        cost_usd=result.cost_usd,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        request_id=trace.request_id,
        session_id=session_id,
        verified=getattr(result, "verified", None),
        attempts=getattr(result, "attempts", None),
    )


@app.get("/api/chat/session/{session_id}")
def api_chat_session(session_id: str):
    from src.storage.session_store import get_session_store

    return JSONResponse(get_session_store().get_history(session_id))


@app.get("/eval", response_class=HTMLResponse)
def eval_page(request: Request):
    results_dir = Path("eval/results")
    # latest_metrics.json is the flat DVC-metrics summary (dvc.yaml), not a
    # timestamped scorecard — excluded here or every history/diff read below
    # breaks on its different schema (no "timestamp"/"delta"/"chat" keys).
    files = sorted(f for f in results_dir.glob("*.json") if f.name != "latest_metrics.json") if results_dir.exists() else []
    latest = json.loads(files[-1].read_text()) if files else None
    history = [json.loads(f.read_text()) for f in files[-10:]] if files else []
    return templates.TemplateResponse(
        request,
        "eval.html",
        {
            "latest": latest,
            "history_json": json.dumps(
                [{"ts": h["timestamp"], "native_f1": h["delta"].get("native", {}).get("f1"),
                  "scanned_f1": h["delta"].get("scanned", {}).get("f1"), "chat_acc": h["chat"]["accuracy"]}
                 for h in history]
            ),
        },
    )


@app.post("/eval/run")
def eval_run():
    from eval.run_eval import compute_pass_fail, run_chat_eval, run_delta_eval, save_and_diff

    delta_results = run_delta_eval()
    chat_results = run_chat_eval()
    passed, _ = compute_pass_fail(delta_results, chat_results)
    save_and_diff(delta_results, chat_results, passed)
    return RedirectResponse(url="/eval", status_code=303)


def _check_backend(name: str, configured: bool, probe) -> dict:
    """Runs a real, short-timeout live probe against a backend — not just
    "is this configured," but "is it actually reachable right now." Every
    probe is wrapped so one hung/broken backend can't take the whole
    /infra page down."""
    if not configured:
        return {"name": name, "status": "not_configured"}
    try:
        detail = probe()
        return {"name": name, "status": "up", "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "status": "down", "detail": f"{type(exc).__name__}: {exc}"}


@app.get("/infra", response_class=HTMLResponse)
def infra_status(request: Request):
    def check_mongo():
        import pymongo

        pymongo.MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=1500).admin.command("ping")
        return redact_uri(settings.mongodb_uri)

    def check_redis():
        import redis

        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1.5).ping()
        return redact_uri(settings.redis_url)

    def check_minio():
        from minio import Minio

        client = Minio(
            settings.minio_endpoint, access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key, secure=settings.minio_secure,
        )
        client.bucket_exists(settings.minio_bucket)
        return settings.minio_endpoint

    def check_chroma():
        from src.storage.vector_store import ChromaVectorStore

        ChromaVectorStore()
        return settings.chroma_host or f"embedded @ {settings.chroma_persist_dir}"

    def check_pinecone():
        from pinecone import Pinecone

        Pinecone(api_key=settings.pinecone_api_key).list_indexes()
        return settings.pinecone_index_name

    def check_celery():
        from src.tasks.celery_app import celery_app

        conn = celery_app.connection()
        conn.ensure_connection(max_retries=1, timeout=1.5)
        conn.release()
        return redact_uri(settings.redis_url)

    def check_langfuse():
        from src.observability.langfuse_tracing import get_langfuse_client

        client = get_langfuse_client()
        assert client is not None
        return settings.langfuse_host

    backends = [
        _check_backend("MongoDB (metadata store)", settings.metadata_store == "mongo", check_mongo),
        _check_backend("Redis (chat cache + Celery broker)", True, check_redis),
        _check_backend("MinIO (blob store)", settings.blob_store == "minio", check_minio),
        _check_backend(
            "Chroma (vector store)",
            settings.retrieval_backend in ("vector", "hybrid") and settings.vector_store == "chroma",
            check_chroma,
        ),
        _check_backend(
            "Pinecone (vector store)",
            settings.retrieval_backend in ("vector", "hybrid") and settings.vector_store == "pinecone",
            check_pinecone,
        ),
        _check_backend("Celery (background tasks)", True, check_celery),
        _check_backend("Langfuse (LLM observability)", bool(settings.langfuse_public_key), check_langfuse),
    ]

    config = {
        "LLM_PROVIDER": settings.llm_provider,
        "RETRIEVAL_BACKEND": settings.retrieval_backend,
        "METADATA_STORE": settings.metadata_store,
        "BLOB_STORE": settings.blob_store,
        "VECTOR_STORE": settings.vector_store,
    }

    links = [
        {"name": "Grafana", "url": "http://localhost:3000"},
        {"name": "Prometheus", "url": "http://localhost:9090"},
        {"name": "Flower (Celery)", "url": "http://localhost:5555"},
        {"name": "MinIO console", "url": "http://localhost:9001"},
        {"name": "Raw metrics", "url": "/metrics"},
    ]

    return templates.TemplateResponse(request, "infra.html", {"backends": backends, "config": config, "links": links})


@app.get("/api/pids")
def api_pids():
    return JSONResponse(_known_pids())


@app.get("/api/version", response_model=VersionResponse)
def api_version() -> VersionResponse:
    return VersionResponse(version=__version__)
