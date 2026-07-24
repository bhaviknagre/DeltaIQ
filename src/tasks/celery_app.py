"""Celery application: background processing for the genuinely slow
operations in this system — scanned-PDF OCR ingestion (~6s observed) and
full eval runs (~30s+ with a real LLM) are bad fits for blocking a web
request. Redis is both broker and result backend (REDIS_URL, src/config.py)
— one less moving part than RabbitMQ+a separate result store for this
project's scale, and it's what Flower expects out of the box.

CELERY_TASK_ALWAYS_EAGER=1 (or settings.celery_task_always_eager) runs tasks
synchronously in-process instead of dispatching to a worker — used by check
scripts/tests so task *logic* is verified even with no live worker running,
without special-casing test code or requiring Redis to be up just to import
this module.
"""

from __future__ import annotations

from celery import Celery

from src.config import settings

celery_app = Celery("delta_chat", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_always_eager,
    worker_send_task_events=True,  # required for Flower to show task history
    task_send_sent_event=True,
)

# Explicit, not autodiscover_tasks: this is a plain src/ layout, not a
# Django-style app-per-directory project autodiscover expects. Importing
# jobs here (after celery_app is fully configured, avoiding a circular
# import since jobs.py imports celery_app from this module) is what
# actually registers the @celery_app.task-decorated functions — a worker
# started as `celery -A src.tasks.celery_app worker` would otherwise show
# an empty [tasks] list and reject every dispatched task as unregistered.
from src.tasks import jobs  # noqa: E402,F401
