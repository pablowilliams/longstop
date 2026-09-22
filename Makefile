PY := python3
export PYTHONPATH := src

.PHONY: help setup test universe announcements outcomes breaks report \
	console-install console-build console-dev api clean

help:
	@grep -E '^[a-z][a-z-]*:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

setup: ## install dependencies
	$(PY) -m pip install -q -r requirements.txt

test: ## unit tests
	$(PY) -m pytest tests -q

announcements: ## stage one, scan quarterly filing indexes (needs network, ~3GB transferred)
	$(PY) -m longstop.cli universe announcements --start 2001 --end 2025

outcomes: ## stage two, label every deal from the target's later filings (needs network)
	$(PY) -m longstop.cli universe outcomes

report: ## write results/universe.json
	$(PY) -m longstop.cli universe report

console-install: ## install the console's dependencies
	cd console && npm install --no-audit --no-fund

console-build: ## typecheck and build the console into console/dist
	cd console && npm run build

console-dev: ## the console with hot reload on :5173, proxying the API on :8000
	cd console && npm run dev

api: ## serve the API, and the built console if there is one, on :8000
	$(PY) -m uvicorn longstop.api.app:app --port 8000

breaks: ## read every break candidate's 8-K and confirm it (needs network)
	$(PY) -m longstop.cli breaks confirm

universe: announcements outcomes report ## the whole phase 0 pipeline

clean:
	rm -rf results/*.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
