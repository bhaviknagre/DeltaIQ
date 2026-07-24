.PHONY: setup samples seed run chat markup eval metrics test clean

VENV := .venv/bin
PY := $(VENV)/python

setup:
	python3 -m venv .venv
	$(VENV)/pip install --quiet --upgrade pip
	$(VENV)/pip install --quiet -r requirements.txt
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

clean:
	rm -rf output logs/*.jsonl traces/*.json data/renders
