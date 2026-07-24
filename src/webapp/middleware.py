"""ASGI middleware: every response gets an `X-Request-ID` and
`X-Process-Time` header, and every HTTP request is counted/timed in
Prometheus — independent of whether the route handler happens to open a
homegrown trace (src/observability/tracing.py covers business-logic spans;
this covers the HTTP layer itself, including routes that don't trace
anything, like static file serving or a 404).

`X-Request-ID` is honored if the caller already sent one (useful for
correlating a request across a reverse proxy), generated otherwise —
propagated into the same contextvar tracing.py's spans read, so a route
that also opens a homegrown trace shares the same id end to end.
"""

from __future__ import annotations

import time
import uuid

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.observability.logging import set_request_id

HTTP_REQUESTS_TOTAL = Counter(
    "deltachat_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "deltachat_http_request_duration_seconds", "HTTP request duration", ["method", "path"],
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        set_request_id(request_id)
        start = time.time()

        response = await call_next(request)

        duration = time.time() - start
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{duration:.4f}"

        # Route path template (e.g. "/results", not "/results?pid_a=...")
        # keeps the metric's cardinality bounded regardless of query params.
        path = request.scope.get("route").path if request.scope.get("route") else request.url.path
        HTTP_REQUESTS_TOTAL.labels(method=request.method, path=path, status=response.status_code).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, path=path).observe(duration)

        return response
