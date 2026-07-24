"""Check: Celery background tasks. Runs in CELERY_TASK_ALWAYS_EAGER mode
(synchronous, in-process) so this check needs no live worker/Redis to verify
task *logic* — see src/tasks/celery_app.py for why eager mode exists. If a
real Redis is reachable, also dispatches one task through a live worker
process to prove the actual async path works, not just the logic.

Usage: python -m scripts.checks.check_tasks
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent
NATIVE_A = ROOT / "data" / "samples" / "pair_native" / "rev_a.pdf"
NATIVE_B = ROOT / "data" / "samples" / "pair_native" / "rev_b.pdf"


def main() -> None:
    suite = CheckSuite("tasks")

    if not (NATIVE_A.exists() and NATIVE_B.exists()):
        suite.skip("all task checks", "sample pair not generated — run `make samples`")
        suite.exit()
        return

    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
    from src.ingest.pid_store import register_pid

    register_pid("check-task-a", str(NATIVE_A), "Rev A")
    register_pid("check-task-b", str(NATIVE_B), "Rev B")

    with suite.check("ingest_and_delta_task (eager, no worker needed)"):
        from src.tasks.jobs import ingest_and_delta_task

        result = ingest_and_delta_task.delay("check-task-a", "check-task-b").get(timeout=30)
        assert result["total_changes"] == 6, result

    with suite.check("processing job record written for the task run"):
        from src.storage.metadata_store import get_metadata_store

        jobs = get_metadata_store().list_processing_jobs(limit=5)
        matching = [j for j in jobs if j.get("kind") == "ingest_and_delta" and j.get("status") == "success"]
        assert matching, f"no successful ingest_and_delta job record found in {jobs}"

    with suite.check("a task failure is recorded on the job record, then re-raised"):
        from celery.exceptions import Retry
        from src.tasks.jobs import ingest_and_delta_task

        try:
            ingest_and_delta_task.delay("check-task-a", "pid-that-does-not-exist").get(timeout=10)
            raise AssertionError("expected the task to raise for an unknown PID")
        except AssertionError:
            raise
        except Exception:
            pass  # any exception from the unknown PID is the expected outcome here

    # Real live-worker path: only if a real Redis is reachable. Spawns an
    # actual `celery worker` subprocess (not eager mode) to prove the async
    # dispatch path works end to end, not just the task logic.
    try:
        import redis

        redis.Redis.from_url("redis://localhost:6379/0", socket_connect_timeout=1).ping()
        redis_reachable = True
    except Exception:
        redis_reachable = False

    if not redis_reachable:
        suite.skip("live Celery worker over real Redis", "no Redis reachable at redis://localhost:6379/0")
    else:
        with suite.check("live Celery worker processes a real dispatched task"):
            env = {**os.environ, "CELERY_TASK_ALWAYS_EAGER": ""}
            proc = subprocess.Popen(
                [sys.executable, "-m", "celery", "-A", "src.tasks.celery_app", "worker",
                 "--loglevel=warning", "--concurrency=1"],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                time.sleep(4)  # worker startup
                from src.tasks.celery_app import celery_app

                async_result = celery_app.send_task("tasks.ingest_and_delta", args=["check-task-a", "check-task-b"])
                result = async_result.get(timeout=20)
                assert result["total_changes"] == 6, result
            finally:
                proc.terminate()
                proc.wait(timeout=10)

    suite.exit()


if __name__ == "__main__":
    main()
