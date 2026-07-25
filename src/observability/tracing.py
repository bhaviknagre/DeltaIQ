from __future__ import annotations

import json
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from src.config import settings
from src.observability.logging import get_logger, get_request_id, set_request_id
from src.observability.prometheus_metrics import (
    REQUEST_ERRORS_TOTAL,
    REQUESTS_TOTAL,
    SPAN_DURATION_SECONDS,
    SPAN_ERRORS_TOTAL,
)

logger = get_logger("observability.tracing")


@dataclass
class Span:
    name: str
    start: float
    end: float | None = None
    duration_ms: float | None = None
    status: str = "ok"
    attrs: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attrs": self.attrs,
            "error": self.error,
        }


class Trace:
    def __init__(self, request_id: str | None = None, kind: str = "request"):
        self.request_id = request_id or str(uuid.uuid4())
        self.kind = kind
        self.started_at = time.time()
        self.ended_at: float | None = None
        self.spans: list[Span] = []
        self.attrs: dict = {}
        set_request_id(self.request_id)

    @contextmanager
    def span(self, name: str, **attrs):
        s = Span(name=name, start=time.time(), attrs=dict(attrs))
        self.spans.append(s)
        logger.info(f"span_start:{name}", extra={"extra_fields": {"span": name, **attrs}})
        try:
            yield s
        except Exception as exc: 
            s.status = "error"
            s.error = f"{type(exc).__name__}: {exc}"
            logger.error(
                f"span_error:{name}",
                extra={"extra_fields": {"span": name, "error": s.error, "trace": traceback.format_exc()}},
            )
            SPAN_ERRORS_TOTAL.labels(span_name=name).inc()
            raise
        finally:
            s.end = time.time()
            s.duration_ms = round((s.end - s.start) * 1000, 3)
            SPAN_DURATION_SECONDS.labels(span_name=name).observe(s.end - s.start)
            logger.info(
                f"span_end:{name}",
                extra={"extra_fields": {"span": name, "duration_ms": s.duration_ms, "status": s.status}},
            )

    def set_attr(self, key: str, value) -> None:
        self.attrs[key] = value

    def finish(self) -> dict:
        self.ended_at = time.time()
        payload = {
            "request_id": self.request_id,
            "kind": self.kind,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": round((self.ended_at - self.started_at) * 1000, 3),
            "attrs": self.attrs,
            "spans": [s.to_dict() for s in self.spans],
            "has_error": any(s.status == "error" for s in self.spans),
        }
        out = Path(settings.traces_dir) / f"{self.request_id}.json"
        out.write_text(json.dumps(payload, indent=2, default=str))

        REQUESTS_TOTAL.labels(kind=self.kind).inc()
        if payload["has_error"]:
            REQUEST_ERRORS_TOTAL.labels(kind=self.kind).inc()

        return payload


@contextmanager
def new_trace(kind: str = "request", **attrs):
    t = Trace(kind=kind)
    for k, v in attrs.items():
        t.set_attr(k, v)
    try:
        yield t
    finally:
        t.finish()
