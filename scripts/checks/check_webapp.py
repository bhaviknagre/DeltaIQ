"""Check: the FastAPI web UI — routes render, canonical-summary/criticality
data reaches the page, and the chat API returns a grounded, cited answer.
Uses FastAPI's TestClient (in-process, no server/port needed).

Usage: python -m scripts.checks.check_webapp
"""

from __future__ import annotations

import warnings
from pathlib import Path

from scripts.checks._common import CheckSuite

# Upstream library noise, not ours: Starlette's TestClient currently warns
# about a future httpx->httpx2 migration on import. Harmless and out of our
# control — filtered so it doesn't read like a problem in check output.
warnings.filterwarnings("ignore", message=r".*httpx.*deprecated.*")

ROOT = Path(__file__).resolve().parent.parent.parent
NATIVE_A = ROOT / "data" / "samples" / "pair_native" / "rev_a.pdf"
NATIVE_B = ROOT / "data" / "samples" / "pair_native" / "rev_b.pdf"


def main() -> None:
    suite = CheckSuite("webapp")

    if not (NATIVE_A.exists() and NATIVE_B.exists()):
        suite.skip("all webapp checks", "sample pair not generated — run `make samples`")
        suite.exit()
        return

    from fastapi.testclient import TestClient

    from src.ingest.pid_store import register_pid
    from src.webapp.app import app

    register_pid("check-web-a", str(NATIVE_A), "Rev A")
    register_pid("check-web-b", str(NATIVE_B), "Rev B")
    client = TestClient(app)

    with suite.check("GET / renders the dashboard"):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Compare two PID revisions" in resp.text

    with suite.check("GET /results shows canonical summary + criticality chips"):
        resp = client.get("/results", params={"pid_a": "check-web-a", "pid_b": "check-web-b"})
        assert resp.status_code == 200
        assert "tables</span>" in resp.text
        assert "chip-" in resp.text

    with suite.check("GET /report/json matches the delta engine exactly"):
        resp = client.get("/report/json", params={"pid_a": "check-web-a", "pid_b": "check-web-b"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 6

    with suite.check("GET /markup/download returns a real PDF"):
        resp = client.get("/markup/download", params={"pid_a": "check-web-a", "pid_b": "check-web-b"})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    with suite.check("POST /api/chat returns a grounded, cited answer"):
        resp = client.post(
            "/api/chat",
            json={"pid_a": "check-web-a", "pid_b": "check-web-b", "question": "What changed with tag 26-KA-902?"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["grounded"] is True
        assert len(payload["citations"]) > 0

    with suite.check("GET /eval renders without a prior run"):
        resp = client.get("/eval")
        assert resp.status_code == 200

    suite.exit()


if __name__ == "__main__":
    main()
