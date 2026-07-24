"""Background tasks. Each wraps existing synchronous application logic
unchanged (ingest/pid_store, delta/engine, eval/run_eval) — Celery is a
dispatch mechanism here, not a place business logic gets duplicated or
reimplemented.

Real use case for each, not task queues for their own sake:
  - ingest_and_delta_task: scanned-PDF OCR ingestion measured at ~6s for one
    page; a web request blocking on that (x2 documents) is a bad experience
    that only gets worse with more pages/documents. Dispatch it, poll/return
    a task id, let the client check back.
  - run_eval_task: a full eval run with a real LLM took ~30s in this
    project's own testing (7 chat questions + delta on 2 pairs). Same
    "don't block a web request" reasoning, at a larger scale.
  - render_markup_task: cheap today (<0.1s) but scales with document/page
    count; included for the same reason and consistency.

Every task's lifecycle (queued -> running -> success/failure) is mirrored
into the metadata store's processing_jobs record (MongoDB in production),
independent of Celery's own Redis result backend — the result backend has a
TTL and is meant for polling a task you just dispatched, not "what ran last
Tuesday," which processing_jobs answers instead.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.tasks.celery_app import celery_app


def _job_started(job_id: str, kind: str, **params) -> None:
    from src.storage.metadata_store import get_metadata_store

    get_metadata_store().save_processing_job(
        job_id, {"kind": kind, "status": "running", "params": params, "started_at": datetime.now(timezone.utc)}
    )


def _job_finished(job_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
    from src.storage.metadata_store import get_metadata_store

    get_metadata_store().update_processing_job(
        job_id, {"status": status, "result": result, "error": error, "finished_at": datetime.now(timezone.utc)}
    )


@celery_app.task(name="tasks.ingest_and_delta", bind=True)
def ingest_and_delta_task(self, pid_a: str, pid_b: str) -> dict:
    from src.delta.engine import compute_delta
    from src.ingest.pid_store import load
    from src.observability.tracing import new_trace
    from src.storage.metadata_store import get_metadata_store

    job_id = self.request.id or "eager"
    _job_started(job_id, "ingest_and_delta", pid_a=pid_a, pid_b=pid_b)
    try:
        with new_trace(kind="task_ingest_delta", pid_a=pid_a, pid_b=pid_b) as trace:
            with trace.span("ingest_a"):
                doc_a = load(pid_a)
            with trace.span("ingest_b"):
                doc_b = load(pid_b)
            with trace.span("delta") as span:
                delta = compute_delta(doc_a, doc_b)
                span.attrs["total_changes"] = len(delta.items)

        delta_json = delta.model_dump(mode="json")
        get_metadata_store().save_delta_result(pid_a, pid_b, delta_json)
        result = {"pid_a": pid_a, "pid_b": pid_b, "counts": delta.counts_by_kind(), "total_changes": len(delta.items)}
        _job_finished(job_id, "success", result=result)
        return result
    except Exception as exc:  # noqa: BLE001 - record failure on the durable job record, then re-raise for Celery
        _job_finished(job_id, "failure", error=f"{type(exc).__name__}: {exc}")
        raise


@celery_app.task(name="tasks.render_markup", bind=True)
def render_markup_task(self, pid_a: str, pid_b: str, out_path: str) -> dict:
    from src.delta.engine import compute_delta
    from src.ingest.pid_store import load, resolve_pid
    from src.markup.overlay import render_markup

    job_id = self.request.id or "eager"
    _job_started(job_id, "render_markup", pid_a=pid_a, pid_b=pid_b)
    try:
        doc_a = load(pid_a)
        doc_b = load(pid_b)
        delta = compute_delta(doc_a, doc_b)
        b_source = Path(resolve_pid(pid_b)["path"])
        out = render_markup(b_source, delta, Path(out_path))
        result = {"path": str(out), "bytes": out.stat().st_size}
        _job_finished(job_id, "success", result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        _job_finished(job_id, "failure", error=f"{type(exc).__name__}: {exc}")
        raise


@celery_app.task(name="tasks.run_eval", bind=True)
def run_eval_task(self) -> dict:
    from eval.run_eval import compute_pass_fail, run_chat_eval, run_delta_eval
    from src.storage.metadata_store import get_metadata_store

    job_id = self.request.id or "eager"
    _job_started(job_id, "run_eval")
    try:
        delta_results = run_delta_eval()
        chat_results = run_chat_eval()
        passed, reasons = compute_pass_fail(delta_results, chat_results)
        payload = {"delta": delta_results, "chat": chat_results, "passed": passed, "fail_reasons": reasons}
        get_metadata_store().save_eval_run(payload)
        _job_finished(job_id, "success", result={"passed": passed})
        return payload
    except Exception as exc:  # noqa: BLE001
        _job_finished(job_id, "failure", error=f"{type(exc).__name__}: {exc}")
        raise
