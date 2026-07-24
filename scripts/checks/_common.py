"""Shared harness for scripts/checks/*.py.

Each check script is a small, standalone, independently-runnable diagnostic
for one subsystem (ingestion, delta engine, chat, observability, eval, web
UI, docs...). The point of splitting these out instead of one big script:
when something breaks, you know exactly which subsystem broke without
re-running everything else. Each script exits 0 if all its sub-checks
passed, 1 otherwise — so it composes with `scripts/check_all.py` and CI.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import traceback
from contextlib import contextmanager

# Quiet routine INFO-level console noise (ingest_start, delta_computed, ...)
# by default so check output is just PASS/FAIL/timing — full detail is still
# written to logs/app.jsonl and traces/*.json either way. Pass --verbose to
# see everything (useful when a check fails and you want the surrounding
# context without re-reading log files by hand).
if "--verbose" not in sys.argv:
    os.environ.setdefault("QUIET_CONSOLE_LOGS", "1")

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


@contextmanager
def expected_failure(note: str):
    """Wraps a deliberately-triggered failure (used to verify the system
    logs/traces/degrades correctly instead of crashing) so its ERROR-level
    console output doesn't look indistinguishable from a real problem when
    skimming check output. The failure is still fully captured in the trace
    file and log file underneath — this only silences the terminal echo for
    the duration of the block, via the standard library's `logging.disable`.
    Assertions in the calling check should read the trace/log *files*, not
    console output, so nothing about what's actually being verified changes.
    """
    print(f"  {_DIM}(expected: {note} — output intentionally silenced below){_RESET}")
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(logging.NOTSET)


class CheckSuite:
    """Runs a set of named sub-checks within one script, prints a
    ✅/❌ line per sub-check with timing, and tracks overall pass/fail."""

    def __init__(self, name: str):
        self.name = name
        self.results: list[tuple[str, bool, str, float]] = []
        print(f"\n{_DIM}== {name} =={_RESET}")

    @contextmanager
    def check(self, label: str):
        start = time.time()
        try:
            yield
        except AssertionError as exc:
            elapsed = time.time() - start
            self.results.append((label, False, str(exc), elapsed))
            print(f"  {_RED}FAIL{_RESET} {label} ({elapsed:.2f}s) — {exc}")
        except Exception as exc:  # noqa: BLE001 - a check crashing is itself a failure to report, not swallow
            elapsed = time.time() - start
            detail = f"{type(exc).__name__}: {exc}"
            self.results.append((label, False, detail, elapsed))
            print(f"  {_RED}FAIL{_RESET} {label} ({elapsed:.2f}s) — {detail}")
            if "--traceback" in sys.argv:
                traceback.print_exc()
        else:
            elapsed = time.time() - start
            self.results.append((label, True, "", elapsed))
            print(f"  {_GREEN}PASS{_RESET} {label} ({elapsed:.2f}s)")

    def skip(self, label: str, reason: str):
        print(f"  {_YELLOW}SKIP{_RESET} {label} — {reason}")

    def summarize(self) -> bool:
        passed = sum(1 for _, ok, _, _ in self.results if ok)
        total = len(self.results)
        all_ok = passed == total
        color = _GREEN if all_ok else _RED
        print(f"{color}{self.name}: {passed}/{total} passed{_RESET}")
        return all_ok

    def exit(self) -> None:
        sys.exit(0 if self.summarize() else 1)
