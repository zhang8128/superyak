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
RESEARCH_TASK_ARGS ?= --help
RESEARCH_TASK_PYTHON ?= $(CURDIR)/engram/.venv/bin/python
LEAD_PROBE_ARGS ?= --help
ATLAS_PYTHON ?= $(CURDIR)/atlas/.venv/bin/python
ATLAS_PROJECT ?= $(CURDIR)/.engram/atlas/project
ATLAS_ARGS ?= --help
HOME_DATA ?= $(CURDIR)/.engram/home
HOME_DEMO_DATA ?= $(CURDIR)/.engram/home-demo
HOME_PORT ?= 7435
HOME_ARGS ?=
TUNING_ARGS ?= --help
TUNING_EXTRA ?= train

PEER_BUNDLE ?= $(CURDIR)/superyak-peer-source.tar.gz

.PHONY: setup-team check-team setup-tuning check-tuning tuning setup-peer check-peer home home-demo peer-bundle help setup setup-engram setup-lighthouse setup-atlas check check-engram check-lighthouse check-atlas check-integration check-research-tasks atlas atlas-demo chat serve sessions adna status stampede-config stampede-plan stampede-deploy stampede-simulate stampede research-poc research-task lead-probe

help:
	@echo "make setup-tuning / check-tuning  Install/check clinical and biotech LoRA tools"
	@echo "make setup-team / check-team      Install/check team mode (lead + Codex/Claude workers)"
	@echo "make tuning             Dataset, model, train, evaluate and Slurm CLI; TUNING_ARGS sets options"
	@echo "make setup-peer / check-peer  Install/check the standalone personal home"
	@echo "make home-demo / home    Serve the fictional demo / ordinary peer on loopback"
	@echo "make peer-bundle         Create a new allowlisted source archive; PEER_BUNDLE selects output"
	@echo "make setup              Install all five components from their lockfiles"
	@echo "make check              Run all suites and interoperability checks"
	@echo "make check-engram       Run the Python suite"
	@echo "make check-lighthouse   Build, lint, typecheck, test, and run protocol proofs"
	@echo "make check-atlas        Run the Atlas research workbench suite"
	@echo "make check-research-tasks Run portable task tests in a separate process"
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
	@echo "make research-task      Export/run one frozen task; RESEARCH_TASK_ARGS sets options"
	@echo "make lead-probe         Probe an existing model endpoint; LEAD_PROBE_ARGS sets options"
	@echo "make atlas-demo         Render the public research pilot offline"
	@echo "make atlas              Atlas project CLI; ATLAS_ARGS defaults to --help"

setup: setup-engram setup-lighthouse setup-atlas setup-peer setup-tuning setup-team

setup-engram:
	cd engram && uv sync --locked --extra dev --python "$(PYTHON_VERSION)"

setup-atlas:
	cd atlas && uv sync --locked --extra dev --extra mcp --python "$(PYTHON_VERSION)"

setup-lighthouse:
	cd lighthouse && pnpm install --frozen-lockfile
	cd lighthouse && pnpm build

check: check-engram check-lighthouse check-atlas check-integration check-research-tasks check-peer check-tuning check-team

check-engram:
	cd engram && LIGHTHOUSE_REPO="$(CURDIR)/lighthouse" uv run --locked --extra dev python -m pytest -q -ra --tb=short

check-atlas:
	cd atlas && uv run --locked --extra dev --extra mcp python -m pytest -q -ra --tb=short

check-research-tasks:
	"$(RESEARCH_TASK_PYTHON)" -m pytest tests/research_tasks -q -ra --tb=short

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

research-task:
	"$(RESEARCH_TASK_PYTHON)" -m research_tasks $(RESEARCH_TASK_ARGS)

lead-probe:
	"$(STAMPEDE_PYTHON)" -m deploy.stampede.probe $(LEAD_PROBE_ARGS)

setup-team:
	cd team && uv sync --locked --extra dev --python "$(PYTHON_VERSION)"

check-team:
	cd team && uv run --locked --extra dev python -m pytest -q -ra --tb=short

setup-peer:
	cd peer && uv sync --locked --python "$(PYTHON_VERSION)"

check-peer:
	cd peer && uv run --locked python -m pytest -q -ra --tb=short

home-demo:
	uv run --locked --project peer python -m superyak_peer demo --data-dir "$(HOME_DEMO_DATA)"
	@echo "Superyak demo: http://127.0.0.1:$(HOME_PORT)"
	uv run --locked --project peer python -m superyak_peer serve --local-demo --data-dir "$(HOME_DEMO_DATA)" --port "$(HOME_PORT)" $(HOME_ARGS)

home:
	@echo "Superyak: http://127.0.0.1:$(HOME_PORT)"
	uv run --locked --project peer python -m superyak_peer serve --data-dir "$(HOME_DATA)" --port "$(HOME_PORT)" $(HOME_ARGS)

peer-bundle:
	uv run --locked --project peer python peer/scripts/source_bundle.py --output "$(PEER_BUNDLE)"

setup-tuning:
	cd tuning && uv sync --locked --extra dev --extra "$(TUNING_EXTRA)" --python "$(PYTHON_VERSION)"

check-tuning:
	cd tuning && uv run --locked --extra dev --extra "$(TUNING_EXTRA)" python -m pytest -q -ra --tb=short

tuning:
	cd tuning && uv run --locked --extra "$(TUNING_EXTRA)" python -m superyak_tuning $(TUNING_ARGS)
