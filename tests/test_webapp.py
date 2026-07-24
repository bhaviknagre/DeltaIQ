"""Smoke tests for the web UI routes — not a substitute for the CLI/eval
tests (which cover the actual logic), just confirming the FastAPI layer
wires up correctly: templates render, the chat API returns a grounded
answer, and the criticality signal reaches the results page. Skips if the
sample pair hasn't been generated / seeded yet."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not (ROOT / "data" / "samples" / "pair_native" / "rev_a.pdf").exists(),
    reason="sample pair not generated — run `make samples && make seed` first",
)


@pytest.fixture(scope="module")
def client():
    from src.ingest.pid_store import register_pid
    from src.webapp.app import app

    register_pid("demo-native-a", "data/samples/pair_native/rev_a.pdf", "Rev A")
    register_pid("demo-native-b", "data/samples/pair_native/rev_b.pdf", "Rev B")
    return TestClient(app)


def test_home_page_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Compare two PID revisions" in resp.text


def test_results_page_shows_criticality_signal(client):
    resp = client.get("/results", params={"pid_a": "demo-native-a", "pid_b": "demo-native-b"})
    assert resp.status_code == 200
    assert "chip-red" in resp.text or "chip-yellow" in resp.text
    assert "tables</span>" in resp.text  # canonical summary card present


def test_report_json_matches_delta_engine(client):
    resp = client.get("/report/json", params={"pid_a": "demo-native-a", "pid_b": "demo-native-b"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["pid_a"] == "demo-native-a"
    assert len(payload["items"]) == 6  # matches the known ground-truth edit count


def test_chat_api_returns_grounded_citation(client):
    resp = client.post(
        "/api/chat",
        json={"pid_a": "demo-native-a", "pid_b": "demo-native-b", "question": "What changed with tag 26-KA-902?"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["grounded"] is True
    assert len(payload["citations"]) > 0


def test_eval_page_renders_without_prior_run(client):
    resp = client.get("/eval")
    assert resp.status_code == 200
