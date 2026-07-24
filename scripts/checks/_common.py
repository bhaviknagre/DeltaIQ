"""Shared harness for scripts/checks/*.py.

Each check script is a small, standalone, independently-runnable diagnostic
for one subsystem (ingestion, delta engine, chat, observability, eval, web
UI, docs...). The point of splitting these out instead of one big script:
when something breaks, you know exactly which subsystem broke without
re-running everything else. Each script exits 0 if all its sub-checks
passed, 1 otherwise — so it composes with `scripts/check_all.py` and CI.
"""

from __future__ import annotations

import sys
import time
import traceback
from contextlib import contextmanager

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


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
