.DEFAULT_GOAL := help
PYTHON_VERSION ?= 3.13
ENGRAM_ARGS ?=
CHAT_ARGS ?=
SERVE_ARGS ?=
SESSION_ARGS ?= list
ADNA_ARGS ?= --help
RUNTIME_CONFIG ?= $(HOME)/.config/superyak/runtime.json
RUNTIME_ARGS ?=
STAMPEDE_PYTHON ?= $(CURDIR)/engram/.venv/bin/python
STAMPEDE_CONFIG ?= $(CURDIR)/.engram/stampede/config.json
STAMPEDE_ARGS ?=
RESEARCH_POC_ARGS ?=
RESEARCH_POC_PYTHON ?= $(CURDIR)/engram/.venv/bin/python
LEAD_PROBE_ARGS ?= --help
ATLAS_PYTHON ?= $(CURDIR)/atlas/.venv/bin/python
ATLAS_PROJECT ?= $(CURDIR)/.engram/atlas/project
ATLAS_ARGS ?= --help

.PHONY: help setup setup-engram setup-lighthouse setup-atlas check check-engram check-lighthouse check-atlas check-integration atlas atlas-demo chat serve sessions adna status stampede-config stampede-plan stampede-deploy stampede-simulate stampede research-poc lead-probe

help:
	@echo "make setup              Install all three components from their lockfiles"
	@echo "make check              Run all suites and interoperability checks"
	@echo "make check-engram       Run the Python suite"
	@echo "make check-lighthouse   Build, lint, typecheck, test, and run protocol proofs"
	@echo "make check-atlas        Run the Atlas research workbench suite"
	@echo "make check-integration  Compare schemas and validate real-socket receipts"
	@echo "make chat / make serve  Start Engram chat / its local web interface"
	@echo "make sessions           List Codex sessions; SESSION_ARGS accepts ask/result"
	@echo "make adna               Inspect aDNA projects without a model; set ADNA_ARGS"
	@echo "make status             Inspect the configured runtime without writing state"
	@echo "make stampede-config    Create the local Stampede3 connection config once"
	@echo "make stampede-plan      Inspect the campaign without connecting"
	@echo "make stampede-deploy    Stage, prepare, and submit the configured campaign"
	@echo "make stampede-simulate  Rehearse the whole small matrix locally"
	@echo "make stampede           Run status/fetch/resume using STAMPEDE_ARGS"
	@echo "make research-poc       Run/resume local Atlas research; RESEARCH_POC_ARGS sets options"
	@echo "make lead-probe         Probe an existing model endpoint; LEAD_PROBE_ARGS sets options"
	@echo "make atlas-demo         Render the public research pilot offline"
	@echo "make atlas              Atlas project CLI; ATLAS_ARGS defaults to --help"

setup: setup-engram setup-lighthouse setup-atlas

setup-engram:
	cd engram && uv sync --locked --extra dev --python "$(PYTHON_VERSION)"

setup-atlas:
	cd atlas && uv sync --locked --extra dev --extra mcp --python "$(PYTHON_VERSION)"

setup-lighthouse:
	cd lighthouse && pnpm install --frozen-lockfile
	cd lighthouse && pnpm build

check: check-engram check-lighthouse check-atlas check-integration

check-engram:
	cd engram && LIGHTHOUSE_REPO="$(CURDIR)/lighthouse" uv run --locked --extra dev python -m pytest -q -ra --tb=short

check-atlas:
	cd atlas && uv run --locked --extra dev --extra mcp python -m pytest -q -ra --tb=short

check-lighthouse:
	cd lighthouse && pnpm check && pnpm proof && pnpm recall:proof

check-integration:
	cd engram && uv run --locked --extra dev python ../scripts/check_integration.py
	cd engram && ENGRAM_REQUIRE_LIGHTHOUSE_INTEROP=1 LIGHTHOUSE_REPO="$(CURDIR)/lighthouse" uv run --locked --extra dev python -m pytest tests/test_lighthouse_interop.py -q -ra --tb=short
	"$(ATLAS_PYTHON)" scripts/check_atlas_integration.py

atlas-demo:
	"$(ATLAS_PYTHON)" scripts/atlas.py --project "$(ATLAS_PROJECT)"

atlas:
	"$(ATLAS_PYTHON)" atlas/scripts/atlas_research.py --project "$(ATLAS_PROJECT)" $(ATLAS_ARGS)

chat:
	cd engram && uv run --locked python -m context_cli $(ENGRAM_ARGS) chat $(CHAT_ARGS)

serve:
	cd engram && uv run --locked python -m context_cli $(ENGRAM_ARGS) serve $(SERVE_ARGS)

sessions:
	cd engram && uv run --locked python -m session_cli $(SESSION_ARGS)

adna:
	@cd engram && uv run --locked python -m adna_cli $(ADNA_ARGS)

status:
	engram/.venv/bin/python scripts/runtime.py --config "$(RUNTIME_CONFIG)" $(RUNTIME_ARGS) status

stampede-config:
	@mkdir -p "$$(dirname "$(STAMPEDE_CONFIG)")"
	@test -f "$(STAMPEDE_CONFIG)" || cp deploy/stampede/config.example.json "$(STAMPEDE_CONFIG)"
	@echo "Stampede3 configuration: $(STAMPEDE_CONFIG)"

stampede-plan: stampede-config
	"$(STAMPEDE_PYTHON)" -m deploy.stampede plan --config "$(STAMPEDE_CONFIG)"

stampede-deploy:
	"$(STAMPEDE_PYTHON)" -m deploy.stampede deploy --config "$(STAMPEDE_CONFIG)"

stampede-simulate:
	"$(STAMPEDE_PYTHON)" -m deploy.stampede simulate $(STAMPEDE_ARGS)

stampede:
	"$(STAMPEDE_PYTHON)" -m deploy.stampede $(STAMPEDE_ARGS)

research-poc:
	"$(RESEARCH_POC_PYTHON)" -m research_poc $(RESEARCH_POC_ARGS)

lead-probe:
	"$(STAMPEDE_PYTHON)" -m deploy.stampede.probe $(LEAD_PROBE_ARGS)
