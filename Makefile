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
USE ?=
LANE ?=
IMPRINTS ?= $(HOME)/.engram/imprints
REPLACED ?=
UNPAIR ?=
IMPRINT_ARGS ?=
PLAN ?=
START ?=
LIMIT ?=
DAYS ?=
ENGRAM_PROJECT_ROOT ?= $(CURDIR)
SUPERYAK_HOME ?= $(HOME)/.superyak
GRANTEE ?=
GRANT ?=
HOURS = 720
BUDGET = 10
ACTIONS = add,remove
# First rail (docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md): the peer a lessons target reads (the
# station's on the Pi; each other peer passes its own), the ship the origin's record names, and the lessons command.
LESSONS_DATA ?= $(STATION_DATA)
LESSONS_SHIP ?= rio-grande
CONFIRM ?=
OWNER ?=
FILE ?=
NEAR ?=
RESTART ?=
LESSON ?=
HOW ?=
HOOK ?=
LESSONS_UNITS := superyak-lessons-index.service superyak-lessons-index.timer
LESSONS = uv run --locked --project peer python -m superyak_peer.lessons
# Spec 2026-10-14 S8, S9: the files make station-units installs, and the services that get the alert drop-in: the five,
# and any project ship's watcher on this machine (a later one gets it when make station-units runs again).
STATION_UNITS := superyak-backup.service superyak-backup.timer superyak-restore-test.service superyak-restore-test.timer superyak-imprint-sweep.service superyak-imprint-sweep.timer superyak-alert@.service
ALERTED_SERVICES = superyak-lighthouse superyak-door superyak-ship superyak-odo superyak-wormhole $(patsubst %.service,%,$(notdir $(wildcard $(SYSTEMD_USER)/superyak-ship-*.service)))
HOME_DEMO_DATA ?= $(CURDIR)/.engram/home-demo
HOME_PORT ?= 7435
HOME_ARGS ?=
TUNING_ARGS ?= --help
TUNING_EXTRA ?= train

PEER_BUNDLE ?= $(CURDIR)/superyak-peer-source.tar.gz

.PHONY: imprint-plan imprint-read imprint-send imprint-status imprint-withdraw imprint-shorten imprint-verify station-imprints station-imprint-admit station-imprint-use station-imprint-use-run station-imprint-delete dock kick install-hooks station-share-link station-pending station-approve station-deny station-rooms station-bridge station-unbridge station-add-ship station-moderate station-unmoderate station-backup station-restore-test station-restore-reconcile station-alerts station-units station-units-remove wormhole-personas wormhole-key setup-agent check-agent setup-team check-team setup-tuning check-tuning tuning setup-peer check-peer home home-demo peer-bundle help setup setup-engram setup-lighthouse setup-atlas check check-engram check-lighthouse check-atlas check-integration check-research-tasks atlas atlas-demo chat serve sessions adna status stampede-config stampede-plan stampede-deploy stampede-simulate stampede research-poc research-task lead-probe station-lessons-room lessons-room lessons-where lessons-ship lessons-check lessons-list lesson-receipts lesson-segments lessons-units lessons-units-remove lessons-prompt-near lessons-timing lesson-repeat lesson-repeats

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
	@echo "make station-lessons-room ID=… [CONFIRM=…]  On the Pi: show, then record, the lessons room (first rail)"
	@echo "make lessons-room ID=…  On another peer: record the lessons room by its full id (LESSONS_DATA=this peer)"
	@echo "make lessons-where      This peer's lessons room, by its full id"
	@echo "make lessons-ship SHIP=… OWNER=…  Andy only, on another peer: a ship account with no key"
	@echo "make lessons-check SHIP=… FILE=…  Run this peer's checks on one lesson or retraction, without posting"
	@echo "make lessons-list       Each live lesson with its full id and the line that retracts it"
	@echo "make lesson-receipts / lesson-segments  This peer's receipts, newest first / its segments per pair of ships"
	@echo "make lesson-repeat LESSON=… HOW=receipt|read HOOK=on|off  Record a repeat after a seen lesson, for this peer's ship"
	@echo "make lesson-repeats     This peer's repeat records, newest first, verified and unverified apart"
	@echo "make lessons-units      Install the lessons index timer for LESSONS_DATA; make lessons-units-remove undoes it"
	@echo "make lessons-prompt-near NEAR=on|off  Let Near run at a prompt on this peer, or not (make lessons-timing says which)"
	@echo "make lessons-timing [RESTART=1]  Section 5's measure at the bound, through this machine's embedder"
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

# Refuse a push to the public repo of what the history scrub removed (docs/checklists.md, Before any push). Run it
# after this target is on main: the path is the checkout's own, and a missing hook fails open. The hook also needs
# ~/.superyak/scrub-terms (mode 0600, Andy's to place); without it every push to the public repo is refused.
install-hooks:
	git config core.hooksPath "$(CURDIR)/scripts/git-hooks"
	@echo 'pre-push hook installed for every worktree of this clone'

# Print one line per mention of this ship or reply to its post; run it under Claude Code's Monitor.
kick:
	@$(AGENT_PYTHON) -u agent/run_agent.py kick

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

station-deny:
	@test -n "$(ID)" || { echo 'Usage: make $@ ID=<short id from make station-pending> [APPROVER=andy]'; exit 2; }
	uv run --locked --project peer python -m superyak_peer $@ --data-dir "$(STATION_DATA)" --id "$(ID)" --as "$(APPROVER)" --imprints-dir "$(IMPRINTS)"

# The owner's imprint targets (I 13). They run on the owner's machine: the agent over the ship key, and the engram
# commands from engram/. imprint-plan passes the directory make ran in, so the default store (I 5.1) is found from
# there and not from engram/; --store in IMPRINT_ARGS still wins.
OWNER_AGENT = $(AGENT_PYTHON) agent/run_agent.py imprint
OWNER_ENGRAM = cd engram && uv run --locked python imprint.py
# Shell fragment: sets dirs to the local imprint folders (those sent from here) that start with $(ID), all when ID is empty.
OWNER_DIRS = dirs=$$(for d in "$(SUPERYAK_HOME)"/imprints/*/; do d=$${d%/}; test -f "$$d/send.json" && case "$${d\#\#*/}" in "$(ID)"*) echo "$$d";; esac; done)

imprint-plan:
	$(OWNER_AGENT) context
	$(OWNER_ENGRAM) plan --project-root "$(ENGRAM_PROJECT_ROOT)" $(IMPRINT_ARGS)

imprint-read:
	@test -n "$(PLAN)" || { echo 'Usage: make $@ PLAN=<first 4+ characters of a plan> [START=0 LIMIT=1]'; exit 2; }
	$(OWNER_ENGRAM) read --plan "$(PLAN)"$(if $(START), --start "$(START)")$(if $(LIMIT), --limit "$(LIMIT)")

imprint-send:
	@test -n "$(PLAN)" || { echo 'Usage: make $@ PLAN=<first 4+ characters of a plan>'; exit 2; }
	$(OWNER_ENGRAM) build --plan "$(PLAN)" --if-needed
	$(OWNER_AGENT) send --plan "$(PLAN)"

# What the station says, then each local imprint's receipts checked and entered in the use list. A failing step does not
# stop the others; the target fails if any did.
imprint-status:
	@$(OWNER_DIRS); fail=0; \
	test -z "$(ID)" -o -n "$$dirs" || { echo 'There is no imprint "$(ID)" sent from this machine.'; exit 2; }; \
	$(OWNER_AGENT) status$(if $(ID), --id "$(ID)") || fail=1; \
	for d in $$dirs; do \
	  uv run --locked --project peer python -m superyak_peer verify-imprint --dir "$$d" --home "$(SUPERYAK_HOME)" || fail=1; \
	  (cd engram && uv run --locked python imprint.py import-receipts --id "$$(basename "$$d")" --superyak-home "$(SUPERYAK_HOME)") || fail=1; \
	done; exit $$fail

imprint-withdraw:
	@test -n "$(ID)" || { echo 'Usage: make $@ ID=<first 4+ characters of the imprint id>'; exit 2; }
	$(OWNER_AGENT) withdraw --id "$(ID)"

imprint-shorten:
	@test -n "$(ID)" -a -n "$(DAYS)" || { echo 'Usage: make $@ ID=<first 4+ characters of the imprint id> DAYS=<days from now>'; exit 2; }
	$(OWNER_AGENT) shorten --id "$(ID)" --days "$(DAYS)"

imprint-verify:
	@test -n "$(ID)" || { echo 'Usage: make $@ ID=<first 4+ characters of the imprint id>'; exit 2; }
	@$(OWNER_DIRS); \
	n=$$(printf '%s' "$$dirs" | grep -c .); \
	[ "$$n" -eq 1 ] || { if [ "$$n" -eq 0 ]; then echo 'There is no imprint "$(ID)" sent from this machine.'; else echo 'More than one imprint starts with "$(ID)"; give more of its characters.'; fi; exit 2; }; \
	uv run --locked --project peer python -m superyak_peer verify-imprint --dir "$$dirs" --home "$(SUPERYAK_HOME)"

# Imprints (I 10, 12; R15, R20, R23, R29, D42). The peer's commands, the imprint job lock, and the one unit recipe.
PEER_CLI = uv run --locked --project peer python -m superyak_peer
PEER_IMPRINT_ARGS = --data-dir "$(STATION_DATA)" --as "$(APPROVER)" --imprints-dir "$(IMPRINTS)"
# Variables given on the command line (or the environment) go on to the unit's make; the defaults need no passing.
UNIT_VARS = $(foreach v,IMPRINTS STATION_DATA APPROVER,$(if $(filter-out file default undefined,$(origin $(v))),$(v)="$($(v))"))
# Shell fragment: sets lock to flock's status: 0 free, 1 held (util-linux), anything else (66: no imprints root) not takeable.
JOBS_LOCK_CHECK = flock -n "$(IMPRINTS)/.jobs.lock" true; lock=$$?

# The admission unit, written once; $(1) is the full imprint id (a shell expression).
define ADMISSION_UNIT
systemd-run --user --unit=superyak-imprint-admit-$(1) --collect -p MemoryMax=512M -p MemorySwapMax=0 -p LimitDATA=512M --setenv=OPENBLAS_NUM_THREADS=1 -p RuntimeMaxSec=3600 -p TimeoutStopSec=60 flock -n "$(IMPRINTS)/.jobs.lock" make -C "$(CURDIR)" $(UNIT_VARS) station-imprint-admit ID=$(1)
endef

station-approve:
	@test -n "$(ID)" || { echo 'Usage: make $@ ID=<short id from make station-pending> [APPROVER=andy]'; exit 2; }
	@out=$$($(PEER_CLI) station-approve --data-dir "$(STATION_DATA)" --id "$(ID)" --as "$(APPROVER)" --imprints-dir "$(IMPRINTS)"); status=$$?; \
	printf '%s\n' "$$out" | grep -v '^ADMIT: ' || true; \
	test $$status -eq 0 || exit $$status; \
	id=$$(printf '%s\n' "$$out" | sed -n 's/^ADMIT: \([0-9a-f-]\{36\}\)$$/\1/p' | head -n 1); \
	test -n "$$id" || exit 0; \
	short=$$(printf '%.4s' "$(ID)"); \
	$(JOBS_LOCK_CHECK); \
	if [ $$lock -eq 1 ]; then echo "Approved $$short, but another imprint job is running, so its admission waits. Run make station-imprint-admit when that job ends."; exit 1; \
	elif [ $$lock -ne 0 ]; then echo "Approved $$short, but the imprint job lock can't be taken: $$lock. Run make station-imprint-admit when that is fixed."; exit 1; fi; \
	$(call ADMISSION_UNIT,$$id) || { echo "Approved $$short, but its admission did not start. Run make station-imprint-admit."; exit 1; }

station-imprints:
	$(PEER_CLI) station-imprints $(PEER_IMPRINT_ARGS)

# With ID=<full imprint id>: begin, admit only when begin allows it (R24), then the sync whatever happened (this is what the
# unit runs). Without: start the unit for the first approved imprint whose admission never began (R29).
station-imprint-admit:
ifeq ($(ID),)
	@ids=$$($(PEER_CLI) station-imprints $(PEER_IMPRINT_ARGS) --awaiting-admission) || exit 1; \
	first=; more=0; \
	for id in $$ids; do \
	  test "$$(systemctl --user show -p LoadState --value superyak-imprint-admit-$$id)" = loaded && continue; \
	  if [ -z "$$first" ]; then first=$$id; else more=$$((more + 1)); fi; \
	done; \
	test -n "$$first" || { echo 'No approved imprint is waiting for its admission to start.'; exit 0; }; \
	$(JOBS_LOCK_CHECK); \
	if [ $$lock -eq 1 ]; then echo "Another imprint job is running on the station; try again when it ends."; exit 1; \
	elif [ $$lock -ne 0 ]; then echo "the imprint job lock can't be taken: $$lock"; exit 1; fi; \
	id=$$first; short=$$(printf '%.4s' "$$id"); \
	$(call ADMISSION_UNIT,$$id) || { echo "The admission of $$short did not start."; exit 1; }; \
	if [ $$more -eq 1 ]; then echo "Started the admission of $$short in the background; 1 more waits. Run make station-imprint-admit again."; \
	elif [ $$more -eq 0 ]; then echo "Started the admission of $$short in the background; no more wait."; \
	else echo "Started the admission of $$short in the background; $$more more wait. Run make station-imprint-admit again."; fi
else
	@$(PEER_CLI) station-imprint-admit-begin $(PEER_IMPRINT_ARGS) --id "$(ID)"; begin=$$?; admit=0; \
	if [ $$begin -eq 0 ]; then uv run --locked --project engram python engram/imprint.py admit --id "$(ID)" --imprints-dir "$(IMPRINTS)" --verify-cmd "uv run --locked --project $(CURDIR)/peer python -m superyak_peer verify-imprint" || admit=$$?; fi; \
	$(PEER_CLI) station-imprint-sync $(PEER_IMPRINT_ARGS); sync=$$?; \
	test $$begin -ne 0 && exit $$begin; test $$admit -ne 0 && exit $$admit; exit $$sync
endif

station-imprint-use:
	@test -n "$(ID)" -a -n "$(USE)" || { echo 'Usage: make $@ ID=<short id from make station-imprints> USE=trail-evaluation [LANE=<lane>]'; exit 2; }
	@id=$$($(PEER_CLI) station-imprints $(PEER_IMPRINT_ARGS) --resolve "$(ID)") || exit 2; \
	env=$$($(PEER_CLI) station-imprint-unit-env) || exit 2; \
	short=$$(printf '%.4s' "$$id"); \
	$(JOBS_LOCK_CHECK); \
	if [ $$lock -eq 1 ]; then echo "Another imprint job is running on the station; try again when it ends."; exit 3; \
	elif [ $$lock -ne 0 ]; then echo "the imprint job lock can't be taken: $$lock"; exit 1; fi; \
	eval "set -- $$env"; \
	if systemd-run --user --unit=superyak-imprint-use-$$id --collect -p MemoryMax=512M -p MemorySwapMax=0 -p LimitDATA=512M --setenv=OPENBLAS_NUM_THREADS=1 -p RuntimeMaxSec=1800 -p TimeoutStopSec=60 "$$@" flock -n "$(IMPRINTS)/.jobs.lock" make -C "$(CURDIR)" $(UNIT_VARS) station-imprint-use-run ID=$$id USE="$(USE)"$(if $(LANE), LANE="$(LANE)"); then \
	  echo "Started a use of $$short in the background; see make station-imprints."; \
	elif [ "$$(systemctl --user show -p LoadState --value superyak-imprint-use-$$id)" = loaded ]; then \
	  echo "A use of $$short is already running; see make station-imprints."; exit 3; \
	else echo "The use of $$short did not start."; exit 1; fi

# What the use unit runs (R23): the begin step prints the use id, imprint.py runs the use, the sync records how it ended.
station-imprint-use-run:
	@test -n "$(ID)" -a -n "$(USE)" || { echo 'Usage: make $@ ID=<full imprint id> USE=trail-evaluation [LANE=<lane>]'; exit 2; }
	@use_id=$$($(PEER_CLI) station-imprint-use-begin $(PEER_IMPRINT_ARGS) --id "$(ID)" --use "$(USE)"); begin=$$?; run=0; \
	if [ $$begin -eq 0 ]; then uv run --locked --project engram python engram/imprint.py use --id "$(ID)" --use-id "$$use_id" --imprints-dir "$(IMPRINTS)"$(if $(LANE), --lane "$(LANE)") || run=$$?; fi; \
	$(PEER_CLI) station-imprint-sync $(PEER_IMPRINT_ARGS); sync=$$?; \
	test $$begin -ne 0 && exit $$begin; test $$run -ne 0 && exit $$run; exit $$sync

station-imprint-delete:
	@test -n "$(ID)" || { echo 'Usage: make $@ ID=<short id from make station-imprints> [APPROVER=andy]'; exit 2; }
	$(PEER_CLI) station-imprint-delete $(PEER_IMPRINT_ARGS) --id "$(ID)"

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

station-lessons-room:
	@test -n "$(ID)" || { echo 'Usage: make station-lessons-room ID=<short id from make station-rooms> [CONFIRM=<the code it showed>] [LESSONS_SHIP=rio-grande] [APPROVER=andy]'; exit 2; }
	$(LESSONS) station-room --data-dir "$(STATION_DATA)" --id "$(ID)" --as "$(APPROVER)" --ship "$(LESSONS_SHIP)"$(if $(CONFIRM), --confirm "$(CONFIRM)")

lessons-room:
	@test -n "$(ID)" || { echo 'Usage: make lessons-room ID=<origin peer id>:<room id> [LESSONS_DATA=<this peer data dir>]'; exit 2; }
	$(LESSONS) room --data-dir "$(LESSONS_DATA)" --id "$(ID)"

lessons-where:
	$(LESSONS) where --data-dir "$(LESSONS_DATA)"

lessons-ship:
	@test -n "$(SHIP)" && test -n "$(OWNER)" || { echo 'Usage, Andy only: make lessons-ship SHIP=<ship username> OWNER=<his username on this peer> [LESSONS_DATA=…]'; exit 2; }
	$(LESSONS) ship --data-dir "$(LESSONS_DATA)" --username "$(SHIP)" --owner "$(OWNER)"

lessons-check:
	@test -n "$(SHIP)" && test -n "$(FILE)" || { echo 'Usage: make lessons-check SHIP=<ship username> FILE=<one lesson or retraction, no final newline> [LESSONS_DATA=…]'; exit 2; }
	$(LESSONS) check --data-dir "$(LESSONS_DATA)" --ship "$(SHIP)" < "$(FILE)"

lessons-list:
	$(LESSONS) list --data-dir "$(LESSONS_DATA)"

lesson-receipts:
	$(LESSONS) receipts --data-dir "$(LESSONS_DATA)"

lesson-segments:
	$(LESSONS) segments --data-dir "$(LESSONS_DATA)"

# First rail section 7.1: the ship is the one this peer's record names, never a variable.
lesson-repeat:
	@test -n "$(LESSON)" && test -n "$(HOW)" && test -n "$(HOOK)" || { echo 'Usage: make lesson-repeat LESSON=<full lesson id or short form> HOW=receipt|read HOOK=on|off [LESSONS_DATA=…]'; exit 2; }
	$(LESSONS) repeat --data-dir "$(LESSONS_DATA)" "$(LESSON)" --how "$(HOW)" --hook "$(HOOK)"

lesson-repeats:
	$(LESSONS) repeats --data-dir "$(LESSONS_DATA)"

# First rail section 4: the index timer on this peer. The directory is resolved in the shell: make's abspath splits a
# path on its spaces.
lessons-units:
	@test -f "$(LESSONS_DATA)/peer.sqlite3" || { echo 'No peer database at $(LESSONS_DATA)/peer.sqlite3: set LESSONS_DATA to this peer data directory'; exit 2; }
	test -d "$(SYSTEMD_USER)" || install -d -m 755 "$(SYSTEMD_USER)"
	for unit in $(LESSONS_UNITS); do install -m 644 "peer/systemd/$$unit" "$(SYSTEMD_USER)/$$unit" || exit 1; done
	test -d "$(HOME)/.config/superyak" || install -d -m 700 "$(HOME)/.config/superyak"
	printf 'SUPERYAK_LESSONS_DATA=%s\n' "$$(cd "$(LESSONS_DATA)" && pwd)" > "$(HOME)/.config/superyak/lessons.env"
	chmod 600 "$(HOME)/.config/superyak/lessons.env"
	systemctl --user daemon-reload
	systemctl --user enable --now superyak-lessons-index.timer

lessons-units-remove:
	-systemctl --user disable --now superyak-lessons-index.timer
	-systemctl --user stop superyak-lessons-index.service
	-systemctl --user reset-failed superyak-lessons-index.service
	for unit in $(LESSONS_UNITS); do rm -f "$(SYSTEMD_USER)/$$unit"; done
	rm -f "$(HOME)/.config/superyak/lessons.env"
	systemctl --user daemon-reload

lessons-prompt-near:
	@test "$(NEAR)" = on || test "$(NEAR)" = off || { echo 'Usage: make lessons-prompt-near NEAR=on|off [LESSONS_DATA=…]'; exit 2; }
	if [ "$(NEAR)" = off ]; then install -m 600 /dev/null "$(LESSONS_DATA)/lessons-prompt-near-off"; else rm -f "$(LESSONS_DATA)/lessons-prompt-near-off"; fi

lessons-timing:
	cd peer && .venv/bin/python -I scripts/lessons_timing.py$(if $(RESTART), --restart-unit superyak-embedder)

station-units:
	@test -f "$(STATION_DATA)/peer.sqlite3" || { echo 'No station database at $(STATION_DATA)/peer.sqlite3: make station-units runs on the station host only'; exit 2; }
	test -d "$(SYSTEMD_USER)" || install -d -m 755 "$(SYSTEMD_USER)"
	for unit in $(STATION_UNITS); do install -m 644 "peer/systemd/$$unit" "$(SYSTEMD_USER)/$$unit" || exit 1; done
	for service in $(ALERTED_SERVICES); do d="$(SYSTEMD_USER)/$$service.service.d"; { test -d "$$d" || install -d -m 755 "$$d"; } && install -m 644 peer/systemd/50-alerts.conf "$$d/50-alerts.conf" || exit 1; done
	systemctl --user daemon-reload
	systemctl --user enable --now superyak-backup.timer superyak-restore-test.timer superyak-imprint-sweep.timer

station-units-remove:
	-systemctl --user disable --now superyak-backup.timer superyak-restore-test.timer superyak-imprint-sweep.timer
	-systemctl --user stop superyak-backup.service superyak-restore-test.service superyak-imprint-sweep.service
	-systemctl --user reset-failed superyak-backup.service superyak-restore-test.service superyak-imprint-sweep.service 'superyak-alert@*'
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
