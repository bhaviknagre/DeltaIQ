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

from src.canonical.model import CanonicalDocument
from src.chat.answer import answer_question
from src.chat.index import RetrievalIndex, build_index
from src.config import settings
from src.delta.engine import DeltaResult, compute_delta
from src.delta.report import to_markdown
from src.ingest.pid_store import _load_manifest, load
from src.markup.overlay import render_markup
from src.observability.logging import get_logger
from src.observability.tracing import new_trace

logger = get_logger("webapp")

HERE = Path(__file__).resolve().parent
app = FastAPI(title="Document Delta & Grounded Chat")
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))

# Demo-scope in-memory cache: ingest+delta recomputation is cheap for a
# single-sheet sample but not something to redo on every page navigation.
# A real deployment would back this with a proper cache/store, not a process
# dict — documented as a scope simplification, not hidden.
_doc_cache: dict[str, CanonicalDocument] = {}
_delta_cache: dict[tuple[str, str], DeltaResult] = {}
_index_cache: dict[tuple[str, str], RetrievalIndex] = {}


def _get_doc(pid: str) -> CanonicalDocument:
    if pid not in _doc_cache:
        _doc_cache[pid] = load(pid)
    return _doc_cache[pid]


def _get_delta(pid_a: str, pid_b: str) -> DeltaResult:
    key = (pid_a, pid_b)
    if key not in _delta_cache:
        _delta_cache[key] = compute_delta(_get_doc(pid_a), _get_doc(pid_b))
    return _delta_cache[key]


def _get_index(pid_a: str, pid_b: str) -> RetrievalIndex:
    key = (pid_a, pid_b)
    if key not in _index_cache:
        _index_cache[key] = build_index(_get_doc(pid_a), _get_doc(pid_b), _get_delta(pid_a, pid_b))
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
    with new_trace(kind="ui_results", pid_a=pid_a, pid_b=pid_b):
        doc_a = _get_doc(pid_a)
        doc_b = _get_doc(pid_b)
        delta = _get_delta(pid_a, pid_b)

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
        pid_a = pid_a or "demo-native-a"
        pid_b = pid_b or "demo-native-b"
    return templates.TemplateResponse(request, "chat.html", {"pid_a": pid_a, "pid_b": pid_b, "pids": pids})


@app.post("/api/chat")
def api_chat(payload: dict):
    pid_a, pid_b, question = payload["pid_a"], payload["pid_b"], payload["question"]
    index = _get_index(pid_a, pid_b)
    with new_trace(kind="ui_chat", pid_a=pid_a, pid_b=pid_b, question=question) as trace:
        result = answer_question(question, index, trace)
    return JSONResponse(
        {
            "answer": result.answer,
            "grounded": result.grounded,
            "citations": result.citations_used,
            "model": result.model,
            "cost_usd": result.cost_usd,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "request_id": trace.request_id,
        }
    )


@app.get("/eval", response_class=HTMLResponse)
def eval_page(request: Request):
    results_dir = Path("eval/results")
    files = sorted(results_dir.glob("*.json")) if results_dir.exists() else []
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


@app.get("/api/pids")
def api_pids():
    return JSONResponse(_known_pids())
