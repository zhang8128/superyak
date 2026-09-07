.DEFAULT_GOAL := help
PYTHON_VERSION ?= 3.13
ENGRAM_ARGS ?=
CHAT_ARGS ?=
SERVE_ARGS ?=

.PHONY: help setup setup-engram setup-lighthouse check check-engram check-lighthouse check-integration chat serve

help:
	@echo "make setup              Install both projects from their lockfiles"
	@echo "make check              Run both suites and the interoperability check"
	@echo "make check-engram       Run the Python suite"
	@echo "make check-lighthouse   Build, lint, typecheck, test, and run protocol proofs"
	@echo "make check-integration  Compare schemas and validate real-socket receipts"
	@echo "make chat / make serve  Start Engram chat / its local web interface"

setup: setup-engram setup-lighthouse

setup-engram:
	cd engram && uv sync --locked --extra dev --python "$(PYTHON_VERSION)"

setup-lighthouse:
	cd lighthouse && pnpm install --frozen-lockfile
	cd lighthouse && pnpm build

check: check-engram check-lighthouse check-integration

check-engram:
	cd engram && LIGHTHOUSE_REPO="$(CURDIR)/lighthouse" uv run --locked --extra dev python -m pytest -q -ra --tb=short

check-lighthouse:
	cd lighthouse && pnpm check && pnpm proof && pnpm recall:proof

check-integration:
	cd engram && uv run --locked --extra dev python ../scripts/check_integration.py

chat:
	cd engram && uv run --locked python -m context_cli $(ENGRAM_ARGS) chat $(CHAT_ARGS)

serve:
	cd engram && uv run --locked python -m context_cli $(ENGRAM_ARGS) serve $(SERVE_ARGS)
