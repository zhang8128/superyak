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
STATION ?= https://smart.tail7db420.ts.net
DOOR ?= https://smart.tail7db420.ts.net:8443
DOCK_ARGS ?=
AGENT_PYTHON ?= python3
STATION_DATA ?= $(HOME)/.local/share/superyak/lighthouse
STATION_BACKUPS ?= $(HOME)/.local/share/superyak/backups/station
SYSTEMD_USER ?= $(HOME)/.config/systemd/user
WORMHOLE_HOME ?= $(HOME)/.local/share/superyak/wormhole
STATION_VAULT_REPO ?= $(HOME)/aDNA/Station.aDNA.git
KEY_FILE ?=
APPROVER ?= andy
ID ?=
OUTPUT ?=
BACKUP ?=
DB ?=
REPLACED ?=
UNPAIR ?=
GRANTEE ?=
GRANT ?=
HOURS = 720
BUDGET = 10
ACTIONS = add,remove
# Spec 2026-10-14 S8, S9: the files make station-units installs, and the services that get the alert drop-in: the five,
# and any project ship's watcher on this machine (a later one gets it when make station-units runs again).
STATION_UNITS := superyak-backup.service superyak-backup.timer superyak-restore-test.service superyak-restore-test.timer superyak-alert@.service
ALERTED_SERVICES = superyak-lighthouse superyak-door superyak-ship superyak-odo superyak-wormhole $(patsubst %.service,%,$(notdir $(wildcard $(SYSTEMD_USER)/superyak-ship-*.service)))
HOME_DEMO_DATA ?= $(CURDIR)/.engram/home-demo
HOME_PORT ?= 7435
HOME_ARGS ?=
TUNING_ARGS ?= --help
TUNING_EXTRA ?= train

PEER_BUNDLE ?= $(CURDIR)/superyak-peer-source.tar.gz

.PHONY: dock station-share-link station-pending station-approve station-deny station-rooms station-bridge station-unbridge station-add-ship station-moderate station-unmoderate station-backup station-restore-test station-restore-reconcile station-alerts station-units station-units-remove wormhole-personas wormhole-key setup-agent check-agent setup-team check-team setup-tuning check-tuning tuning setup-peer check-peer home home-demo peer-bundle help setup setup-engram setup-lighthouse setup-atlas check check-engram check-lighthouse check-atlas check-integration check-research-tasks atlas atlas-demo chat serve sessions adna status stampede-config stampede-plan stampede-deploy stampede-simulate stampede research-poc research-task lead-probe

help:
	@echo "make setup-tuning / check-tuning  Install/check clinical and biotech LoRA tools"
	@echo "make setup-team / check-team      Install/check team mode (lead + Codex/Claude workers)"
	@echo "make setup-agent / check-agent    Install/check the ship agent (station client and tools)"
	@echo "make tuning             Dataset, model, train, evaluate and Slurm CLI; TUNING_ARGS sets options"
	@echo "make setup-peer / check-peer  Install/check the standalone personal home"
	@echo "make home-demo / home    Serve the fictional demo / ordinary peer on loopback"
	@echo "make dock DOCK_ARGS='--ship NAME'  Dock this machine's agent at the station (see CLAUDE.md)"
	@echo "make station-share-link   On the Pi: create the station's reusable Tailscale share link"
	@echo "make station-pending      On the Pi: list waiting dockings and access requests by short id"
	@echo "make station-approve ID=… On the Pi: approve one (APPROVER=andy); make station-deny ID=… refuses it"
	@echo "make station-rooms     On the Pi: list the rooms you own (APPROVER=andy) by short id, and which are bridged"
	@echo "make station-bridge ID=… On the Pi: bridge a room to Stanley's aDNA lattice (adds Wormhole); make station-unbridge ID=… stops"
	@echo "make station-add-ship ID=… SHIP=…  On the Pi: add one of your own ships to a room you own (APPROVER=andy)"
	@echo "make station-moderate ID=… GRANTEE=…  On the Pi: let someone moderate a room you own (APPROVER=andy)"
	@echo "make station-unmoderate GRANT=…  On the Pi: end a moderate grant by its short id"
	@echo "make station-backup [OUTPUT=…]  On the Pi: a checked copy of the station database (the rotation, or OUTPUT)"
	@echo "make station-restore-test [BACKUP=…]  On the Pi: boot a throwaway station from the newest copy (or BACKUP)"
	@echo "make station-restore-reconcile DB=… [REPLACED=…] [UNPAIR='id …']  On the Pi: runbook step 5 (docs/station-restore.md)"
	@echo "make station-alerts     On the Pi: show the alert queue and what is held back"
	@echo "make station-units      On the Pi: install the backup timers and the alert drop-ins; make station-units-remove undoes it"
	@echo "make wormhole-personas   On the Pi: refresh the aDNA persona map the wormhole bridge relays to"
	@echo "make wormhole-key KEY_FILE=…  On the Pi: authorize Stanley's sync key (a .pub file) for the station vault only"
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

setup: setup-engram setup-lighthouse setup-atlas setup-peer setup-tuning setup-team setup-agent

setup-engram:
	cd engram && uv sync --locked --extra dev --python "$(PYTHON_VERSION)"

setup-atlas:
	cd atlas && uv sync --locked --extra dev --extra mcp --python "$(PYTHON_VERSION)"

setup-lighthouse:
	cd lighthouse && pnpm install --frozen-lockfile
	cd lighthouse && pnpm build

check: check-engram check-lighthouse check-atlas check-integration check-research-tasks check-peer check-tuning check-team check-agent

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

setup-agent:
	cd agent && uv sync --locked --extra dev --python "$(PYTHON_VERSION)"

check-agent:
	cd agent && uv run --locked --extra dev python -m pytest -q -ra --tb=short

setup-peer:
	cd peer && uv sync --locked --python "$(PYTHON_VERSION)"

check-peer:
	cd peer && uv run --locked python -m pytest -q -ra --tb=short

home-demo:
	uv run --locked --project peer python -m superyak_peer demo --data-dir "$(HOME_DEMO_DATA)"
	@echo "Superyak demo: http://127.0.0.1:$(HOME_PORT)"
	uv run --locked --project peer python -m superyak_peer serve --local-demo --data-dir "$(HOME_DEMO_DATA)" --port "$(HOME_PORT)" $(HOME_ARGS)

dock:
	@$(AGENT_PYTHON) -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo 'superyak-agent needs Python 3.11 or newer. With uv installed: make dock AGENT_PYTHON="uv run --no-project --python 3.13 python" DOCK_ARGS=...'; exit 2; }
	$(AGENT_PYTHON) agent/run_agent.py dock --station "$(STATION)" --door "$(DOOR)" $(DOCK_ARGS)

station-share-link:
	python3 peer/scripts/share_link.py

station-pending:
	uv run --locked --project peer python -m superyak_peer station-pending --data-dir "$(STATION_DATA)" --as "$(APPROVER)"

station-approve station-deny:
	@test -n "$(ID)" || { echo 'Usage: make $@ ID=<short id from make station-pending> [APPROVER=andy]'; exit 2; }
	uv run --locked --project peer python -m superyak_peer $@ --data-dir "$(STATION_DATA)" --id "$(ID)" --as "$(APPROVER)"

station-rooms:
	uv run --locked --project peer python -m superyak_peer station-rooms --data-dir "$(STATION_DATA)" --as "$(APPROVER)"

station-bridge station-unbridge:
	@test -n "$(ID)" || { echo 'Usage: make $@ ID=<short id from make station-rooms> [APPROVER=andy]'; exit 2; }
	uv run --locked --project peer python -m superyak_peer $@ --data-dir "$(STATION_DATA)" --id "$(ID)" --as "$(APPROVER)"

station-add-ship:
	@test -n "$(ID)" && test -n "$(SHIP)" || { echo 'Usage: make station-add-ship ID=<short id from make station-rooms> SHIP=<ship username> [APPROVER=andy]'; exit 2; }
	uv run --locked --project peer python -m superyak_peer station-add-ship --data-dir "$(STATION_DATA)" --id "$(ID)" --ship "$(SHIP)" --as "$(APPROVER)"

station-moderate:
	@test -n "$(ID)" && test -n "$(GRANTEE)" || { echo 'Usage: make station-moderate ID=<short id from make station-rooms> GRANTEE=<username> [HOURS=720] [BUDGET=10] [ACTIONS=add,remove] [APPROVER=andy]'; exit 2; }
	uv run --locked --project peer python -m superyak_peer station-moderate --data-dir "$(STATION_DATA)" --id "$(ID)" --grantee "$(GRANTEE)" --hours "$(HOURS)" --budget "$(BUDGET)" --actions "$(ACTIONS)" --as "$(APPROVER)"

station-unmoderate:
	@test -n "$(GRANT)" || { echo 'Usage: make station-unmoderate GRANT=<grant short id> [APPROVER=andy]'; exit 2; }
	uv run --locked --project peer python -m superyak_peer station-unmoderate --data-dir "$(STATION_DATA)" --grant "$(GRANT)" --as "$(APPROVER)"

station-backup:
	uv run --locked --project peer python -m superyak_peer station-backup --data-dir "$(STATION_DATA)" --backup-dir "$(STATION_BACKUPS)"$(if $(OUTPUT), --output "$(OUTPUT)")

station-restore-test:
	uv run --locked --project peer python -m superyak_peer station-restore-test --backup-dir "$(STATION_BACKUPS)"$(if $(BACKUP), --backup "$(BACKUP)")

station-restore-reconcile:
	@test -n "$(DB)" || { echo 'Usage: make station-restore-reconcile DB=<the staged restored.sqlite3> [REPLACED=<the set-aside peer.sqlite3>] [UNPAIR="<peer id> …"]'; exit 2; }
	uv run --locked --project peer python -m superyak_peer station-restore-reconcile --db "$(DB)" --live-data-dir "$(STATION_DATA)"$(if $(REPLACED), --replaced "$(REPLACED)")$(foreach peer,$(UNPAIR), --unpair "$(peer)")

station-alerts:
	uv run --locked --project peer python -m superyak_peer station-alerts --data-dir "$(STATION_DATA)"

station-units:
	@test -f "$(STATION_DATA)/peer.sqlite3" || { echo 'No station database at $(STATION_DATA)/peer.sqlite3: make station-units runs on the station host only'; exit 2; }
	test -d "$(SYSTEMD_USER)" || install -d -m 755 "$(SYSTEMD_USER)"
	for unit in $(STATION_UNITS); do install -m 644 "peer/systemd/$$unit" "$(SYSTEMD_USER)/$$unit" || exit 1; done
	for service in $(ALERTED_SERVICES); do d="$(SYSTEMD_USER)/$$service.service.d"; { test -d "$$d" || install -d -m 755 "$$d"; } && install -m 644 peer/systemd/50-alerts.conf "$$d/50-alerts.conf" || exit 1; done
	systemctl --user daemon-reload
	systemctl --user enable --now superyak-backup.timer superyak-restore-test.timer

station-units-remove:
	-systemctl --user disable --now superyak-backup.timer superyak-restore-test.timer
	-systemctl --user stop superyak-backup.service superyak-restore-test.service
	-systemctl --user reset-failed superyak-backup.service superyak-restore-test.service 'superyak-alert@*'
	for unit in $(STATION_UNITS); do rm -f "$(SYSTEMD_USER)/$$unit"; done
	for service in $(ALERTED_SERVICES); do dir="$(SYSTEMD_USER)/$$service.service.d"; if [ -d "$$dir" ]; then rm -f "$$dir/50-alerts.conf"; rmdir "$$dir" 2>/dev/null || true; fi; done
	systemctl --user daemon-reload

wormhole-personas:
	python3 agent/run_agent.py wormhole-personas --out "$(WORMHOLE_HOME)/personas.json"

wormhole-key:
	@test -n "$(KEY_FILE)" || { echo "Usage: make wormhole-key KEY_FILE=<path to Stanley's sync key .pub file>"; exit 2; }
	python3 agent/run_agent.py wormhole-key --key-file "$(KEY_FILE)" --repo "$(STATION_VAULT_REPO)"

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
