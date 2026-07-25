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
    worker_send_task_events=True,  
    task_send_sent_event=True,
)
from src.tasks import jobs 
