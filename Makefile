.PHONY: setup samples seed run chat markup eval metrics test clean ui docs docs-build \
        check check-fast check-env check-ingestion check-delta check-report check-retrieval \
        check-observability check-chat check-webapp check-eval check-docs check-storage \
        check-tasks check-metrics check-dvc check-k8s version worker flower infra-up infra-down infra-logs \
        dvc-repro dvc-dag dvc-metrics

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
	$(PY) -m src.cli run 26-9026-REV-A 26-9026-REV-B --out-dir output/native

run-scanned: seed
	$(PY) -m src.cli run 26-9026-REV-A-SCAN 26-9026-REV-B-SCAN --out-dir output/scanned

chat: seed
	$(PY) -m src.cli chat 26-9026-REV-A 26-9026-REV-B

markup: seed
	$(PY) -m src.cli markup 26-9026-REV-A 26-9026-REV-B --out output/native/markup.pdf

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

check-storage:
	$(PY) -m scripts.checks.check_storage

check-tasks: seed
	$(PY) -m scripts.checks.check_tasks

check-metrics: seed
	$(PY) -m scripts.checks.check_metrics

check-dvc:
	$(PY) -m scripts.checks.check_dvc

check-k8s:
	$(PY) -m scripts.checks.check_k8s

dvc-repro:
	$(VENV)/dvc repro

dvc-dag:
	$(VENV)/dvc dag

dvc-metrics:
	$(VENV)/dvc metrics show

version:
	@$(PY) -c "from src._version import __version__; print(__version__)"

# --- Infra (MongoDB, Redis, MinIO, Chroma, Prometheus, Grafana) ---
infra-up:
	docker compose --profile full up -d
	@echo "mongo:27017  redis:6379  minio:9000 (console :9001)  chroma:8100  prometheus:9090  grafana:3000"

infra-down:
	docker compose --profile full down

infra-logs:
	docker compose --profile full logs -f

# Celery worker / Flower — needs Redis (`make infra-up`, or a local redis-server).
worker:
	$(VENV)/celery -A src.tasks.celery_app worker --loglevel=info --concurrency=2

flower:
	$(VENV)/celery -A src.tasks.celery_app flower --port=5555

clean:
	rm -rf output logs/*.jsonl traces/*.json data/renders site
