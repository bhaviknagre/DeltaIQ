.PHONY: setup samples seed run chat markup eval metrics test clean ui docs docs-build \
        check check-fast check-env check-ingestion check-delta check-report check-retrieval \
        check-observability check-chat check-webapp check-eval check-docs version

VENV := .venv/bin
PY := $(VENV)/python

setup:
	python3 -m venv .venv
	$(VENV)/pip install --quiet --upgrade pip
	$(VENV)/pip install --quiet -r requirements.txt
	$(VENV)/pip install --quiet -r requirements-docs.txt
	@command -v tesseract >/dev/null 2>&1 || (echo "tesseract not found — install it: brew install tesseract (macOS) or apt-get install tesseract-ocr (Linux)" && exit 1)

samples:
	$(PY) -m data.samples.build_synthetic_pairs

seed:
	$(PY) -m scripts.seed_pids

# Reproducible run: ingest the demo native-PDF pair, compute the delta, write the report.
run: seed
	$(PY) -m src.cli run demo-native-a demo-native-b --out-dir output/native

run-scanned: seed
	$(PY) -m src.cli run demo-scanned-a demo-scanned-b --out-dir output/scanned

chat: seed
	$(PY) -m src.cli chat demo-native-a demo-native-b

markup: seed
	$(PY) -m src.cli markup demo-native-a demo-native-b --out output/native/markup.pdf

eval:
	$(PY) -m eval.run_eval

metrics:
	$(PY) -m src.observability.metrics

test:
	$(PY) -m pytest tests/ -v

# Web UI: dashboard (delta + charts + RAG signal), chat, eval scorecard.
ui: seed
	$(VENV)/uvicorn src.webapp.app:app --reload --port 8000

docs:
	$(VENV)/mkdocs serve

docs-build:
	$(VENV)/mkdocs build

# --- Per-subsystem check scripts (scripts/checks/) ---
# Each is independently runnable so a failure is isolated to one subsystem
# instead of buried in one big run. `make check` runs all of them in order
# and prints a final pass/fail summary; use the individual targets when
# you only care about one piece while developing.
check: seed
	$(PY) -m scripts.check_all

check-fast: seed
	$(PY) -m scripts.check_all --skip-slow

check-env:
	$(PY) -m scripts.checks.check_env

check-ingestion: seed
	$(PY) -m scripts.checks.check_ingestion

check-delta: seed
	$(PY) -m scripts.checks.check_delta_engine

check-report: seed
	$(PY) -m scripts.checks.check_delta_report

check-retrieval: seed
	$(PY) -m scripts.checks.check_retrieval

check-observability:
	$(PY) -m scripts.checks.check_observability

check-chat: seed
	$(PY) -m scripts.checks.check_chat

check-webapp: seed
	$(PY) -m scripts.checks.check_webapp

check-eval: seed
	$(PY) -m scripts.checks.check_eval

check-docs:
	$(PY) -m scripts.checks.check_docs

version:
	@$(PY) -c "from src._version import __version__; print(__version__)"

clean:
	rm -rf output logs/*.jsonl traces/*.json data/renders site
