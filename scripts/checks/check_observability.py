"""Check: tracing writes real per-request trace files with spans, structured
logs carry a correlation id, errors inside a span are captured (not
swallowed) before re-raising, and the metrics reducer runs over real traces.

Usage: python -m scripts.checks.check_observability
"""

from __future__ import annotations

import json

from scripts.checks._common import CheckSuite, expected_failure


def main() -> None:
    suite = CheckSuite("observability")

    from src.config import settings
    from src.observability.tracing import new_trace

    with suite.check("trace file is written with expected spans"):
        with new_trace(kind="check_observability") as trace:
            with trace.span("step_one", note="check"):
                pass
            with trace.span("step_two"):
                pass
        trace_path = settings.traces_dir / f"{trace.request_id}.json"
        assert trace_path.exists(), f"no trace file at {trace_path}"
        payload = json.loads(trace_path.read_text())
        span_names = [s["name"] for s in payload["spans"]]
        assert span_names == ["step_one", "step_two"], span_names
        assert payload["has_error"] is False

    with suite.check("a span error is captured on the trace, then re-raised (not swallowed)"):
        request_id = None
        with expected_failure("a span deliberately raises, to verify it's captured and re-raised, not swallowed"):
            try:
                with new_trace(kind="check_observability") as trace:
                    request_id = trace.request_id
                    with trace.span("failing_step"):
                        raise ValueError("simulated failure")
            except ValueError:
                pass
            else:
                raise AssertionError("expected the span error to re-raise")
        trace_path = settings.traces_dir / f"{request_id}.json"
        payload = json.loads(trace_path.read_text())
        assert payload["has_error"] is True
        assert payload["spans"][0]["status"] == "error"
        assert "simulated failure" in payload["spans"][0]["error"]

    with suite.check("structured log line carries the request_id correlation id"):
        with new_trace(kind="check_observability") as trace:
            from src.observability.logging import get_logger, log_event

            logger = get_logger("check_observability")
            log_event(logger, 20, "check_marker_event", probe=True)
        log_line = None
        for line in reversed(settings.logs_dir.joinpath("app.jsonl").read_text().splitlines()):
            if "check_marker_event" in line:
                log_line = json.loads(line)
                break
        assert log_line is not None, "log line not found"
        assert log_line["request_id"] == trace.request_id

    with suite.check("metrics reducer runs over real trace files without error"):
        from src.observability.metrics import load_traces, summarize

        traces = load_traces()
        summary = summarize(traces)
        assert summary["count"] >= 1

    suite.exit()


if __name__ == "__main__":
    main()
