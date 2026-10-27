# Permissions by Place, Step 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On one machine, every use of a memory that leaves its store is decided by one model of places, people and
permission records, combined by intersection, with a receipt for each use, behind a gate that stays `off` until the
owner raises it with his own terminal yes.

**Architecture:** `engram/permissions.py` is the pure model: names, selectors, places, matching with history, `need`,
`decide` for single and bulk uses, boxes and the gluing check, the write rules and the words. It does no I/O.
`engram/permission_ledger.py` is the ledger file: an append-only hash-chained log, its table projections, one entry
point for every act, the gate and the houses. `engram/permission_uses.py` is the receipts file and its views.
`engram/permission_cli.py` is `engram-permissions`, acting only as the ledger owner. The daemon, the receivers, the
server, storage, federation, the policy generator and config gain small hooks. With no ledger the gate reads `off`
and they behave as today, with two fail-closed changes the spec makes in every mode (the daemon never serves
`group:outside-home`, and `share` refuses that name) and one requirement on small machines: the lighthouse daemon no
longer refuses to start without `ENGRAM_EMBEDDER_SOCKET` (R37); it loads the model in process and logs a warning, and
gate G0 still requires the socket and the embedder unit on small-hardware machines (spec 12.2), as `engram/CLAUDE.md` says.

**Tech Stack:** Python 3.12 or later (`requires-python = ">=3.12"` in engram's `pyproject.toml` and `uv.lock`; there is
no `.python-version`, so on this Pi uv picks its own 3.14.8, the only installed interpreter that fits). Standard library
and `sqlite3` only in the four new modules, pytest, uv. Run on the station's Raspberry Pi 5 (`smart`).

**Spec:** `docs/superpowers/specs/2026-10-25-permissions-by-place-design.md`, revision 6, at `e737e02`, cited below as
"P" with its section numbers. Also read: the contract `docs/city-rail-vision.md`; the interface table
`docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md` (rows cited as "row N"); the consolidation log
`docs/superpowers/reviews/2026-10-25-city-rail-consolidation.md`. The imprints spec
(`engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md`, revision 6, "I") is read only for U22's
agreement fixture and for what it reads from this plan's files.

**Scope.** P section 14's step 1 only. Build order across the three plans: this plan (permissions core) first, then
imprints, then trails step 1. This plan depends on no task of the other two. They depend on the interfaces listed in
"What the other plans use" below.

**Build branch.** A new worktree `/home/andy/superyak/.worktrees/permissions-core` on branch `permissions-core`, made
from `main` once the three specs and plans are merged there, or else from `trail-arrows-spec` at this plan's approved
commit, so the spec travels with the code. Every path below is relative to that worktree.

## Global Constraints

- **Step 1 only, off by default.** With no ledger file and no house carrying `permissions_ledger_id`, the effective
  gate is `off` (P 12.3, rule 1) and everything behaves as today, except that the daemon never serves
  `group:outside-home` and the `share` tool refuses that name (P 12.1, 12.3 "Off").
- **Nothing live.** No step deploys, restarts a service, posts to the station, or runs `engram-permissions` against a
  real `ENGRAM_HOME`. Every test sets `ENGRAM_HOME` (or the module's `ENGRAM_HOME`) to `tmp_path`. Deploy and live
  acts are gates in "Gates (for later)", never steps.
- **Purity.** `permissions.py` reads no file, opens no database, reads no clock and draws no randomness. Callers pass
  the state and the time.
- **Names, verbatim from the spec.** Modules `engram/permissions.py`, `engram/permission_ledger.py`,
  `engram/permission_uses.py`, `engram/permission_cli.py`; migration `engram/migrations/029_share_identity.sql`;
  command `engram-permissions`; files `ENGRAM_HOME/.engram/permissions.db` and
  `ENGRAM_HOME/.engram/permission-uses.db`; every table and column of P 5.5 and P 9.1, exactly; meta keys
  `ledger_id`, `schema_version` (value `1`), `owner`, `admins`, `gate`, `gate_raised`; the house meta key
  `permissions_ledger_id` and its value `unreadable`; gate values `off`, `shadow`, `enforce`, and the reading
  `closed`; actions `recall`, `read`, `inject_context`, `route`, `imprint`, in that order; kinds `memory`, `road`,
  `trail`; codes `UNKNOWN_REQUESTER`, `RETIRED`, `NO_LAYER`, `BOUND`, `DENIED`, `EXPIRED`, `GRANT_INVALID`,
  `NOT_YET`, `NO_ALLOW`, `LEGACY_DENY`; grant ops `share`, `deny`, `withdraw`, `shorten`, `narrow`, `collect`,
  `uncollect`; channels `terminal`, `tool`, `migration`; backings `person` and `grant:<id>`; id prefixes `r-`, `g-`,
  `p-`, `u-` + 32 lowercase hex; the reserved group `group:outside-home`; collections
  `collection:andy/legacy-commons` and `collection:andy/legacy-group-<g>`, where `andy` is the owner's handle that
  `migrate` takes from the login (R24); MCP tools `permissions(focus="uses" |
  "rules" | "proposals" | "grants", ...)` and `permit(op, ...)`; the read item member `permission`; the receipt
  extension key `engram:permissions`; the `PlaceRules` envelope of P 9.4 (`protocolVersion "0.1"`,
  `kind "PlaceRules"`, `payloadMediaType "application/vnd.engram.place-rules+json"`).
- **Constants (P 15), as `permissions.py` module constants:** `MAX_RECORDS_PER_LAYER = 256`; `MAX_AUDIENCE = 32`;
  `MAX_LIST = 64`; `MAX_MEMORIES = 512`; `MAX_PURPOSES = 16`; `MAX_SUBJECTS = 8`; `MAX_COLLECTION = 100_000`;
  collection name `[a-z][a-z0-9-]{0,79}`; `MAX_PLACES = 1024`; `MAX_PARENTS = 4`; `MAX_SEGMENTS = 8`;
  `MAX_PLACE_CHARS = 255`; `MAX_ANCESTORS = 16`; `MAX_LAYERS = 43`; `MAX_ANSWER_NAMES = 32`; `MAX_BULK_NAMED = 512`;
  `MAX_BULK_DERIVED = 100_000`; `MAX_BULK_MEMORIES = 100_000`; `MAX_COPY_CHAIN = 4`; `OUTSIDE_HOME_DAYS = 366`;
  `MAX_GRANT_LINKS = 3`; `MAX_GRANT_DEPTH = 2`; `MAX_GRANT_HOURS = 720`; `MAX_REPLACES = 16`; `PROPOSAL_DAYS = 7`;
  `BOX_CAP = 4096`; `JOINTS_PER_CHANGE = 64`; `SWEEP_PER_PASS = 256`; `CACHE_ENTRIES = 64`;
  `MAX_PLACEMENTS = 20_000`; `REBUILD_BUDGET_S = 2`; `BULK_BUDGET_S = 40`; `GUARD_RECEIPTS = 200`;
  `GUARD_SECONDS = 24 * 3600`; `GATE_HOUSES = 64`; `RETENTION_DAYS = 400`; `USE_LIST_ROWS = 200`;
  `ANNOTATION_CHARS = 240`; `ANNOTATION_NAME_CHARS = 32`; `CODE_CHARS = 6`; `SHORT_HEX = 4`;
  `RECEIPT_SHORT_HEX = 8`; `REASON_CHARS = 200`.
- **Times** are integer UTC seconds, half-open `[from, until)` (P14). `t` is the deciding party's clock, floored to a
  whole second, never a frame's `at` (P 6.1).
- **Writes.** Every ledger and receipts write runs inside `BEGIN IMMEDIATE`. Readers that must not write open with
  `mode=ro` and `PRAGMA query_only=ON` (P 5.5).
- **Hash chains.** `digest = sha256(prev_digest + "\n" + canonical_json(entry))`, the entry being the row without
  `prev_digest` and `digest`, the first `prev_digest` 64 zeros, `canonical_json` from `engram/lighthouse_protocol.py`
  (P 5.6). The receipts chain uses the same rule (P 9.1).
- **What a refusal shows.** The agent that asked never sees a refusal's code, layer, action or cited record, at the
  point of use, in a `remember` reply or in its receipts (P 9.2, 10, 12.2). The owner's list and the owner's CLI do.
- **Tests.** Each is named, written first and seen failing first (P 17). Property tests loop 500 cases each over
  `random.Random(f"{SEED}-<test>-{case}")` with `SEED = 20261025`, and every failure message names the seed and case.
  Their oracle is `engram/tests/permissions_oracle.py`, written from P sections 5 and 6, importing nothing from
  `permissions.py`. `engram_server_env` (and `seed`) are not in `conftest.py`: new test files import them from
  `tests.test_recall_margins`, as `tests/test_share_tools.py:4` does.
- **Test command on this Pi** (`smart`, Raspberry Pi 5, 16 GB; `/tmp` is on disk), from the build worktree's
  `engram/` directory:
  `PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider <tests>`.
  The first run creates the git-ignored `engram/.venv` from `uv.lock`. Each task writes it out in full.
- **Packaging.** Each new top-level module is added to `[tool.setuptools] py-modules` in `engram/pyproject.toml` in
  the task that creates it: `tests/test_packaging.py::test_wheel_contains_runtime_modules_and_assets` requires every
  `engram/*.py` in the wheel.
- **Existing tests stay unchanged, with one named exception.** No task edits an existing test file, except one line
  under R29: Task 23 changes `tests/test_packaging.py:225`, in `test_installed_wheel_starts_outside_checkout`, from
  `== 43` to `== 45`, because it adds the MCP tools `permit` and `permissions`. Nothing else in that file, and no other
  existing test file, changes. New tests go in new files.
- **Commits.** One per task, on `permissions-core` only, ending with the session's attribution line. No push, merge
  or deploy inside any task.

## Rulings

Choices the spec leaves to the builder (P 18) or does not fix. A reviewer checks each; Andy can veto any.

| # | Ruling | Why |
|---|---|---|
| R1 | `permissions.db` and `permission-uses.db` keep SQLite's default rollback journal (`journal_mode=DELETE`), with `busy_timeout` 5000 ms. A writer that dies mid-commit leaves a hot journal, which a `mode=ro` reader can't roll back (`SQLITE_READONLY_ROLLBACK`). Every reader then reads `closed` until a writer opens the file. The cause text says so and names a command that clears it: any writing open, such as `engram-permissions sweep`. | A `mode=ro` reader of a WAL file may need to create `-shm`; with a rollback journal the daemon's read-only open never writes a byte (U9). A hot journal fails closed. |
| R2 | `permissions.State` is built from the ledger tables of P 5.5 (`State.from_tables`), which is also F1's JSON form. `Ledger.state(seq)` filters the tables by their `*_seq` columns. | One form for the ledger, the tests and other implementations (F1). |
| R3 | Every act goes through one call, `Ledger.perform(act, *, actor, channel, now)`, which authorizes it with the pure `permissions.authorize` and then writes one log row and its projection. A refused act raises `RuleError`. | U4's table and U18's MCP refusals test one path. |
| R4 | A place's display name ("Public Health") is kept in its `register-place` log body and read into `State.names`. The default is the last segment. | P 7.6 and 8 word places by name, and P 5.5's `places` table has no name column. The log is the source of truth (P 5.6), so no column is added. |
| R5 | Gluing reports are computed, never stored. `perform` returns the reports for up to `JOINTS_PER_CHANGE` affected joint places in id order and names the rest; the CLI prints those the owner must see, and `check` recomputes. | P 8 says who is shown what, and P 5.5 has no table for reports. |
| R6 | A joint place is a proposal of kind `joint-place` whose body lists its parents. Each parent's steward signs it with `sign`; each signature is a `proposal-sign` log row. The place is registered when every parent has a signing steward. | P 4.4 ("waits as a proposal until all have"); P 11 signs one at a time. |
| R7 | Legacy layers (ConnectionPolicy) and layers kept outside a ledger (I's station ceiling) are passed to `decide` as callables. Neither writes a ledger row, and neither enters `until` or the horizon. | P 6.1, 6.3 item 4, 6.5 steps 6 and 7. |
| R8 | `Cited` has `records: tuple[str, ...]`. For a use on one memory it holds at most one id, and its JSON key is `record`. For a use on a road or trail, a bulk use, and a recall receipt, it holds every distinct record cited for that (layer, action), sorted, and its JSON key is `records`. A recall receipt's `until` and `horizon` are the earliest over what it returned. | P 6.4 "The decision" for bulk uses. A recall decides many placements. |
| R9 | Under `shadow`, a read item that both the legacy path and the new decision allow gains `permission`. An item the legacy path delivers and the new decision refuses gets none. | P 12.3's mode table says the annotation runs in shadow, and only an allowed item has an annotation (P 11). |
| R10 | The `remember` guard's use is: requester `agent:<instance>`, its one place, the delivery receipt's `object`, `copy` and `purpose`, action `imprint`, `t` = now. It writes one receipt for that decision. Its decision reads ledger layers only, no legacy layer. So the guard ignores a legacy `imprint` rule, allow or deny: the ConnectionPolicy schema accepts any action string (`engram/schemas/lighthouse/connection-policy.schema.json`, `actions`), so a hand-written one is possible, and it changes nothing here. The guard compares two digests with each delivery's `content_digest`: that of the content as passed, and that of the stripped content `remember` keeps (`engram/server.py:1849` strips before anything else). | P 10 says it decides `imprint` for the delivered item. The ConnectionPolicy files decide the crossing (`recall`, `read`, `inject_context`), which has already happened, and under `enforce` both legacy layers allowed that delivery. Today's generated files (`engram/policy_gen.py:75`) and E1's hand-written ones have no `imprint` rule: with them, every verbatim keep would be refused and P25's subjects never carried. This departs from P 6.3 item 4 for the guard alone; the re-check confirmed it, and gate G11 has the spec record it. Two digests, so surrounding whitespace doesn't let a verbatim copy through. |
| R11 | Under `closed`, the guard refuses a `remember` whose content digest matches a delivery receipt. If `permission-uses.db` exists and can't be read, it refuses every `remember` and names the cause, under `closed` and under `enforce` alike; under `shadow` it logs the cause, lets `remember` go on, and adds `"would_refuse": True`. With no receipts file it finds no delivery. | P 12.3: closed means fail closed, and the guard "refuses as under `enforce`". |
| R12 | The terminal code is 6 characters from `abcdefghjkmnpqrstuvwxyz23456789`, drawn by rejection sampling from `os.urandom`. Exit codes: 0 done, 1 refused by a rule, 3 no terminal or a wrong code. Code 2 stays argparse's usage error. | P 7.6 fixes the length and source only. A script can then tell a missing yes from a typo in the command. |
| R13 | An engram server's agent is `agent:<instance name>`, or `agent:default` when it has none, as `share` names its source (`engram/server.py:1976`). | `migrate` registers one agent per receiver name (P 12.3 step 2). |
| R14 | A row of `permission-uses.db` is imported when its `ledger_id` differs from the local ledger's `ledger_id`. Its station is that `ledger_id`, the station's peer id. | P 9.1 imported form item 4. No column is added. |
| R15 | `returned` is JSON. A recall: a sorted list of refs. An answer use on one road or trail: the sorted list of the memory refs it named, at most 32 (P 9.1). A named bulk use or an imported memory batch: `{"count": n, "sha256": "<hex of the sorted refs, joined by \n>"}`. A counted bulk use: `{"count": n}`, or SQL null for an imported row refused before a count existed. `cited` and `refusal` are JSON too (Task 14 pins their shape). | P 9.1 names the content, not the encoding. |
| R16 | Pseudonym salts are 16 bytes from `os.urandom` at place registration. | P 5.5 `pseudonym_salt BLOB NOT NULL`. |
| R17 | The raise writes `meta.permissions_ledger_id` into each house through plain `sqlite3` (not `Storage`), one `BEGIN IMMEDIATE` per house. | No vector extension or migration runs on a house the raise only marks. |
| R18 | The sweep is `sharing.sweep_placements`. The server runs it at startup and after `share` and `unshare`; the CLI runs it after each command that writes, and as `sweep`. | P 10; P 16 puts the sweep in `sharing.py` and `server.py`. |
| R19 | `PublisherDaemon` gains `engram_home`, passed by `main` and defaulting to the publishers' common root, so it can find the ledger and the receipts file. | P 5.5 fixes both paths under `ENGRAM_HOME`. |
| R20 | When the first lane note can't be written, `Storage.set_episode_lanes` raises `LaneNoteError`. `compress.py` catches it at its one call (`engram/compress.py:508-510`), keeps the old lane, logs a warning and goes on with the commit. The cluster's new semantic then takes the old lane too: `lane` is set back to `cluster.get("lane") or "personal"` before `add_semantic` (`:563`). | P 5.3: "the re-lane is refused". Compression should not fail as a whole for it. A summary is never in a wider lane than its evidence. |
| R21 | U24 runs only with `ENGRAM_PI_BUDGET=1`, so the default suite skips it. The reviewer runs it on the Pi (see "Verification before merge"). | P 17: "Marked slow, and run on the Pi". |
| R22 | `decide_bulk(..., group=True)` may decide objects with equal attributes once (P 6.4, "How it is computed"). U24 measures with `group=False`. | P 6.4: "With or without grouping". |
| R23 | U24's world pins its record mix (Task 31). Every memory has 8 subjects, so each decision meets 43 layers: 8 homes, 16 requester places, 16 holding places, 2 legacy layers and 1 restriction layer. Each of the 41 ledger layers holds 256 effective records. 32 pass the pre-filter for the measured (requester, place, action, purpose). The other 224 fail it, 56 each on `audience`, `requesters`, `actions` and `purposes`. Of the 32 that pass: 8 allows each name one of 8 collections that split the memories evenly (2,500 each for the rebuild), 8 allows each name a `memories` list of 512 refs, 8 allows name `lanes: ["work"]`, and 8 denies each name a `memories` list of 64 refs that hold no placed memory. So each placed memory, in each ledger layer, matches 1 collection allow, 0 or 1 list allow and 0 or 1 lane allow, and is checked against 8 denies that never match. Every placement is allowed, so no decision stops early. | P 12.2's 2 s is "with the pre-filter of 6.5". If every record passed it, the test would measure a case the spec doesn't budget. If none did, it would measure nothing. 32 of 256 is a calibration guess, like P 15's numbers. |
| R24 | `init` and `migrate` take the owner's handle from the Unix login name (`getpass.getuser()`). It must fit the person-handle grammar, or they refuse and say so. The words of the yes name it ("Create a ledger owned by person:andy"). `Ledger.create(engram_home, owner_handle, *, now)` keeps its argument for the API and the fixtures. On a machine whose login isn't `andy`, the owner is `person:<login>` and nothing chooses otherwise; `migrate` names its legacy collections `collection:<owner handle>/legacy-…` to match. G3 runs on the machine whose `ENGRAM_HOME` holds the published house the daemon serves, and Andy checks there that the words name `person:andy` before the yes. | P 7.6: no command takes an argument naming who acts. P 4.4: the owner is the person who runs `init`. The person sees the name before the yes. |
| R25 | Task 1 refuses a finite `layers`, `lanes`, `collections` or `memories` when `kinds` is `"*"`, as well as when it lists `road` or `trail`. So every allow that names a collection, a lane, a layer or memories lists `kinds: ["memory"]`. `migrate`'s legacy allows do (Task 28), and so do E1's R1 and every fixture's. | P 5.2 says it "for a road or trail". `"*"` covers roads and trails, so this reading is the one that never lets a memory-only dimension stand for a road. It is stricter than the letter, and a reviewer may relax it. |
| R26 | `permit` takes the seven grant ops with their named arguments. It also takes the other P 7.6 acts that are one `Act`: `grant`, `group`, `register-agent`, `put-agent`, `add-steward`, `register-place`, `add-parent`, `register-store`, `remove-subject` and `gate`, with `args` holding that act's arguments (Tasks 11 to 13). For an agent, `authorize` on channel `tool` files each widening act as a proposal for the ledger owner, with the full `Act` in its body. `sign`, with the yes, completes every proposal kind `perform` can file: record proposals (`allow`, `deny`, and a deny's `revoke`, `shorten` or `narrow`), `collect`, `joint-place`, and each act kind named here. `migrate` is not an op. It is a CLI run over the files on disk, not one act, so no proposal can hold its change. `permit(op="migrate")` returns an error naming `engram-permissions migrate` and writes nothing. The `gate` act takes only `mode`. `perform` computes the published house and the houses to mark from the ledger's own root when it applies the act, so no caller and no proposal body names them, and `sign` of a gate proposal prints them, with R27's list of houses lacking 029, before the yes (Tasks 13 and 26A). | P 7.6: the MCP tools can make none of these acts, and a tool call for one files a proposal. For `migrate` a proposal can't be written, and a refusal also makes nothing. The same reason keeps a gate act's houses out of its arguments: which houses exist is a fact of the files at the time of the yes. |
| R27 | Under `shadow` and `enforce`, the daemon serves nothing from a house whose `shared_memories` lacks `source_instance_id` or `record_id`, or that has no `shared_memories_changes` table. It warns, naming the house and saying an engram server must open it once. Under `off` such a house serves as today. `gate` (Task 27) and `migrate` (Task 28) list such houses before the yes. | Every real house predates 029, and neither the raise (R17) nor the daemon (`engram/lighthouse_daemon.py:82-113`) migrates. Without 029 a placement has no object and the cache has no counter, so the new decision can't be made. Failing closed shows the house; serving it by the legacy path alone under `shadow` would hide it from `report shadow`. |
| R28 | The `permissions` tool answers in full only an agent whose registered principal is `meta.owner`. Any other registered agent gets its own `Uses.agent_view` for `focus="uses"`, and `{"error": "only agents acting for the ledger owner can read this"}` for the other focuses. An unregistered agent gets that error for every focus. P 9.2's subject row is not offered through the tool in step 1. | P 9.2 and AS2: the owner's list shows refusal layers, which can name a person. Task 25's `keep_world` runs a server as `agent:ph-coordinator`. |
| R29 | Task 23 changes one line of an existing test: `tests/test_packaging.py:225`, `assert len(server.mcp._tool_manager.list_tools()) == 43`, becomes `== 45`. It is the only edit to an existing test file in this plan. Global Constraints and Verification step 2 name it. | `server.py` has 43 `@_server_tool()` today, and Task 23 decorates `permit` and `permissions`, which P 12.1 and 9.3 name as MCP tools. The test counts the tools a server registers at `_init()`, so a correct build changes the number. The trails plan adds none at import and says so. |
| R30 | The daemon's two legacy layers answer per action as today's code does. The publisher's layer answers every action of `need` with this frame's one publisher decision: the policy decided once for `recall` (`engram/lighthouse_daemon.py:362`) or for `read` (`:402`). The receiver's layer decides each action of `need` with its own `PolicyRequest`, as the receiver does (`engram/neighbors.py:53-60`, asked for `recall`, `read` and `inject_context` at `:120` and `:138`). | P 12.2: the publisher's decision "is made once per frame". `policy_gen.py:75` and E1's publisher policy allow only `recall` and `read`, so asking the publisher's policy about `inject_context` would refuse every delivery under `enforce`, E1's use 1 among them, and under `shadow` every receipt would read as refused by the legacy path, so `report shadow` would list no disagreement. |
| R31 | The daemon's eligible-set cache is keyed by (house, agent, place, purpose, action), at most `CACHE_ENTRIES` entries over all houses together. | P 12.2 keys it per (agent, place, purpose, action) for the placements of one house. One daemon serves several publishers, and an entry's validity reads that house's `placement_changes()`, so without the house in the key, an entry built for one house would be checked against another's counter and served for it. |
| R32 | `effective_gate` leaves out a served path that is not a file. The daemon computes the gate after today's publisher check (`engram/lighthouse_daemon.py:331-337`), so the house a frame reads from is always a file and always in the gate. | P 12.3 defines a house as an engram store at those paths. A configured publisher whose `graph.db` doesn't exist yet serves nothing (`PUBLISHER_UNAVAILABLE`, as today); read as a house with no id it would close every frame for every publisher. |
| R33 | `Uses.place_view(state, P)` covers uses at P and at every place P dominates, and uses of copies they hold, and gives every pseudonym with P's salt. | P 9.2 gives a place's receipts to its stewards "and the stewards of every place that dominates it", each subject as "the pseudonym this view gives". One salt per view keeps a person's pseudonym stable within a view and different across places (U8), and E1 use 14 has public health's stewards see clinic-3's uses. |
| R34 | An agent's proposals and child grants are bounded (the final review's I1): at most `MAX_OPEN_PROPOSALS_PER_AGENT = 64` open proposals (pending and not expired) per filer, `MAX_OPEN_PROPOSALS = 1024` per ledger, and `MAX_CHILD_GRANTS = 64` live (not revoked, not expired) child grants per parent grant. Each is counted inside the write's `BEGIN IMMEDIATE`, as the records bound is, and a refusal names the bound. A State reads proposals on demand (`ProposalMap`) and holds none. | Spec 15 bounds records, caches and sets, not proposals, and an agent can file proposals and issue child grants with no yes. 300 proposals of 512 refs added 4.1 MB to every State, so an agent in a retry loop could push the daemon's two States past 512 MB. No decision reads a proposal. The numbers are the controller's; gate G12 has the spec record them. |
| R35 | An eligible set's horizon also holds every time after its `at` at which a row it reads by its log time comes into or goes out of force: the requester's places and group memberships, and each placed object's memberships, subject rows (up its `copies` chain) and lane notes (the final review's M2); and the earliest anchor after `at` of an unrevoked record, of any layer or effect, made once per (State, t) (the re-review's M2: a back-dated deny, a `--from` in the past or a deny proposal signed after it was filed, counts only from its anchor). A decision's own horizon is unchanged. | After a backward clock step, a row written by the faster clock does not count at the daemon's t, and the cache would serve that decision until the next ledger write. 6.5 step 7 allows terms beyond its reading that are only ever earlier ones. Every decision stays as 5.3 reads it, so the oracle, the gluing check and F1 are unchanged; the cache ends when the row starts to count. |
| R36 | Under `shadow`, a read the publisher's audience check refused keeps the ledger's own verdict and refusal on its receipt, and records the audience refusal as a `cited` entry of its own: `{"layer": "publisher", "kind": "audience", "action": "inject_context", "verdict": "deny"}` (the final review's M8). `report shadow` reads it there, and still reads a receipt written before as it did. | One field held two refusals: when both refused, the ledger's code was lost. Gate G12 has the spec's 9.1 name the entry. |
| R37 | The lighthouse daemon does not refuse to start without `ENGRAM_EMBEDDER_SOCKET` (the controller's ruling, "G0 on the Mac"). Without it, `main` embeds in process through `create_embedding_provider()`, as main does, and logs a warning that names `scripts/superyak-embedder.service` and says the model is loaded in this process. With it, `RemoteEmbedProvider` as before. G0 stays the deploy item for small-hardware machines. | "Gate off behaves as before" (`engram/CLAUDE.md`) must hold on every machine. Andy's Mac runs the daemon under launchd with KeepAlive and a 10-second throttle, with no socket and no shared embedder; with the refusal, a pull of this branch would make it exit 2 and relaunch every 10 s for good. Cost if wrong: a machine that should run the shared embedder and does not loads a second model in the daemon (about 1.5 GB more), which the Pi cannot hold; the warning in the log and G0 are the guard. |
| R38 | `decide` keeps its own reading of rows logged after `at` (Tardis's advisory review, T11): a co-subject row or a placement removal already in the State but logged after `at` is not in force at `at`, so a decision at `at` neither adds that subject nor drops that placement. | 5.3 and 6.3 read every row by its log time, and `decide(u, σ, t)` must not depend on what σ learned after t, or L8 and F1's agreement fail. The cache side is closed by R35 (M2): an eligible set ends when such a row starts to count. Cost if wrong: a caller that decides at a t behind the ledger's last write (a backward clock step) gets the earlier answer for up to the gap; the daemon's cache ends at the row's time, and every other caller decides at its own now. |
| R39 | `Uses.append_imported` stays as it is (T12): it accepts an `inject_context` row with a content digest and the local ledger id, which `deliveries()` and `owner_list` then read as local. | It has no production caller: nothing imports receipts yet (the imprints spec's transport is later work). Cost if wrong: the first caller could make the `remember` guard treat a foreign delivery as this machine's, and count it as local; that caller's task must refuse rows that carry the local ledger id or a content digest, or mark them so both views skip them. |
| R40 | `migrate` keeps registering every rule's publishers as home agents, deny rules' included (T15). | Registering an agent grants nothing by itself: migrate's allows name the audiences the legacy shares had, and delivery still applies the legacy ConnectionPolicy check, met with the ledger's (12.1), so a publisher a deny rule names is still refused there. Cost if wrong: an allow the person later writes for `self` in his home reaches that publisher in the ledger's layers, and only the legacy deny rule, while the policy keeps it, still refuses the delivery; `engram-permissions agent unplace` takes such an agent out of his home. |
| R41 | A decision's `until` and effective end follow a grant-backed membership's envelopes (Tardis's T1): `_route` takes, for each selector naming collections, the latest-ending route by which the object is there, a route being a grant-backed membership and, for each envelope in its grant chain that names collections, the route there (with that membership assumed, as `_membership_counts` does). Every row on the route is a membership the use matched through (6.5 step 5), so `EXPIRED` and `GRANT_INVALID` read its chain too. The horizon reads more: the expiry after t of the grant chain behind every grant-backed membership of a needed object, in whatever collection. The oracle's `candidate_terms` reads the same routes. `random_world(nested=True)` builds the nesting; the reference test draws a083a96's worlds (`nested=False`) and lets a horizon move earlier only to one of those expiries (`t1_terms`). | Reading every membership in `until` would end it, and say `EXPIRED`, for a grant the allow never relied on, which the codes' table does not allow; the horizon may hold terms beyond the spec's reading that are only ever earlier (6.5 step 7), and reading every row keeps it one pass per object. Cost if wrong: an eligible set holding an object with grant-backed memberships in collections no layer names ends sooner and is rebuilt; nothing is served past a change. |
| R42 | A narrowing or shortening must also state nothing wider than the record it replaces (Tardis's T3): each selector field within the old one's as `selector_within` reads an envelope, and its interval within the old one's, besides the region check. `share_cover`, `placement_still_counts` and `relink_cover` read a record with its `replaces` chain, each link's interval, actions, object dimensions and audience, as `decide` does. An agent's narrowing grant meets a record (`_meets_envelope`) where the record and its whole chain meet the envelope, not the record's own selector alone. | The region check compares the sets of the moment: when no agent works in the audience yet, or the collection is empty, both regions are empty and any replacement passed, so `place show` and `share` read a wider record than `decide`, which intersects the chain (P8). Reading the envelope test through the chain is the narrower of the two readings of "the same rule"; reading stated fields there would let an agent touch records whose region is empty now. Cost if wrong: a replacement that only reorders or renames an audience entry to an equal reach (`self` for the home place) is refused, and the person writes it as a revoke and a new allow. |
| R43 | When a ledger file exists, `shares` lists placements only to an agent acting for its owner, under every gate, `off` included, as `permissions(focus="rules")` does; any other agent gets `only agents acting for the ledger owner can read this`. If the ledger cannot be read, `shares` lists nothing, and with no ledger but a closed gate it lists nothing either. `unshare` refuses an agent that the readable ledger says does not act for the owner, before it looks for the share; with no ledger, or one that cannot be read, it works as before (U11: removing a placement only narrows). With no ledger at all, both are main's (Tardis's T5). | A placement's reason, audience and digest can name a person and what is shared about them (P23), and `rules` was already owner-only. Under `off` a ledger still names the owner, so the check costs nothing there. Cost if wrong: on a machine whose ledger is `off`, an agent not registered as the owner's can no longer list or remove placements, which `engram/CLAUDE.md`'s "with an `off` gate engram behaves as before" does not yet say (gate G13); the person registers the agent (`engram-permissions agent add <name> --acts-for person:<owner>`) or runs the tools from an owner's agent. |
| R44 | An object whose store has no `stores` row has no subject in a decision (Tardis's T6; P 6.3 item 1, P32): `_decision_subjects` gives it none, whatever co-subject or `copies` rows name it, so the decision is refused with `NO_LAYER` at that object, and a road or trail it is named by gets none from it (it is decided as its own need, and refused there). `subjects_of` keeps reading such an object's rows where it is the source of another copy, and `record_copy` still carries them. `record_copy` refuses a copy into a store with no `stores` row. The oracle reads the same rule. The reference test lets a decision that needs such an object become that refusal, and compares an eligible set's other placements with the reference's. | P32 says such an object has no subject. Dropping its rows everywhere would take subjects away from the copies made of it, which widens; the decision is the one place the rule refuses. Cost if wrong: a memory written into a store before the store is registered is refused until the person registers it (`engram-permissions store add`); genome sync skips, and `remember` refuses, a copy into such a store until then. |
| R45 | The retention fold counts only this ledger's own uses (Tardis's T7): a shadow receipt, a recall that returned nothing, and a row whose `ledger_id` is not the local ledger's (an imported station receipt) are verified, deleted with their batch and counted nowhere. Of "fold imported rows apart, or not at all", it takes not at all. `Uses.fold` takes the local `ledger_id`; the server and `run_sweep` read it from the ledger. | Under shadow the legacy path decided the use, so a shadow refusal is no refusal, and a recall of nothing is no use of any memory (9.1, 9.3), yet both became permanent counts. 9.1's `uses_monthly` has no column that keeps imported rows apart, so folding them apart would change the schema; the station keeps its own receipts of them (imprints spec, D32). Cost if wrong: after 400 days, the owner's monthly counts hold no station imports and no shadow-period decisions; if Andy wants those, a column and its migration add them later. |

## Carried items

Items from the consolidation log, and the reviews it answers, that belong to this spec. Each is a task or a gate.

| Item | What it asks | Where |
|---|---|---|
| YN6 | P 9.1 item 1 says "three for an admission", but `uses.purpose` is NOT NULL, so an imported row is per action **and purpose**. With `route`, an admission has `recall` and `read` for two purposes, and three actions on roads and trails. | Task 15: `uses --action` and `--purpose` count imported rows per (action, purpose), tested on that admission. Gate G8: the wording fix in P 9.1 for the spec's next revision. No verdict changes. |
| XS2, P's side | An imported counted row refused before the station counted roads and trails holds `returned` null (P 9.1 item 3). | Task 14 accepts it in `append_imported`; Task 15 lists and counts it, showing "not counted". |
| XM1, P's side | U22's agreement test must hold on a fixture with two owners, one of them the operator. | Task 7, in `test_u22_imprints_spec_need_agrees`. |
| XN3 | U24's trails have 512 touches each. | Task 31. |
| XN6 | Which item of `Req` holds the station ceiling in a step-2 ledger. | Gate G9: P 14 step 2's to say. Not built. |
| BS1, BN3, BN4 | What a refused `remember`, a refused agent acting for the owner, and a bulk refusal show. | Tasks 15 and 25 (U8, U17). |
| BS2 | At most 100,000 memories named by one bulk use's roads and trails. | Task 7 (U22). |
| BS3 | Step 2 decides what a subject sees of another subject's home in receipts. | Task 15 builds the view as written; Gate G9. |
| AN4 | `engram/CLAUDE.md` gains the rule that agents never run an `engram-permissions` command that writes. | Task 32. |
| AN5 | `config.py` warns about a `[permissions]` section. | Task 18 (U16). |
| Not this spec's | YS1, YN1 to YN5, YN7, XN2, I's CN7 (second half) and CN8, T's FS1 and FN1 to FN3. | The imprints and trails plans. Listed so a reviewer can see none was dropped here. |

## Review Focus

Inputs and failures the spec implies that no test in P 17 exercises, most likely first. Each has a test in the task
named.

1. **A receipt that can't be written.** Under `enforce`, if `permission-uses.db` can't be written, no read item
   carries content, a recall returns no candidates, and the daemon warns. No use without its receipt (vision
   principle 5). Under `shadow` both deliver by the legacy path and the daemon warns. Task 20,
   `test_rf1_no_receipt_no_content`.
2. **A ledger locked by a writer.** With R1's rollback journal, a writer that holds only `BEGIN IMMEDIATE` (a RESERVED
   lock) does not block readers: they read the last committed state, which is correct. A writer that holds an
   exclusive lock, as a commit or a cache spill takes, does. When that lock outlasts the daemon's busy timeout, the
   daemon reads `closed` and serves nothing. It never reads `off` and never serves a cached allow. Task 19,
   `test_rf2_locked_ledger_reads_closed`.
3. **A clock that steps backwards.** A cached eligible set computed at t₁ is not served at t₀ < t₁, where a record
   that starts between them must not count yet. Task 21, `test_rf3_cache_not_served_before_its_time`.
4. **Ids that print alike.** A trailing newline, an uppercase letter or a non-ASCII look-alike in any id is refused
   (`\Z` and ASCII-only patterns), so two ids never look the same in the words a person confirms. Task 1,
   `test_rf4_ids_refuse_newline_case_and_non_ascii`.
5. **Two writers at once.** A CLI command and a server's lane note appended at the same moment keep gapless `seq`s, one
   valid chain, and `rebuild` gives the same tables. Task 10, `test_rf5_two_writers_keep_one_chain`.

## File Structure

| File | Responsibility |
|---|---|
| `engram/permissions.py` (new) | The pure model (P 16 row 1). Tasks 1 to 9 (with 5A), 20, 21, 23 (`share_cover`). |
| `engram/permission_ledger.py` (new) | The ledger file, `perform`, the gate and houses, `PlaceRules`, lane notes, kept-copy rows, reads for the other plans. Tasks 10 to 13, 16, 17. |
| `engram/permission_uses.py` (new) | The receipts file, its writers and views, pseudonyms, the fold. Tasks 14, 15. |
| `engram/permission_cli.py` (new) | `engram-permissions`. Tasks 26, 26A, 27, 28. |
| `engram/migrations/029_share_identity.sql` (new) | Two `shared_memories` columns and the change counter. Task 16. |
| `engram/storage.py` | 029's step that marks a new house; the lane listener; calls run when the outermost transaction commits or rolls back. Tasks 16, 17. |
| `engram/compress.py` | Catches `LaneNoteError` at its one re-lane. Task 17. |
| `engram/config.py` | The `[permissions]` warning. Task 18. |
| `engram/policy_gen.py` | Refuses a group named `outside-home`. Task 18. |
| `engram/sharing.py` | `source_instance_id`, `record_id`, the placement bound, `sweep_placements`. Tasks 23, 24. |
| `engram/lighthouse_daemon.py` | The gate, the outside-home rule, decisions, receipts, the annotation, the cache. Tasks 19 to 21. |
| `engram/lighthouse_client.py`, `engram/neighbors.py`, `engram/context_lighthouse.py` | Accept and pass `permission`; the receipt extension. Task 22. |
| `engram/server.py` | `share`, `permit`, `permissions`, the sweep calls, the lane listener, the `remember` guard, the gate over the published house. Tasks 17, 18, 23 to 25. |
| `engram/federation.py` | Kept-copy subjects for synced genome episodes. Task 25. |
| `engram/pyproject.toml` | Four `py-modules` entries and the `engram-permissions` script. Tasks 1, 10, 14, 26. |
| `engram/tests/test_packaging.py` | One line: the MCP tool count at `:225`, 43 to 45 (R29). Task 23. The only existing test file this plan changes. |
| `engram/CLAUDE.md` | The "Permissions" paragraph, Key Files rows and the agents rule. Task 32. |
| `engram/tests/permissions_support.py` (new) | Test builders: `World`, `T`, `use`, `random_world`. Task 2, grown by later tasks. |
| `engram/tests/permissions_oracle.py` (new) | The brute-force oracle. Task 5A, boxes added in Task 8. |
| `engram/tests/test_permissions_*.py` (new), `engram/tests/fixtures/permissions/` (new) | P 17's tests. |

**Note (the final review's I3, 2026-10-27): what else the branch's diff holds.** Verification step 2 reads "File
Structure" as this table and this note. The build's later tasks added test support files the table does not name:

| File | Task |
|---|---|
| `engram/tests/permissions_memory_support.py` (new) | The small-hardware (SH) tasks: the lazy State's helpers (`38ef58f`). |
| `engram/tests/test_store_digest_chunks.py` (new) | SH: `store_digest` hashes a store in chunks (`0e4ae36`). |
| `engram/tests/permissions_reference.py` (new) | Perf P0: the frozen copy of `a083a96`'s decision code that every later decision is checked against (`06ba849`). |
| `engram/tests/permissions_budget_core.py` (new) | U24 (Task 31, revision 8): what the generated world and the probes share (`31dd1c3`). |
| `engram/tests/permissions_budget_ledger.py`, `engram/tests/pi_budget_probe.py` (new) | U24: the reference ledger and the per-process memory probes (`e34400f`). |

The diff also holds documents that are not the build's. The specs, plans and reviews of the city rail work came with
the branch's start and with its two merges of `trail-arrows-spec`: `6610215` (revision 7, for the SH tasks) and
`8e2a075` (revision 8, for the performance tasks, which brought `docs/superpowers/reviews/2026-10-27-permissions-rev8-review.md`
and revision 8 of the spec). They are: `docs/city-rail-vision.md`; `docs/superpowers/specs/2026-10-25-permissions-by-place-design.md`; this plan;
`docs/superpowers/reviews/2026-10-25-{city-rail-consolidation,city-rail-interfaces,permissions-by-place-plan-review,permissions-by-place-spec-review,small-hardware-imprints-review,small-hardware-permissions-review,small-hardware-trails-review,store-imprint-plan-review,store-imprint-spec-review,trail-arrows-plan-review,trail-arrows-rev4-spec-review,trail-arrows-spec-review}.md`;
and `engram/docs/superpowers/{plans,specs}/2026-10-25-{store-imprint,trail-arrows}{,-design}.md` (the imprints and
trails plans and specs). The final review's fixes added one test file, `engram/tests/test_permissions_review_fixes.py`,
which the `test_permissions_*.py` row covers.

## What the other plans use

Kept stable after this plan merges. A change to any of these is a change to the imprints or trails plan too.

- **Trails step 1** reads `stores.owner` for a store's `instance_id` from `ENGRAM_HOME/.engram/permissions.db`, opened
  `mode=ro` and `query_only` (T 6.5). It may call `Ledger.open_read_only(engram_home)` and
  `Ledger.store_row(instance_id) -> dict | None` (Tasks 10, 11). The `stores` table is exactly P 5.5's.
- **Imprints** reads, on the source machine: `Ledger.store_row(instance_id)` for D37 and
  `Ledger.cosubjects(ref, at=None) -> frozenset[str]` for `cosubjects(m)` (I 5.2), both Task 11. Since the final
  review's M6, `cosubjects` follows copies: it is `subjects_of(state, ref, at)` (the ref's own subject rows and its
  sources' up the `copies` chain, at most `MAX_COPY_CHAIN` links) less the ref's default subject, its store's owner
  (not for an imprint store). `at` None reads every subject row not removed; a time reads those in force then. It
  builds a State per call, and raises `RuleError` on a malformed ref. The imprints plan's Task 8 test
  `test_a_copy_carries_what_its_source_gains_after_the_copy` asserts `led.cosubjects(copy) == frozenset()` (the
  copy's own rows only); at the rebase it changes to `{"person:jenn"}`, equal to its `cosubjects_of`. It also reads
  `Ledger.latest_lane_note(ref) -> str | None` for `pending(m)` (I 5.2), Task 17. It writes imported receipts with `Uses.append_imported(row, subjects)` (Task 14), and its
  `import-receipts` test runs `Uses.owner_list` (Task 15). It names copies `imprint:<station peer id>/<imprint id>`,
  which `permissions.parse_copy_ref` accepts (Task 1).
- **Both** may run `permissions.decide` and `permissions.decide_bulk` on a `State` (Tasks 5 to 7).
- **The trails plan's fixtures** also use `permission_ledger.ledger_path(engram_home)`, `Ledger.create(engram_home,
  owner_handle, *, now)`, `Ledger.close()` (Task 10), `Ledger.perform(act, *, actor, channel, now)` (Task 11) and
  `permissions.Act(kind, args)` (Task 9).
- **The imprints plan** also uses `permissions.State.from_tables(tables, *, seq, seq_at, meta, names=None)` (R2,
  Task 2), `engram/tests/permissions_support.World` (Task 2), and `permission_uses.UseRow` and `Uses.open(engram_home)`
  (Task 14).
- **Both** depend on R15's encoding of `returned`, in particular a named batch's `{"count": n, "sha256": h}`, where h
  is the lowercase hex SHA-256 of the sorted refs joined by `"\n"` (no trailing newline), UTF-8.
- **The imprints plan changes two of them**, in its Task 45: `Uses.owner_list` (Task 15) gains `copies: Sequence[dict]
  = ()`, whose lines it puts first, and the `uses` command (Task 27) passes `imprint_copies.copies_held(...)`. Both stay
  backward compatible: with no `copies`, the list is this plan's.
- **Both build after this plan's R29**, so `tests/test_packaging.py:225` reads `== 45` when they start. The trails plan
  adds no tool at import, and the imprints plan adds none.

---

### Task 1: Names, ids and selectors

**Files:**
- Create: `engram/permissions.py`
- Modify: `engram/pyproject.toml` (`py-modules` gains `"permissions"`)
- Test: `engram/tests/test_permissions_names.py`

**Interfaces:**
- Consumes: `lighthouse_protocol.canonical_json`.
- Produces:
  - the constants of Global Constraints; `STAR = "*"`; `ACTIONS`; `KINDS`; `RESERVED_GROUP = "group:outside-home"`;
  - `class RuleError(ValueError)`, `RuleError(rule: str, message: str)`, with `.rule` naming the spec rule (for
    example `"4.1 place grammar"`, `"5.4 outside-home lifetime"`);
  - `check_id(kind: str, value: str) -> str` for kinds `person`, `agent`, `place`, `group`, `collection`, `record`,
    `grant`, `proposal`, `use`; it returns the value or raises `RuleError`;
  - `home_of(person: str) -> str` (`person:andy` → `place:home/andy`); `person_of_home(place: str) -> str | None`;
  - `ObjectRef`, a `NamedTuple` `(kind: str, instance_id: str, layer: str | None, local_id: str)`, and
    `parse_object_ref(ref: str) -> ObjectRef` for `mem:`, `road:` and `trail:` refs (P 4.1);
  - `CopyRef`, a `NamedTuple` `(kind: str, instance_id: str, station: str | None)`, and
    `parse_copy_ref(ref: str) -> CopyRef` for `store:<instance_id>` and `imprint:<station peer id>/<imprint id>`;
  - `Selector`, a frozen dataclass with fields `audience`, `requesters`, `kinds`, `stores`, `layers`, `lanes`,
    `collections`, `memories`, `actions`, `purposes`, each a sorted `tuple[str, ...]` or `STAR`;
  - `parse_selector(doc: dict | str) -> Selector`; `selector_json(sel: Selector) -> str` (canonical JSON, P 5.2);
  - `resolve_prefix(ids: Iterable[str], given: str) -> str`; `short_id(full: str) -> str` (`#` + 4 hex);
    `receipt_short(full: str) -> str` (`#` + 8 hex).

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from permissions import (RuleError, STAR, check_id, home_of, parse_copy_ref, parse_object_ref,
                         parse_selector, receipt_short, resolve_prefix, selector_json, short_id)

def test_u2_identifier_grammars():
    assert check_id("person", "person:andy") == "person:andy"
    assert check_id("agent", "agent:ph-coordinator") == "agent:ph-coordinator"
    assert check_id("place", "place:la-county/public-health/clinic-3")
    assert check_id("collection", "collection:andy/" + "a" * 80)
    assert home_of("person:andy") == "place:home/andy"
    for kind, bad in [("place", "place:home"), ("place", "place:" + "/".join("a" * 9)),
                      ("place", "place:" + "/".join(["b" * 63] * 5)),  # 319 characters > 255
                      ("place", "place:home/andy/den"), ("group", "group:outside-home"),
                      ("collection", "collection:andy/" + "a" * 81), ("record", "r-" + "a" * 31)]:
        with pytest.raises(RuleError):
            check_id(kind, bad)

def test_rf4_ids_refuse_newline_case_and_non_ascii():
    for kind, bad in [("person", "person:andy\n"), ("person", "person:Andy"), ("person", "person:аndy"),
                      ("place", "place:la-county\n"), ("agent", "agent:eng ram")]:
        with pytest.raises(RuleError):
            check_id(kind, bad)

def test_object_and_copy_refs():
    assert parse_object_ref("mem:9b1e/episode/m1") == ("memory", "9b1e", "episode", "m1")
    assert parse_object_ref("trail:9b1e/t7").kind == "trail"
    assert parse_copy_ref("imprint:" + "5d" * 32 + "/c0a8f5e2").station == "5d" * 32
    for bad in ["mem:9b1e/instinct/i1", "store:", "imprint:abc"]:
        with pytest.raises(RuleError):
            (parse_copy_ref if bad.startswith(("store", "imprint")) else parse_object_ref)(bad)

def test_selector_canonical_form_and_bounds():
    doc = {"audience": ["place:la-county/public-health"], "requesters": "*",
           "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                       "collections": ["collection:andy/medical-history"], "memories": "*"},
           "actions": ["read", "recall", "inject_context"], "purposes": ["care-coordination"]}
    sel = parse_selector(doc)
    assert sel.actions == ("inject_context", "read", "recall") and sel.memories == STAR
    assert parse_selector(selector_json(sel)) == sel
    for key, value in [("audience", "*"), ("audience", [f"group:g{i:02d}" for i in range(33)]),
                       ("purposes", [f"p{i}" for i in range(17)]), ("actions", ["recall", "recall"])]:
        with pytest.raises(RuleError):
            parse_selector({**doc, key: value})
    with pytest.raises(RuleError):
        parse_selector({**doc, "objects": {**doc["objects"], "memories": [f"mem:s/episode/m{i}" for i in range(513)]}})

def test_selector_road_and_trail_dimensions_must_be_star():
    doc = {"audience": ["self"], "requesters": "*", "actions": ["route"], "purposes": "*",
           "objects": {"kinds": ["road"], "stores": ["s1"], "layers": "*", "lanes": ["work"],
                       "collections": "*", "memories": "*"}}
    with pytest.raises(RuleError, match="5.2"):
        parse_selector(doc)

def test_u26_prefix_resolution():
    ids = ["r-7f3a" + "0" * 28, "r-7f3b" + "0" * 28, "r-0b9e" + "1" * 28]
    assert resolve_prefix(ids, "r-0b9e") == ids[2] and resolve_prefix(ids, ids[0]) == ids[0]
    with pytest.raises(RuleError, match="r-7f3a.*r-7f3b"):
        resolve_prefix(ids, "r-7f3")
    with pytest.raises(RuleError):
        resolve_prefix(ids, "r-0b9")  # fewer than 4 hex
    assert short_id(ids[0]) == "#7f3a" and receipt_short("u-5e21a9c0" + "f" * 24) == "#5e21a9c0"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_names.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'permissions'`.

- [ ] **Step 3: Implement the names and selectors in `engram/permissions.py`**

Patterns are compiled with `re.ASCII` and matched with `fullmatch` on patterns ending `\Z`. Agent names, instance
ids, memory ids, cell ids, trail event ids, station peer ids and imprint ids use the instance-name grammar
`[A-Za-z0-9][A-Za-z0-9_-]{0,63}` (`engram/lighthouse_receiver_config.py:13`). A memory ref's layer is `episode` or
`semantic`. `parse_selector` sorts each list by UTF-16 code units (ASCII here, so byte order), refuses duplicates,
refuses `"*"` for `audience`, applies P 5.2's sizes, refuses `group:outside-home` anywhere, and for kinds that include
`road` or `trail` (or `"*"`, ruling R25) refuses a finite `layers`, `lanes`, `collections` or `memories`. Add
`"permissions"` to `py-modules`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permissions.py engram/pyproject.toml engram/tests/test_permissions_names.py
git commit -m "Permissions: names, copy refs, short ids and selectors (P 4.1, 5.2)"
```

### Task 2: Places, dominance and the State

**Files:**
- Modify: `engram/permissions.py`
- Create: `engram/tests/permissions_support.py`
- Test: `engram/tests/test_permissions_places.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `State`, a frozen dataclass of the P 5.5 tables at one `seq`, with `seq: int`, `seq_at: Mapping[int, int]` (each
    log seq to its `at`), `meta: Mapping[str, str]`, `names: Mapping[str, str]` (R4), and indexes the builder
    chooses; `State.from_tables(tables, *, seq, seq_at, meta, names=None) -> State`, where `tables` maps each P 5.5
    table name to a list of row dicts with its columns; `State.to_tables() -> dict`;
  - `ancestors(state, place: str) -> frozenset[str]` and `dominators(state, place: str) -> frozenset[str]` (P 4.2,
    4.3), cached per state;
  - `place_retired(state, place: str) -> bool` (it or any ancestor retired);
  - `check_new_place(state, place: str, parents: Sequence[str]) -> tuple[str, ...]` returns the parents, defaulting
    to the name's prefix, or raises `RuleError`; `check_new_parent(state, place: str, parent: str) -> None`.
  - Test support in `engram/tests/permissions_support.py`: `T(text: str) -> int` (`"2026-11-02"` or
    `"2026-12-15T00:00:00Z"` to UTC seconds); `World(owner="andy", start=T("2026-11-01"))` with methods
    `person(handle)`, `place(pid, parents=(), stewards=(), name=None)`, `add_parent(place, parent)`,
    `places() -> list[str]`, `retire_place(pid)`, `retire_person(handle)`, `agent(name, acts_for, at=None)`,
    `store(instance_id, owner="person:andy", place="place:home/andy", name="engram", imprint_of=None)`,
    `group(gid, owner, members)`, `collect(cid, refs, backing="person")`, `uncollect(cid, ref)`,
    `subject(ref, subject, self_claimed=False)`, `copy(copy_ref, source_ref)`, `lane(ref, lane, at)`,
    `allow(layer, **selector_and_fields) -> str`, `deny(layer, **...) -> str` (both default `kinds` to `["memory"]`,
    R25's form for a selector that names a lane, a collection, a layer or memories, so the oracle and `decide` never
    read a selector the write rules refuse), `record(rid) -> Record`,
    `revoke(rid)`, `grant(...) -> str`, `revoke_grant(gid)`, `remove_steward(place, person)`,
    `tick(seconds) -> int`, `state() -> State`. `World` writes table rows directly with increasing `seq`s and checks
    nothing. `use(agent, place, obj, *, copy="store:house", action="recall", purpose="care-coordination", at=None,
    names=(), shows=())` builds a `Use` (Task 4). Later tasks add named fixture builders to this file (for example
    `county_world`, `e1_world`); each builds what its name says from P 13 or the test that uses it.

- [ ] **Step 1: Write the failing tests**

```python
def county():
    w = World()
    w.place("place:la-county", name="LA County")
    w.place("place:la-county/public-health", name="Public Health")
    w.place("place:la-county/parks-and-rec", name="Parks and Recreation")
    w.place("place:la-county/public-health/clinic-3")
    w.place("place:la-county/summer-wellness", parents=["place:la-county/public-health",
                                                       "place:la-county/parks-and-rec"])
    return w

def test_u2_joint_place_dominance():
    s = county().state()
    assert dominators(s, "place:la-county/summer-wellness") == {"place:la-county/summer-wellness", "place:la-county"}
    assert "place:la-county/parks-and-rec" in ancestors(s, "place:la-county/summer-wellness")
    assert dominators(s, "place:home/andy") == {"place:home/andy"}

def test_u2_name_rule_cycles_roots_and_bounds():
    s = county().state()
    with pytest.raises(RuleError, match="4.2"):
        check_new_place(s, "place:la-county/x/y", [])            # prefix not registered
    with pytest.raises(RuleError, match="P26"):
        check_new_parent(s, "place:home/andy", "place:la-county")               # a root stays a root
    with pytest.raises(RuleError, match="cycle"):
        check_new_parent(s, "place:la-county/public-health", "place:la-county/public-health/clinic-3")
    w = county()
    for i in range(5):
        w.place(f"place:la-county/p{i}")
    with pytest.raises(RuleError, match="4 parents"):
        check_new_place(w.state(), "place:la-county/j", [f"place:la-county/p{i}" for i in range(5)])
    # depth: at most 16 ancestors, the place itself included (P 4.2)
    w = county()
    for i in range(12):
        w.place(f"place:la-county/p{i:02d}")
    for j, parents in enumerate([(0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11), (8, 9, 10)]):
        w.place(f"place:la-county/j{j}", parents=[f"place:la-county/p{i:02d}" for i in parents])
    s = w.state()
    assert len(ancestors(s, "place:la-county/j0")) == 6                   # j0, p00 to p03, la-county
    k16 = ["place:la-county/j0", "place:la-county/j1", "place:la-county/j3"]   # 1 + 3 + 8 + 3 + 1 = 16
    assert check_new_place(s, "place:la-county/k16", k16) == tuple(k16)
    with pytest.raises(RuleError, match="16 ancestors"):                  # 1 + 3 + 12 + 1 = 17
        check_new_place(s, "place:la-county/k17", ["place:la-county/j0", "place:la-county/j1", "place:la-county/j2"])
    w.place("place:la-county/k16", parents=k16)
    with pytest.raises(RuleError, match="16 ancestors"):                  # k16, below j3, would reach 17
        check_new_parent(w.state(), "place:la-county/j3", "place:la-county/p11")
    # count: at most 1,024 places per ledger, homes included (P 4.4)
    w = county()
    while len(w.places()) < MAX_PLACES - 1:
        w.place(f"place:la-county/q{len(w.places()):04d}")
    check_new_place(w.state(), "place:la-county/the-1024th", [])
    w.place("place:la-county/the-1024th")
    assert len(w.places()) == MAX_PLACES
    with pytest.raises(RuleError, match="1,024 places"):
        check_new_place(w.state(), "place:la-county/the-1025th", [])

def test_u2_retiring_a_place_stops_its_sub_places():
    w = county(); w.retire_place("place:la-county/public-health")
    assert place_retired(w.state(), "place:la-county/public-health/clinic-3")
    assert not place_retired(w.state(), "place:la-county/parks-and-rec")

def test_pt4_dominance_never_grows():
    for case in range(500):   # random DAGs of up to 12 places
        rng = random.Random(f"{SEED}-pt4d-{case}")
        w, place, parent = random_dag_and_new_edge(rng)
        s0 = w.state()
        w.add_parent(place, parent)
        s1 = w.state()
        for p in w.places():
            assert dominators(s1, p) <= dominators(s0, p), (SEED, case, p)
            assert ancestors(s1, p) >= ancestors(s0, p), (SEED, case, p)
```

Also `test_u2_home_reserved` (a `place:home/...` other than a person's home is refused) and
`test_state_tables_round_trip` (`State.from_tables(s.to_tables(), ...)` equals `s`). `random_dag_and_new_edge` lives in `permissions_support.py`
and only picks a place that already has a parent; a root edge is the refused case above.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_places.py`
Expected: FAIL, `ImportError: cannot import name 'State' from 'permissions'`.

- [ ] **Step 3: Implement `State`, `ancestors`, `dominators`, `place_retired`, `check_new_place`, `check_new_parent`**

`dominators` follows P 4.3 in topological order. `check_new_place` applies P 4.2's name rule (the prefix must be a
registered place that dominates the new one), at most `MAX_PARENTS` parents, at most `MAX_ANCESTORS` ancestors for any
place, at most `MAX_PLACES` places, and refuses `place:home/...` except a person's home. Write `World` and `T` in
`permissions_support.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permissions.py engram/tests/permissions_support.py engram/tests/test_permissions_places.py
git commit -m "Permissions: places, ancestry, dominance and the State (P 4.2, 4.3)"
```

### Task 3: Grant chains

**Files:**
- Modify: `engram/permissions.py`
- Test: `engram/tests/test_permissions_grants.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces:
  - `Grant`, a frozen dataclass of the `permission_grants` columns (`ops: frozenset[str]`, `envelope: Selector`);
  - `grant_chain(state, grant_id: str) -> tuple[Grant, ...]`, root first;
  - `grant_validity(state, grant_id: str, at: int) -> tuple[bool, str | None]`, with reason `"revoked"`, `"expired"`,
    `"too-long"` (more than `MAX_GRANT_LINKS` links) or `"not-steward"` (the root's issuer is no longer a steward of
    the layer); a revocation at `seq` s makes it invalid in every state at s or later;
  - `check_root_grant(state, grant: Grant) -> None` and `check_child_grant(state, parent: Grant, child: Grant) -> None`,
    raising `RuleError`;
  - `selector_within(state, inner: Selector, outer: Selector) -> bool`: each list a subset, `"*"` only where the
    outer has `"*"`, and each audience entry within an outer entry (equal; or the outer is `commons`; or both are
    `place:` and the outer's place dominates the inner's).

- [ ] **Step 1: Write the failing tests**

```python
def test_root_grant_bounds():
    w = county_world()                        # added in this task; here only persons, agents and places matter
    g = w.grant_draft(issuer="person:andy", grantee="agent:rio-grande", layer="place:home/andy",
                      ops={"share", "withdraw"}, envelope=R1_ENVELOPE, max_days=120, depth=2, hours=720)
    check_root_grant(w.state(), g)
    for change in [{"depth": 3}, {"expires": g.created + 721 * 3600}, {"ops": frozenset({"share", "sign"})},
                   {"grantee": "agent:parks-planner"}]:      # parks-planner does not act for Andy
        with pytest.raises(RuleError):
            check_root_grant(w.state(), dataclasses.replace(g, **change))

def test_child_is_a_subset_in_every_field_and_a_fourth_link_is_refused():
    w, root, child, grandchild = three_link_chain()          # root depth 2, child 1, grandchild 0
    for wider in [{"ops": root.ops | {"deny"}}, {"max_days": root.max_days + 1}, {"expires": root.expires + 1},
                  {"depth": root.depth}, {"envelope": widen_audience(root.envelope, "place:la-county")}]:
        with pytest.raises(RuleError):
            check_child_grant(w.state(), root, dataclasses.replace(child, **wider))
    with pytest.raises(RuleError, match="3 links"):
        check_child_grant(w.state(), grandchild, child_draft(grandchild))

def test_validity_walks_to_the_root_at_each_check():
    w, root, child, _ = three_link_chain()
    assert grant_validity(w.state(), child.id, T("2026-11-05")) == (True, None)
    w.revoke_grant(root.id)
    assert grant_validity(w.state(), child.id, T("2026-11-05")) == (False, "revoked")
    w2, root2, child2, _ = three_link_chain()
    assert grant_validity(w2.state(), child2.id, root2.expires) == (False, "expired")
    w3, _, child3, _ = three_link_chain(); w3.remove_steward("place:home/andy", "person:andy")
    assert grant_validity(w3.state(), child3.id, T("2026-11-05"))[1] == "not-steward"
```

`county_world` (P 13's places, persons and agents, with no records), `R1_ENVELOPE`, `three_link_chain`,
`World.grant_draft`, `child_draft` and `widen_audience` are added to `permissions_support.py` here.
`remove_steward` on a home is a test-only row edit (a home's steward never changes through `perform`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_grants.py`
Expected: FAIL, `ImportError: cannot import name 'grant_validity'`.

- [ ] **Step 3: Implement the grant functions in `engram/permissions.py`**

Follow P 7.2 and `_grant_validity`'s walk (`peer/superyak_peer/grants.py:95-122`). A root's depth is 0 to
`MAX_GRANT_DEPTH` and it lasts at most `MAX_GRANT_HOURS` hours. Its grantee must act for the layer's person, or for
the layer's place. The ops are a subset of the seven grant ops.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permissions.py engram/tests/permissions_support.py engram/tests/test_permissions_grants.py
git commit -m "Permissions: grant chains, validity and the subset rule (P 7.2)"
```

### Task 4: Matching with history

**Files:**
- Modify: `engram/permissions.py`
- Test: `engram/tests/test_permissions_match.py`

**Interfaces:**
- Consumes: Tasks 1 to 3. `Use` is defined here (Task 5 adds the decision types around it).
- Produces:
  - `Use`, a frozen dataclass `(requester: str, place: str, obj: str, copy: str, action: str, purpose: str, at: int,
    names: tuple[str, ...] = (), shows: frozenset[str] = frozenset())`; `names` are the memories a road or trail
    names, in order, and `shows` those whose content the answer shows;
  - `Record`, a frozen dataclass of the `records` columns (`selector: Selector`);
  - `acts_for_place(state, agent: str) -> str | None` (`act(a)`); `agent_place_at(state, agent, at) -> str | None`;
  - `record_matches(state, record: Record, use: Use, action: str) -> bool`, P 5.3 rules 1 to 5 with memberships read
    narrowly for an allow and widely for a deny (P7);
  - `record_candidate(state, record, use, action) -> bool`, P 6.5's candidate (rules 2 and 3 and the selector parts
    of 4 and 5, every validity ignored; a revoked allow is never one);
  - `lane_held(state, ref, lane, since, at) -> bool` and `lane_touched(state, ref, lane, anchor, at) -> bool`, the
    two readings of `lane_notes`.

- [ ] **Step 1: Write the failing tests**

```python
def test_u20_place_audience_needs_the_acts_for_place_within_the_domain():
    w = county_world()                     # county() plus agents ph-coordinator, parks-planner, sw-helper
    r1 = w.allow("place:home/andy", audience=["place:la-county/public-health"],
                 collections=["collection:andy/medical-history"], actions=["recall", "read", "inject_context"],
                 purposes=["care-coordination"], valid_from=T("2026-11-01"), valid_until=T("2027-01-31"))
    s, rec = w.state(), w.record(r1)
    ok = use("agent:ph-coordinator", "place:la-county/public-health/clinic-3", M1, at=T("2026-11-02"))
    assert record_matches(s, rec, ok, "recall")
    assert not record_matches(s, rec, use("agent:parks-planner", "place:la-county/parks-and-rec", M1,
                                          at=T("2026-11-02")), "recall")
    assert not record_matches(s, rec, use("agent:sw-helper", "place:la-county/summer-wellness", M1,
                                          at=T("2026-11-02")), "recall")

def test_u20_self_and_own_group_allows_do_not_match_outside_the_home():
    w = county_world(); w.group("group:andys", "person:andy", ["agent:rio-grande"])
    for entry in ["self", "group:andys"]:
        rid = w.allow("place:home/andy", audience=[entry], actions=["recall"])
        assert not record_matches(w.state(), w.record(rid),
                                  use("agent:rio-grande", "place:la-county", M1, at=T("2026-11-02")), "recall")

def test_u6_lanes_after_a_move():
    w = county_world(); w.lane(M1, "personal", T("2026-10-01"))
    work_allow = w.allow("place:home/andy", audience=["self"], lanes=["work"], actions=["recall"])
    w.lane(M1, "pending", T("2026-11-03")); w.lane(M1, "work", T("2026-11-03"))
    assert not record_matches(w.state(), w.record(work_allow), home_use(M1, T("2026-11-04")), "recall")
    personal_deny = w.deny("place:home/andy", audience=["self"], lanes=["personal"], actions=["recall"],
                           anchor=T("2026-10-15"))
    assert record_matches(w.state(), w.record(personal_deny), home_use(M1, T("2026-11-04")), "recall")
    # one moved from work to personal stops being covered by the work-lane allow
    w2 = county_world(); w2.lane(M1, "work", T("2026-10-01"))
    allow2 = w2.allow("place:home/andy", audience=["self"], lanes=["work"], actions=["recall"])   # anchored 2026-11-01
    assert record_matches(w2.state(), w2.record(allow2), home_use(M1, T("2026-11-02")), "recall")   # in work since
    w2.lane(M1, "pending", T("2026-11-03")); w2.lane(M1, "personal", T("2026-11-03"))
    assert not record_matches(w2.state(), w2.record(allow2), home_use(M1, T("2026-11-04")), "recall")

def test_u25_pending_reads_as_neither_lane_for_an_allow_and_both_for_a_deny():
    w = county_world(); w.lane(M1, "personal", T("2026-10-01")); w.lane(M1, "pending", T("2026-11-03"))
    allows = [w.allow("place:home/andy", audience=["self"], lanes=[lane], actions=["recall"])
              for lane in ("personal", "work")]
    denies = [w.deny("place:home/andy", audience=["self"], lanes=[lane], actions=["recall"], anchor=T("2026-10-15"))
              for lane in ("personal", "work")]
    any_lane = w.allow("place:home/andy", audience=["self"], lanes="*", actions=["recall"])
    s, u = w.state(), home_use(M1, T("2026-11-04"))         # no settling note after the pending one
    assert not any(record_matches(s, w.record(r), u, "recall") for r in allows)
    assert all(record_matches(s, w.record(r), u, "recall") for r in denies)
    assert record_matches(s, w.record(any_lane), u, "recall")   # "*" makes no lane test (P 5.2)

def test_u25_a_memory_with_no_note_matches_no_lane_limited_allow():
    w = county_world()                                       # M1 has no lane note at all
    allows = [w.allow("place:home/andy", audience=["self"], lanes=[lane], actions=["recall"])
              for lane in ("personal", "work")]
    denies = [w.deny("place:home/andy", audience=["self"], lanes=[lane], actions=["recall"], anchor=T("2026-10-15"))
              for lane in ("personal", "work")]
    s, u = w.state(), home_use(M1, T("2026-11-04"))
    assert not any(record_matches(s, w.record(r), u, "recall") for r in allows)
    assert all(record_matches(s, w.record(r), u, "recall") for r in denies)

def test_grant_backed_membership_counts_only_while_its_chain_is_valid_and_within_its_envelopes(): ...
def test_removed_membership_still_counts_for_a_deny_since_its_anchor(): ...

def test_pt6_a_replacement_never_matches_what_its_chain_does_not():
    for case in range(500):
        rng = random.Random(f"{SEED}-pt6-{case}")
        w, chain = random_replacement_chain(rng)       # random selectors and intervals, some outside the original
        apply_random_registry_changes(rng, w)
        s = w.state()
        for u in sample_uses(rng, w, 40):
            for x in ACTIONS:
                if record_matches(s, w.record(chain[-1]), u, x):
                    assert all(selector_and_interval_match(s, w.record(r), u, x) for r in chain), (SEED, case)
```

`home_use`, `M1` (`"mem:S/episode/m1"`), `random_replacement_chain`, `apply_random_registry_changes` and `sample_uses`
are added to `permissions_support.py`. `selector_and_interval_match` is written in this test file from P 5.3 rules 1 to
3 (the oracle of Task 5 later holds the same reading).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_match.py`
Expected: FAIL, `ImportError: cannot import name 'record_matches'`.

- [ ] **Step 3: Implement matching in `engram/permissions.py`**

Audience entries follow P 5.2's list exactly: an allow's `place:Z` needs `Z ∈ dom(P)` and `Z ∈ dom(act(a))`; a deny's
needs Z in `anc(P)`, in `anc(act(a))`, or in `anc(X)` for a place X the agent was in during `[anchor, t]`; a `group:g`
allow also needs `home(owner(g)) ∈ dom(P)`; a `self` allow needs `place(L) ∈ dom(P)`. Memberships follow P 5.3's
table, reading times through `state.seq_at`. Rule 4 walks `replaces` up to `MAX_REPLACES` links, ignoring the
revocations made by the replacing records. Rule 5 uses Task 3's chain and validity.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permissions.py engram/tests/permissions_support.py engram/tests/test_permissions_match.py
git commit -m "Permissions: audiences and matching with history (P 5.2, 5.3)"
```

### Task 5: Subjects, required layers, need and the decision

**Files:**
- Modify: `engram/permissions.py`, `engram/tests/permissions_support.py`
- Test: `engram/tests/test_permissions_decide.py`

The oracle, `random_world` and the property tests are Task 5A, so this task stays one decision and its hand-written
cases.

**Interfaces:**
- Consumes: Tasks 1 to 4; `lighthouse_policy.Policy` and `PolicyRequest` (U1 only).
- Produces:
  - `Need(obj: str, actions: tuple[str, ...])`; `needs(use: Use) -> tuple[Need, ...]`: the object first, then each
    named memory in ref order, per P 6.4's table and named-memory rule;
  - `Layer(id: str, kind: str)` with kind `consent`, `restriction`, `legacy` or `outside`;
  - `subjects_of(state, obj: str, at: int, names: Sequence[str] = ()) -> tuple[str, ...]`, sorted: the store's owner
    and co-subjects, a kept copy's source's subjects through `copies` up to `MAX_COPY_CHAIN` links, and for a road or
    trail the union of its named memories' subjects plus its store's owner (P24, P25);
  - `required_layers(state, use: Use) -> tuple[Layer, ...]` in P 6.5 step 2's order, each layer once;
  - `LegacyLayer(name: str, allows: Callable[[Use, str], bool])`; `outside: Mapping[str, Callable[[Use, str], str]]`
    maps a place id whose layer is kept outside a ledger to its verdict (`allow`, `deny` or `silent`) (R7). For a
    place id in `outside`, the callable is that layer's whole verdict. `decide` reads no ledger record in that layer,
    cites none (its `Cited` has kind `outside` and empty `records`), and the layer adds nothing to `until` or the
    horizon. The layer keeps its place in step 2's order and counts once, however many items of `Req` name it. This
    is what lets the imprints plan pass `outside={"place:home/andy": ceiling}` while Andy's own records sit in that
    same layer (XM1): meeting those records with the ceiling would refuse sam's imprint;
  - `layer_verdict(state, layer: Layer, use: Use, action: str) -> str`: `allow`, `deny`, `silent` or `missing`;
  - `Cited(layer: str, kind: str, action: str, verdict: str, records: tuple[str, ...])`;
    `Refusal(code: str, layer: str | None, action: str | None)`;
    `Decision(allowed: bool, at: int, ledger_seq: int, action: str, cited: tuple[Cited, ...],
    refusal: Refusal | None, until: int | None, horizon: int | None, versions: Mapping[str, int])` with
    `to_json() -> dict` (R8);
  - `decide(state, use: Use, *, legacy: Sequence[LegacyLayer] = (), outside: Mapping | None = None) -> Decision`.
    In this task `until` and `horizon` are `None`; Task 6 fills them.
  - in `permissions_support.py`: `e1_world(through_use: int) -> tuple[World, SimpleNamespace]`, P 13's places,
    rules, agents, collection, co-subject, R1, G1 and the acts of uses 6 to 10 up to the one named, written with
    `World`; the ids namespace holds `R1`, `R1P` (R1′), `G1`, `D1`, `C1`, `H1`, `L1` and the rest. `e1_use_1()`,
    `e1_after_use_7()`, `e1_after_use_9()`, `e1_after_use_10()` and the like are thin wrappers over it. Task 29 builds
    the same world through the ledger.

- [ ] **Step 1: Write the failing tests**

```python
def test_u28_each_refusal_code():
    cases = {"UNKNOWN_REQUESTER": unregistered_agent_use, "RETIRED": retired_subject_home_use,
             "NO_LAYER": no_subject_use, "BOUND": nine_subjects_use, "DENIED": dated_deny_use,
             "EXPIRED": ended_allow_use, "GRANT_INVALID": revoked_grant_use, "NOT_YET": future_allow_use,
             "NO_ALLOW": silent_layer_use, "LEGACY_DENY": legacy_refusal_use}
    for code, build in cases.items():
        s, u, legacy = build()
        assert decide(s, u, legacy=legacy).refusal.code == code, code

def test_u28_expired_against_grant_invalid_against_not_yet_on_one_record():
    s, u = one_grant_backed_record(valid_from=T("2026-11-05"), valid_until=T("2026-11-20"))
    assert decide(s, u(at=T("2026-11-01"))).refusal.code == "NOT_YET"
    assert decide(s, u(at=T("2026-11-21"))).refusal.code == "EXPIRED"
    s2, u2 = one_grant_backed_record(revoked_grant=True)
    assert decide(s2, u2(at=T("2026-11-10"))).refusal.code == "GRANT_INVALID"

def test_u28_use_10_read_of_m4():
    s, read_m4 = e1_after_use_10()    # R1′ covers m4 only through G1's membership; G1 revoked 2026-11-20
    assert decide(s, read_m4(T("2026-11-21"))).refusal == Refusal("GRANT_INVALID", "place:home/andy", "recall")
    assert decide(s, read_m4(T("2026-11-30"))).refusal == Refusal("EXPIRED", "place:home/andy", "recall")

def test_u28_a_co_subject_is_no_allow_when_registered_with_an_empty_home_and_no_layer_when_not():
    # P 7.4: "NO_ALLOW if they are registered with an empty home layer, NO_LAYER if not". person:amy sorts before
    # person:andy, so her home is the first layer in step 2's order either way.
    s, u = co_subject_world(register_amy=True)
    assert decide(s, u).refusal == Refusal("NO_ALLOW", "place:home/amy", "recall")
    s, u = co_subject_world(register_amy=False)
    assert decide(s, u).refusal == Refusal("NO_LAYER", "place:home/amy", "recall")   # her layer is `missing`

def test_u21_unregistered_store_no_source_and_unregistered_house_are_no_layer():
    for s, u in [object_in_unregistered_store(), placement_without_source_instance_id(),
                 copy_in_unregistered_house()]:
        assert decide(s, u).refusal.code == "NO_LAYER"

def test_u21_the_same_ref_in_two_houses_uses_each_house_place():
    s, at_home, at_clinic = one_ref_two_houses()   # the clinic's layer refuses imprint, the home's allows it
    assert decide(s, at_home).allowed and not decide(s, at_clinic).allowed

def test_u1_most_specific_wins_is_not_monotone():
    a = rule("A", "allow", publishers=["urn:engram:*"], contexts=["memory/technical"])
    d = rule("D", "deny", publishers=["urn:engram:x"], contexts=["memory/*"])
    request = policy_request(publisher="urn:engram:x", context="memory/technical")
    assert Policy(policy_artifact([a, d])).decide(request).effect == "deny"
    narrowed = rule("A", "allow", publishers=["urn:engram:x"], contexts=["memory/technical"])
    assert Policy(policy_artifact([narrowed, d])).decide(request).effect == "allow"

def test_an_outside_layer_is_that_layers_whole_verdict():
    w, u = two_owner_imprint_use()     # sam's copy; Andy's home layer holds his own allows, none naming sam's store
    s = w.state()
    refusal = decide(s, u).refusal                                                    # the ledger layer alone
    assert (refusal.code, refusal.layer) == ("NO_ALLOW", "place:home/andy")
    d = decide(s, u, outside={"place:home/andy": lambda use, x: "allow"})
    assert d.allowed and [c for c in d.cited if c.layer == "place:home/andy"] == [
        Cited("place:home/andy", "outside", x, "allow", ()) for x in sorted_actions(needs(u))]
    w.deny("place:home/andy", audience=["commons"], actions=["imprint"])               # a ledger deny there
    assert decide(w.state(), u, outside={"place:home/andy": lambda use, x: "allow"}).allowed   # not read
    assert decide(s, u, outside={"place:home/andy": lambda use, x: "silent"}).refusal.code == "NO_ALLOW"
```

`two_owner_imprint_use` and `sorted_actions` are added to `permissions_support.py`: the requester is
`agent:station-imprints` acting for Andy at `place:home/andy`; the copy is `imprint:<peer>/c0a8` of sam's store, held
at `place:home/andy`; sam's home layer allows the use; the agent's restriction layer is empty. `sorted_actions` lists
the actions `needs(u)` asks of the object, in `ACTIONS` order. `co_subject_world(register_amy)` is `county_world`
plus Andy's store `S` and the house `house`, both at `place:home/andy`, R1 of P 13 in Andy's home, and `person:amy` as
m1's co-subject; with `register_amy` it also registers `person:amy`, whose home layer stays empty. Its use is
`ph-coordinator`'s recall of m1 at clinic-3 on 2026-11-02, for care-coordination, with copy `store:house`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_decide.py`
Expected: FAIL, `ImportError: cannot import name 'decide'`.

- [ ] **Step 3: Implement `needs`, `subjects_of`, `required_layers`, `layer_verdict` and `decide`**

Follow P 6.3 and P 6.5 steps 1 to 5 and 8. Step 1's tests run in its order. The pre-filter of P 6.5 ("How it is
computed") selects, per layer, the records whose audience, `requesters`, `actions` and `purposes` can match before any
object test. Refusal codes: `EXPIRED`, then `GRANT_INVALID`, then `NOT_YET`, then `NO_ALLOW`, reading every candidate's
chains, its own and its memberships' (the re-check's RS7). A missing layer, an unknown place or an unregistered
subject is `missing` and refuses with `NO_LAYER`. A restriction layer's `silent` passes. A layer in `outside` is
decided by its callable alone. `cited` holds one `Cited` per (layer, action), with the allowing record chosen by
latest effective end, then smallest id (step 5). `versions` holds each ledger layer's highest touching `seq`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permissions.py engram/tests/permissions_support.py engram/tests/test_permissions_decide.py
git commit -m "Permissions: subjects, required layers, need, decide and its codes (P 6.3-6.5)"
```

### Task 5A: The oracle, `random_world` and the decision's property tests

**Files:**
- Create: `engram/tests/permissions_oracle.py`
- Modify: `engram/tests/permissions_support.py`
- Test: `engram/tests/test_permissions_properties.py`

The number keeps the other plans' references to Tasks 6 to 32 valid.

**Interfaces:**
- Consumes: Task 5.
- Produces:
  - `engram/tests/permissions_oracle.py`: `oracle_allowed(tables: dict, seq_at: dict, use: dict,
    legacy: Sequence[tuple[str, frozenset[str]]] = ()) -> bool`, a brute-force reading of P 5 and 6 that imports
    nothing from `permissions.py`. It walks every record of every required layer for every needed (object, action),
    with no pre-filter and no index;
  - in `permissions_support.py`: `random_world(rng, *, places=12) -> World`, which reaches every op, every membership
    kind, joint places, roots, pending notes, kept copies with chains of up to 4 links, and bulk uses (P 18), and
    `sample_uses(rng, w, n)` (Task 4's) extended to bulk uses.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_oracle_agrees_with_task_5s_hand_written_cases():
    for build in HAND_WRITTEN_CASES:                  # Task 5's U28, U21 and E1 builders, imported from its test file
        for s, u, legacy in build():                  # each entry yields (state, use, legacy) triples
            assert oracle_allowed(s.to_tables(), dict(s.seq_at), use_json(u), legacy_json(legacy)) \
                is decide(s, u, legacy=legacy).allowed, build.__name__

def test_random_world_reaches_every_op_and_membership_kind():
    seen = set()
    for case in range(500):
        seen |= features(random_world(random.Random(f"{SEED}-reach-{case}")))
    assert seen >= REQUIRED_FEATURES, REQUIRED_FEATURES - seen   # every op, membership kind, joint place, root,
                                                                 # pending note, 4-link copy chain, bulk use
```

`HAND_WRITTEN_CASES` is a list of zero-argument callables, each returning a list of (state, use, legacy) triples, so
the agreement test unpacks one shape. Task 5's builders return three shapes, and each entry adapts its builder: a
U28 builder's `(s, u, legacy)` is one triple; an `(s, u)` builder (`co_subject_world`, the U21 builders,
`two_owner_imprint_use`) gets legacy `()`; `one_ref_two_houses`'s `(s, at_home, at_clinic)` gives two triples; and a
builder whose use is a function of time (`one_grant_backed_record`, `e1_after_use_10`) is called at each time its Task
5 test uses.

Then, each looping 500 cases over `random_world(rng)` and also asserting, for each sampled use,
`decide(...).allowed == oracle_allowed(...)`:

- `test_pt1_meet` — adding any layer to `Req` (a subject, a place, a legacy policy, a restriction deny) never turns a
  refusal into an allow.
- `test_pt4_nesting_allows` — what is allowed at a place is within each ancestor's layer there; an allow to `place:Z`
  never matches a place with a path around Z; adding a parent edge to a place that has one never adds an allowed use.
- `test_pt5_unchecked_changes` — random lane moves, pending notes and removals from collections, groups and places
  never add an allowed use.
- `test_pt7_subjects` — adding subjects never adds an allowed use; a road's subjects include its endpoints'; a kept
  copy carries its source's subjects, and an allow at the keeper's place alone never lets it out; a subject added to a
  source after the copy refuses the copy's next use, through chains of up to 4 copies.
- `test_pt8_revocation_and_expiry` — a record revoked at `seq` s is never cited at s or later, and no use at or after
  its `valid_until` is allowed by it.
- `test_pt3_delegation` — for random chains of up to 3 links, every effective record's matches and every match through
  a grant-backed membership lie within `(Sig⁺ ∪ Env) \ Sig⁻` (L4), with `Sig⁺`, `Sig⁻` and `Env` computed by the
  oracle over the person's own rows and root grants.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_properties.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'permissions_oracle'`.

- [ ] **Step 3: Write the oracle and `random_world`**

Write the oracle from the spec text, not from `permissions.py`, and never look at `decide` while writing it. If an
oracle and `decide` disagree, the failing seed and case go into `test_the_oracle_agrees_with_task_5s_hand_written_cases`
as a new hand-written case before either side is changed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_properties.py tests/test_permissions_decide.py`
Expected: PASS, 8 + 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/tests/permissions_support.py engram/tests/permissions_oracle.py engram/tests/test_permissions_properties.py
git commit -m "Permissions: the brute-force oracle, random_world and the decision's property tests (P 6.6, 17)"
```

### Task 6: Citations, `until` and the horizon

**Files:**
- Modify: `engram/permissions.py`
- Test: `engram/tests/test_permissions_horizon.py`, `engram/tests/test_permissions_properties.py`

**Interfaces:**
- Consumes: Tasks 5 and 5A.
- Produces: `effective_end(state, record: Record, matched_memberships: Sequence) -> int | None` (P 6.5 step 5); `decide`
  now fills `until` (step 6) and `horizon` (step 7), both over ledger layers only, both `None` when no term exists.

- [ ] **Step 1: Write the failing tests**

```python
def test_u19_a_dated_deny_refuses_at_its_start_with_no_write():
    s, u = e1_after_use_9()                        # D1 denies m2 from 2026-12-01
    d = decide(s, u(M2, T("2026-11-12")))
    assert d.allowed and d.until == d.horizon == T("2026-12-01")
    assert decide(s, u(M2, T("2026-12-01"))).refusal == Refusal("DENIED", "place:home/andy", "recall")

def test_u19_a_grant_backed_membership_stops_at_its_grant_expiry():
    s, u = e1_after_use_7()                        # m4 collected under G1, which expires 2026-11-30
    d = decide(s, u(M4, T("2026-11-08")))
    assert d.until == d.horizon == T("2026-11-30") and not decide(s, u(M4, T("2026-11-30"))).allowed

def test_u19_until_is_cited_per_layer_and_action():
    d = decide(*e1_use_1())
    assert {(c.layer, c.action) for c in d.cited if c.kind == "consent"} == {
        (layer, x) for layer in E1_USE_1_LAYERS for x in ("recall", "read", "inject_context")}
    assert d.until == T("2027-01-31") and d.horizon == T("2027-01-31")

def test_u19_a_legacy_rule_ending_first_refuses_at_the_next_request():
    s, u, legacy = e1_use_1_with_publisher_rule_until("2026-12-01T00:00:00Z")
    assert decide(s, u(T("2026-11-30")), legacy=legacy).until == T("2027-01-31")   # the ledger's until
    assert decide(s, u(T("2026-12-01") + 1), legacy=legacy).refusal.code == "LEGACY_DENY"
```

In `test_permissions_properties.py`:
- `test_pt12_horizon` — for random states and uses, `decide` is the same at every sampled time in `[t, horizon)`
  (ten times, both ends included where valid), and `horizon <= until` when both exist.
- `test_pt10_determinism_by_insertion_order` — the same decision, cited records, `until` and horizon whatever order
  the rows were inserted in (`random_world` shuffles row order and renumbers nothing). The replay half is Task 10.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_horizon.py tests/test_permissions_properties.py`
Expected: FAIL, the `until` assertions (in `test_u19_until_is_cited_per_layer_and_action`, `None != 1801353600`,
which is 2027-01-31).

- [ ] **Step 3: Implement `effective_end`, `until` and `horizon`**

Exactly P 6.5 steps 5 to 7: `until` is the earliest of every cited record's effective end and the `valid_from`, after
t, of every deny in a required ledger layer that would match some use in `need(u)` at that time with σ fixed; the
horizon is the earliest `valid_from` or `valid_until` after t of every record in a required ledger layer that is
effective at σ or in the `replaces` chain of one, and every `expires` after t of a grant behind a record or membership
the decision read.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/permissions.py engram/tests/test_permissions_horizon.py engram/tests/test_permissions_properties.py
git commit -m "Permissions: citations, until and the horizon (P 6.5 steps 5-7, L8)"
```

### Task 7: Roads, trails and bulk uses

**Files:**
- Modify: `engram/permissions.py`
- Test: `engram/tests/test_permissions_bulk.py`

**Interfaces:**
- Consumes: Tasks 5 and 6.
- Produces:
  - `BulkUse`, a frozen dataclass `(requester, place, objects: tuple[str, ...], copy, action, purpose, at,
    named: bool, names: Callable[[str], Iterable[str]] = lambda o: ())`; `named=True` means the receipt names its
    objects (at most `MAX_BULK_NAMED`), `False` that they are derived and counted (at most `MAX_BULK_DERIVED`);
  - `decide_bulk(state, bulk: BulkUse, *, legacy=(), outside=None, group=True) -> Decision`, P 6.4 "Bulk uses" and
    P 6.5 step 1's bulk order; `cited` aggregates per (layer, action) (R8); its refusal names no object. `outside`
    works as in `decide` (Task 5): a place id in it is that layer's whole verdict. Since `need(U)` is a union (P 6.4),
    `decide_bulk` decides each (memory, action) pair once across U, however many objects name the memory, and keeps
    the refusal order by object: the refusal is that of the first object, in ref order, whose needs hold a refused
    pair;
  - `decide` now refuses with `BOUND` an answer use on a road or trail that names more than `MAX_ANSWER_NAMES`, and a
    road or trail with more than `MAX_SUBJECTS` subjects.

- [ ] **Step 1: Write the failing tests**

```python
def test_u22_a_route_answer_needs_read_and_inject_on_what_it_shows_and_recall_on_what_it_names():
    s = road_world()                 # road r names a and b; inject_context is not allowed on b
    assert decide(s, route(ROAD, names=(A, B), shows={A})).allowed
    assert decide(s, route(ROAD, names=(A, B), shows={A, B})).refusal.action == "inject_context"

def test_u22_every_action_on_a_trail_needs_recall_on_every_memory_it_names():
    s = trail_world(blocked=C)       # C may not be recalled by this audience
    for x in ("recall", "read", "imprint"):
        assert not decide(s, trail_use(TRAIL, x, names=(A, B, C))).allowed

def test_u22_answer_uses_name_at_most_32():
    s = trail_world()
    assert decide(s, trail_use(TRAIL33, "route", names=memories(33))).refusal.code == "BOUND"
    assert decide(s, trail_use(TRAIL32, "route", names=memories(32))).allowed

def test_u22_a_bulk_route_over_three_trails_of_40_touches_is_allowed():
    s = trail_world()
    bulk = bulk_route([TRAIL_A, TRAIL_B, TRAIL_C], touches=40, named=False)
    assert decide_bulk(s, bulk).allowed
    assert all(decide(s, trail_use(t, "route", names=memories(40))).refusal.code == "BOUND" for t in bulk.objects)

def test_u22_one_failing_object_refuses_the_bulk_use_without_naming_it():
    s, bulk = bulk_with_one_denied_object()
    d = decide_bulk(s, bulk)
    assert d.refusal == Refusal("DENIED", "place:home/andy", "recall") and "mem:" not in json.dumps(d.to_json())
    assert d.until == min(per_object_untils(s, bulk)) and all(c.records == tuple(sorted(c.records)) for c in d.cited)

def test_u22_size_bounds_come_before_any_object():
    s = trail_world()
    assert decide_bulk(s, derived_bulk(100_001)).refusal.code == "BOUND"
    assert decide_bulk(s, named_bulk(513)).refusal.code == "BOUND"
    assert decide_bulk(s, derived_bulk(100_001, requester="agent:nobody")).refusal.code == "UNKNOWN_REQUESTER"

def test_u22_named_memories_bound_and_split():
    s = trail_world()
    big = derived_trails_naming(100_001)            # distinct memories across all touches
    assert decide_bulk(s, big).refusal.code == "BOUND"
    first, second = split_by_named_memories(big, 100_000)
    assert decide_bulk(s, first).allowed and decide_bulk(s, second).allowed

def test_u22_no_subject_and_nine_subjects_unless_an_earlier_object_fails():
    s = bulk_world()
    assert decide_bulk(s, bulk_of(NO_SUBJECT_OBJ)).refusal.code == "NO_LAYER"
    assert decide_bulk(s, bulk_of(NINE_SUBJECTS_OBJ)).refusal.code == "BOUND"
    assert decide_bulk(s, bulk_of(EARLIER_DENIED_OBJ, NINE_SUBJECTS_OBJ)).refusal.code == "DENIED"

def test_u22_a_memory_named_by_many_objects_is_decided_once_per_action():
    s, calls = trail_world(), collections.Counter()
    counting = [LegacyLayer("count", lambda u, x: calls.update([(u.obj, x)]) is None)]   # allows, and counts
    bulk = bulk_route([TRAIL_A, TRAIL_B, TRAIL_C], touches=40, named=False, same_memories=True)  # each names m0..m39
    assert decide_bulk(s, bulk, legacy=counting, group=False).allowed
    assert {calls[(m, "recall")] for m in memories(40)} == {1}

def test_u22_imprints_spec_need_agrees():
    # I 8's Need(trail-evaluation) and Need(admission), with h = imprint:<peer>/<id>, requester
    # agent:station-imprints acting for the operator in place:home/andy. Two owners: sam's imprint c0a8 and Andy's
    # own (Andy is the operator, XM1). The operator's home layer is passed as `outside`, the ceiling ⟦c⟧ of I 8,
    # written in the test from I 8's items 1 to 5.
    s, ceiling, uses_and_expected = imprint_fixture(owners=("sam", "andy"), operator="andy")
    for bulk, expected in uses_and_expected:
        assert decide_bulk(s, bulk, outside={"place:home/andy": ceiling}).allowed is expected, bulk
```

The receipts parts of U22 (five roads give five receipts; one counted receipt; a named batch's count and SHA-256) are
in Task 14.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_bulk.py`
Expected: FAIL, `ImportError: cannot import name 'BulkUse'`.

- [ ] **Step 3: Implement the bounds and `decide_bulk`**

`decide_bulk` runs the tests on a, P, `anc(P)` and `anc(H)` once, then counts objects and distinct named memories,
stopping at the bound plus one, before deciding any object. Objects are decided in ref order, each by `decide`'s
per-object path with the bound of 32 waived, but each named memory's (memory, action) verdicts come from one memo
keyed by that pair, at most `MAX_BULK_MEMORIES` memories. So Task 31 makes at most 100,000 memory decisions per
action, not one per touch, and its 51.2 million touches cost one memo lookup each. With `group=True`, objects that
agree on kind, store, layer, lane notes, collection memberships, whether any pre-filtered record lists them in
`memories`, and subjects share one decision. `names` is called again when the objects are decided, so the touches are
streamed, never held.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 10 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permissions.py engram/tests/permissions_support.py engram/tests/test_permissions_bulk.py
git commit -m "Permissions: roads, trails and bulk uses with their bounds (P 6.4, P33, P35)"
```

### Task 8: Boxes, the gluing check and ineffective parts

**Files:**
- Modify: `engram/permissions.py`, `engram/tests/permissions_oracle.py`
- Test: `engram/tests/test_permissions_boxes.py`, `engram/tests/test_permissions_properties.py`

**Interfaces:**
- Consumes: Tasks 2 to 6.
- Produces:
  - `FSet(items: frozenset[str], co: bool)` (finite or cofinite), `TimeSet(intervals: tuple[tuple[int, int | None],
    ...])`, `Box` (one set per dimension: requester place, requester agent, kind, store, layer, lane, memory, action,
    purpose, time);
  - `box_and(a, b) -> Box | None`, `box_minus(a, b) -> list[Box]` (at most 10 disjoint boxes), `box_empty(b) -> bool`,
    `box_subset(a, b) -> bool`;
  - `layer_boxes(state, layer: str, *, at_place: str | None = None) -> list[Box]`, raising `TooComplex` past
    `BOX_CAP`; collections expand as P 8 says;
  - `GluingReport(place: str, delta: tuple[Box, ...], ineffective: tuple[Box, ...], too_complex: bool,
    notify: frozenset[str])`; `gluing(state, joint: str) -> GluingReport`; `ineffective(state, place: str) ->
    GluingReport`; `affected_joints(state, changed: Iterable[str]) -> tuple[str, ...]`;
  - `disagreement_words(state, report: GluingReport) -> str`, the sentence of P 8;
  - `box_contains(box, point) -> bool`, used by the oracle tests and by Task 9.

- [ ] **Step 1: Write the failing tests**

```python
def test_u15_summer_wellness_disagreement_and_who_sees_it():
    s = e1_county_rules()        # C1, H1, H2, K1, K2, W1, L1 of P 13, with display names
    r = gluing(s, "place:la-county/summer-wellness")
    assert not r.too_complex and r.delta and not r.ineffective
    assert r.notify == stewards(s, "place:la-county/summer-wellness", "place:la-county/public-health",
                                "place:la-county/parks-and-rec")
    assert disagreement_words(s, r) == ("Parks and Recreation allows read in Summer Wellness for program-operations; "
        "Public Health does not. Until one of you changes your rules, Summer Wellness may only recall.")

def test_u15_ineffective_part_at_a_single_parent_place_goes_to_its_stewards():
    s = e1_county_rules(extra=("place:la-county/public-health/clinic-3", "imprint"))  # clinic-3 asks what H1 lacks
    r = ineffective(s, "place:la-county/public-health/clinic-3")
    assert r.ineffective and r.notify == stewards(s, "place:la-county/public-health/clinic-3")

def test_u15_box_cap_reports_could_not_check():
    s, joint = cap_breaking_joint()           # more than 4,096 boxes
    r = gluing(s, joint)
    assert r.too_complex and r.notify and disagreement_words(s, r).startswith("could not check: too complex")
```

In `test_permissions_properties.py`:
- `test_pt9_boxes` — on universes of up to 3 values per dimension and 4 time points, `box_and`, `box_minus`,
  `box_empty` and `box_subset` agree with brute force over every point.
- `test_pt11_gluing` — Δ and the ineffective parts from boxes equal the oracle's (`oracle_delta`,
  `oracle_ineffective`, added to `permissions_oracle.py` with the same collection expansion) at the current state.
  Plus `test_pt11_collection_fixture`: m in C1 and C2, own allows C1, parent A allows C2, parent B allows C3; it must
  report a disagreement.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_boxes.py tests/test_permissions_properties.py`
Expected: FAIL, `ImportError: cannot import name 'gluing'`.

- [ ] **Step 3: Implement boxes, `gluing`, `ineffective` and the words**

P 8 throughout. `s_i` is the meet of `anc(Q_i)`'s layers restricted to the uses at J; `own(J)` is J's layer;
`Δ(J) = own(J) ∩ (⋃ s_i \ ⋂ s_i)`. `notify` is J's stewards and those of every parent whose chain refuses part of Δ;
for an ineffective part, the place's stewards; for too-complex, the same as Δ. `affected_joints` returns joint places
whose own, parent or ancestor layer changed, or every joint place after a registry change, in id order.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/permissions.py engram/tests/permissions_oracle.py engram/tests/test_permissions_boxes.py \
        engram/tests/test_permissions_properties.py engram/tests/permissions_support.py
git commit -m "Permissions: boxes, the gluing check and ineffective parts (P 8)"
```

### Task 9: Write rules, narrowing, authority and words

**Files:**
- Modify: `engram/permissions.py`
- Test: `engram/tests/test_permissions_write_rules.py`

**Interfaces:**
- Consumes: Tasks 1 to 8.
- Produces:
  - `is_inside_home(state, layer: str, selector: Selector) -> bool` (P 5.4);
  - `check_record(state, record: Record) -> None`: P13's purposes and 366-day end for an outside-home allow; P28's two
    shapes; a deny's null end anywhere; at most `MAX_RECORDS_PER_LAYER` effective records per layer;
    `check_new_subject(state, obj: str, subject: str) -> None` (at most `MAX_SUBJECTS` of the object's own subjects;
    never refused because of its copies, P 7.4); `check_new_members(state, collection: str, count: int) -> None` (at
    most `MAX_COLLECTION`); each refusal raises `RuleError` naming the bound;
  - `check_narrower(state, new: Record, old: Record) -> None` (box subset of selector and interval) and
    `within_envelopes(state, selector: Selector, valid_from: int, valid_until: int | None, grant_id: str) -> bool`;
  - `placement_audience(state, record: Record | None, legacy_audience: str | None = None) -> str`, P 12.1's mapping;
  - `Act(kind: str, args: Mapping[str, object])`; `WIDENING_ACTS: frozenset[str]` (P 7.6's table);
    `Authority(outcome: str, backing: str, under_grant: str | None)` with outcome `do` or `proposal`;
    `authorize(state, actor: str, act: Act, *, channel: str, at: int) -> Authority`, raising `RuleError` when refused.
    It encodes P 4.4, 7.1, 7.2's op rules (P27) and 7.6: a widening act on channel `tool` files a proposal; on
    `terminal` or `migration` it applies the role rules to the actor the caller names. The CLI only ever names the
    ledger owner (Task 26); E1's county fixtures name their own stewards through the API (P 13);
  - `allow_words(state, record: Record) -> str` (P 7.6, using display names, R4) and
    `proposal_words(state, kind: str, body: Mapping) -> str` (P 7.7, from the body only).

- [ ] **Step 1: Write the failing tests**

```python
def test_u3_outside_home_allow_needs_purposes_and_an_end_within_366_days():
    s = county_world().state()
    base = dict(layer="place:home/andy", audience=["place:la-county/public-health"],
                collections=["collection:andy/medical-history"], actions=["recall"], valid_from=T("2026-11-01"))
    with pytest.raises(RuleError, match="5.4"):
        check_record(s, draft(**base, purposes="*", valid_until=T("2027-01-31")))
    with pytest.raises(RuleError, match="366"):
        check_record(s, draft(**base, purposes=["care-coordination"], valid_until=T("2026-11-01") + 367 * 86400))
    check_record(s, draft(**base, purposes=["care-coordination"], valid_until=T("2026-11-01") + 366 * 86400))
    check_record(s, draft(layer="place:home/andy", audience=["self"], actions=["recall"], purposes="*",
                          valid_from=T("2026-11-01"), valid_until=None))

def test_u3_outside_home_shapes_p28():
    s = county_world().state()
    with pytest.raises(RuleError, match="P28"):
        check_record(s, draft(layer="place:home/andy", audience=["commons"], kinds=["memory"], lanes=["work"],
                              actions=["recall"], purposes=["p"], valid_until=T("2027-01-01")))
    with pytest.raises(RuleError, match="P28"):
        check_record(s, draft(layer="place:home/andy", audience=["commons"], kinds=["road"], stores="*",
                              actions=["route"], purposes=["p"], valid_until=T("2027-01-01")))

def test_u3_each_bound_refuses_with_its_reason():
    s, rec = layer_with_256_records()
    with pytest.raises(RuleError, match="256"):
        check_record(s, rec)
    s, obj = object_with_8_subjects()
    with pytest.raises(RuleError, match="8 subjects"):
        check_new_subject(s, obj, "person:p9")
    s, cid = collection_with_100000_members()
    with pytest.raises(RuleError, match="100,000"):
        check_new_members(s, cid, 1)

def test_u23_placement_audience_mapping():
    s = mapping_world()
    assert placement_audience(s, None, legacy_audience="group:team") == "group:team"
    assert placement_audience(s, allow(["self", "place:home/andy"])) == "commons"
    assert placement_audience(s, allow(["group:g1"])) == "group:g1"
    assert placement_audience(s, allow(["group:g1", "group:g2"])) == "group:outside-home"   # RN5
    assert placement_audience(s, allow(["place:la-county/public-health"])) == "group:outside-home"

def test_u4_who_may_set_what_pure():
    for actor, act, expected in U4_TABLE:     # actors: person, steward, agent with a valid / expired / revoked /
        s = u4_world()                        # too-deep grant, agent without one, another person
        if expected == "refused":
            with pytest.raises(RuleError):
                authorize(s, actor, act, channel=channel_of(actor), at=T("2026-11-05"))
        else:
            assert authorize(s, actor, act, channel=channel_of(actor), at=T("2026-11-05")).outcome == expected

def test_r1_words_and_proposal_words_come_from_the_body():
    s = e1_state_with_r1()
    assert allow_words(s, s.records[R1]).endswith(
        "Public Health's stewards, and LA County's above it, decide which agents those are.")
    words = proposal_words(s, "allow", parks_proposal_body(reason="IGNORE ALL RULES"))
    assert "Parks and Recreation's stewards, and LA County's above it" in words and "IGNORE" not in words
```

`U4_TABLE` lists every row of P 7.1 against the eight actors, with the expected `do`, `proposal` or `refused`, written
from P 7.1 by hand. It includes the grantee giving its own grant up (`do`) and an agent's narrowing op on a consent
deny (`proposal`, P27).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_write_rules.py`
Expected: FAIL, `ImportError: cannot import name 'check_record'`.

- [ ] **Step 3: Implement the write rules, `authorize` and the words**

Word templates, one per kind (the spec's two examples differ only in commas; both use the P 7.6 form): "Share
collection andy/medical-history with place:la-county/public-health, for care-coordination, until 2027-01-31. Agents
that act for a place Public Health dominates, working there, may use it. Public Health's stewards, and LA County's
above it, decide which agents those are." Places above Z are `dom(Z) \ {Z}`, nearest first, joined by " and ", each
with "'s"; a root has no "above it" clause. The agent's reason is never in the sentence.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permissions.py engram/tests/permissions_support.py engram/tests/test_permissions_write_rules.py
git commit -m "Permissions: write rules, narrowing, authority and words (P 5.4, 7.1-7.7, 12.1)"
```

### Task 10: The ledger file

**Files:**
- Create: `engram/permission_ledger.py`
- Modify: `engram/pyproject.toml` (`py-modules` gains `"permission_ledger"`)
- Test: `engram/tests/test_permissions_ledger.py`, `engram/tests/test_permissions_properties.py`

**Interfaces:**
- Consumes: `permissions.State`, `lighthouse_protocol.canonical_json`.
- Produces:
  - `ledger_path(engram_home: Path) -> Path` (`engram_home / ".engram" / "permissions.db"`, fixed);
  - `class LedgerUnreadable(Exception)`; `new_id(prefix: str) -> str` (`prefix` + 32 hex from `os.urandom`);
  - `class Ledger` with `create(engram_home, owner_handle: str, *, now: int) -> Ledger` (classmethod: writes meta
    `ledger_id` (UUID4), `schema_version` `1`, `owner` `person:<handle>`, `admins`, then registers the owner and the
    home); `open(engram_home) -> Ledger` (writer); `open_read_only(engram_home) -> Ledger` (`mode=ro`,
    `query_only`, raising `FileNotFoundError` or `LedgerUnreadable`); `conn` (its `sqlite3` connection); `close()`;
    `seq() -> int`;
    `state(seq: int | None = None) -> State`; `meta() -> dict`; `tables() -> dict[str, list[dict]]`;
    `verify() -> int | None` (the first bad `seq`, or `None`); `rebuild(dest: Path) -> Path`; and the internal
    `_append(kind, ref, actor, channel, body, *, under_grant=None, proposal_id=None, at) -> int`, which writes one
    `ledger_log` row and its projection in one `BEGIN IMMEDIATE`.

- [ ] **Step 1: Write the failing tests**

```python
def test_init_writes_meta_owner_and_home(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    meta = led.meta()
    assert meta["schema_version"] == "1" and meta["owner"] == "person:andy" and uuid.UUID(meta["ledger_id"])
    assert led.state().persons["person:andy"].home == "place:home/andy"
    assert ledger_path(tmp_path) == tmp_path / ".engram" / "permissions.db"

def test_u8_the_log_chain_verifies_and_one_changed_byte_fails(tmp_path):
    led = small_ledger(tmp_path)              # init plus ten registry rows written through _append
    assert led.verify() is None
    flip_one_byte_in_log_body(ledger_path(tmp_path), seq=4)
    assert Ledger.open(tmp_path).verify() == 4

def test_rebuild_gives_the_same_tables(tmp_path):
    led = small_ledger(tmp_path)
    assert Ledger.open(led.rebuild(tmp_path / "copy.db")).tables() == led.tables()

def test_state_at_an_older_seq_hides_later_rows(tmp_path): ...

def test_u9_read_only_open_changes_no_byte(tmp_path):
    small_ledger(tmp_path).close()
    before = ledger_path(tmp_path).read_bytes()
    ro = Ledger.open_read_only(tmp_path); ro.state(); ro.state(1)
    assert ro.conn.total_changes == 0 and ledger_path(tmp_path).read_bytes() == before
    assert sorted(p.name for p in (tmp_path / ".engram").iterdir()) == ["permissions.db"]

def test_rf5_two_writers_keep_one_chain(tmp_path):
    small_ledger(tmp_path).close()
    run_in_two_processes(tmp_path, appends_each=50)   # multiprocessing, each opens its own Ledger
    led = Ledger.open(tmp_path)
    seqs = [row["seq"] for row in led.tables()["ledger_log"]]
    assert seqs == list(range(1, len(seqs) + 1)) and led.verify() is None
    assert Ledger.open(led.rebuild(tmp_path / "copy.db")).tables() == led.tables()
```

In `test_permissions_properties.py`: `test_pt10_determinism_after_replay` — for random worlds written through
`Ledger._append`, `decide` on `led.state(s)` equals `decide` on the rebuilt file's `state(s)` for random `s`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_ledger.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'permission_ledger'`.

- [ ] **Step 3: Implement `engram/permission_ledger.py`**

The schema is P 5.5's `CREATE TABLE` statements verbatim, plus indexes. Journal mode per R1. `_append` reads the last
digest inside its transaction. Its projection code covers every log kind, records, grants and proposals included, so
`rebuild`, `test_pt10_determinism_after_replay` and the fixtures of Tasks 11 to 13 can write any row through it. `rebuild` replays `ledger_log` into a fresh file through the same projection code.
`state(seq)` filters rows by their `*_seq` columns and reads display names from `register-place` bodies (R4). Add
`"permission_ledger"` to `py-modules`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_ledger.py tests/test_permissions_properties.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_ledger.py engram/pyproject.toml engram/tests/test_permissions_ledger.py \
        engram/tests/test_permissions_properties.py
git commit -m "Permission ledger: schema, hash-chained log, projections, state(seq) and rebuild (P 5.5, 5.6)"
```

### Task 11: Registry acts

**Files:**
- Modify: `engram/permission_ledger.py`
- Test: `engram/tests/test_permissions_acts.py`

**Interfaces:**
- Consumes: Task 9's `Act` and `authorize`; Task 8's `affected_joints` and `gluing`; Task 10.
- Produces:
  - `Ledger.perform(act: Act, *, actor: str, channel: str, now: int) -> Outcome`;
    `Outcome(status: str, ref: str, seq: int, reports: tuple[GluingReport, ...], pending_checks: tuple[str, ...])`,
    `status` `done` or `proposal` (R3, R5);
  - act kinds here: `register-person`, `retire-person`, `register-place` (args `place`, `parents`, `name`,
    `stewards`: at least one registered person, since a place keeps at least one steward, P 4.4), `add-parent`,
    `add-steward`, `remove-steward`, `retire-place`, `register-agent` (`agent`, `acts_for`), `put-agent`,
    `remove-agent`, `register-store` (`instance_id`, `name`, `owner`, `place`, `imprint_of`), `group` (`group`,
    `members`), `make-collection`, `collect` (`collection`, `refs`, and `lanes`: for each ref, `{"lane",
    "created_at"}` or null), `uncollect`, `add-subject`, `remove-subject`;
  - who passes `lanes`: the ledger can't read a store, so the caller reads each memory's lane and `created_at` from
    its store and passes them. The CLI (Task 26) opens the store the ref names with `Storage.open_read_only`;
    `migrate` (Task 28) reads them while it checks each row; the server's `share` reads its own storage (Task 23). A
    ref whose store can't be read on this machine gets null and no first note, so it matches no lane-limited allow
    (U25's rule fails closed);
  - proposals: `perform` files one when `authorize` says so, with the full change in its body; act kinds `sign` and
    `decline` (args `proposal`) act on it, one at a time; a `joint-place` or `put-agent` proposal completes when every
    signer it needs has signed (R6). Task 12 adds record proposals, their expiry and their words;
  - `Ledger.record_copy(copy_ref: str, source_ref: str, *, now: int) -> None`: the `copies` row and the source's
    subjects as co-subjects with `added_by` `copy:<source ref>`, in one transaction, before the store write; refused
    past `MAX_COPY_CHAIN` links or `MAX_SUBJECTS` subjects;
  - read accessors for the other plans: `Ledger.store_row(instance_id: str) -> dict | None` and
    `Ledger.cosubjects(ref: str) -> frozenset[str]` (effective co-subjects other than the default subject).

- [ ] **Step 1: Write the failing tests**

```python
def test_u2_a_joint_place_waits_for_every_parents_steward(tmp_path):
    led = county_ledger(tmp_path)             # stewards ph-steward and pr-steward, written through perform
    out = led.perform(Act("register-place", {"place": SW, "parents": [PH, PR], "name": "Summer Wellness"}),
                      actor="person:ph-steward", channel="terminal", now=T("2026-11-01"))
    assert out.status == "proposal" and SW not in led.state().places
    led.perform(Act("sign", {"proposal": out.ref}), actor="person:pr-steward", channel="terminal",
                now=T("2026-11-01"))
    assert SW in led.state().places

def test_u2_one_place_per_agent_and_retiring_a_person(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)   # ph-steward stewards public-health and clinic-3, so it is both
    with pytest.raises(RuleError, match="P31"):  # the target's steward and ph-coordinator's principal
        led.perform(Act("put-agent", {"agent": "agent:ph-coordinator", "place": PH}),
                    actor="person:ph-steward", channel="terminal", now=T("2026-11-01"))
    led.perform(Act("retire-person", {"person": "person:jenn"}), actor="person:andy", channel="terminal",
                now=T("2026-11-01"))
    assert decide(led.state(), read_by_ph(M3, T("2026-11-02"))).refusal.code == "RETIRED"

def test_u20_putting_an_agent_in_a_place_needs_its_principal(tmp_path):
    led = county_ledger(tmp_path)              # agent:parks-intern acts for parks-and-rec and is in no place yet
    out = led.perform(Act("put-agent", {"agent": "agent:parks-intern", "place": PH}),
                      actor="person:ph-steward", channel="terminal", now=T("2026-11-01"))
    assert out.status == "proposal"            # waits for a parks-and-rec steward, the principal
    led.perform(Act("sign", {"proposal": out.ref}), actor="person:pr-steward", channel="terminal",
                now=T("2026-11-01"))
    assert agent_place_at(led.state(), "agent:parks-intern", T("2026-11-02")) == PH

def test_u5_co_subjects(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)   # m3 has Jenn as co-subject; Jenn's home layer is empty
    assert decide(led.state(), read_by_ph(M3, T("2026-11-02"))).refusal == Refusal("NO_ALLOW", "place:home/jenn",
                                                                                      "recall")
    add_subject(led, M5, "person:amy", actor="agent:rio-grande", channel="tool")
    remove_subject(led, M5, "person:amy", actor="person:andy")           # his agent added it: allowed
    add_subject(led, M6, "person:jenn", actor="person:jenn", self_claimed=True)   # an API fixture (P 7.4)
    led.record_copy(COPY_OF_M3, M3, now=T("2026-11-03"))                  # the copy carries Jenn
    for ref in (M6, COPY_OF_M3):
        with pytest.raises(RuleError, match="7.4"):
            remove_subject(led, ref, "person:jenn", actor="person:andy")
    src, copy = source_with_copy_at_8_subjects(led)                        # the copy's union holds 8
    add_subject(led, src, "person:p9", actor="person:andy")                # written: never refused for its copies
    assert decide(led.state(), read_copy(copy)).refusal.code == "BOUND"

def test_pt7_a_copy_chain_deeper_than_4_is_refused_when_made(tmp_path):
    led = copies_ledger(tmp_path, chain=4)
    with pytest.raises(RuleError, match="4 links"):
        led.record_copy("mem:K5/episode/c5", "mem:K4/episode/c4", now=T("2026-11-02"))

def test_u15_the_check_reruns_after_a_registry_change(tmp_path):
    led = e1_county_ledger(tmp_path)
    out = led.perform(Act("add-steward", {"place": "place:la-county/summer-wellness", "person": "person:sw2"}),
                      actor="person:sw-steward", channel="terminal", now=T("2026-11-02"))
    assert "place:la-county/summer-wellness" in {r.place for r in out.reports}
```

`add_subject` and `remove_subject` are test helpers over `perform`. The self-claimed row is written through
`perform` with the co-subject (`person:jenn`) as actor on the API; P 7.4 notes the CLI can't do that in step 1. The
self-claim's line in Andy's list is tested in Task 15.

The fixture builders, added to `permissions_support.py` here. Every row goes through `perform` on channel `terminal`
as the actor named, except where `_append` is named: `allow` and `grant` are Task 12's acts, so until then those rows
are written through `Ledger._append` (Task 10's projection covers them), with the same actor, channel and time. They
stay that way after Task 12; Task 29 builds E1 through `perform` alone.

- `county_ledger(tmp_path)`: `Ledger.create(tmp_path, "andy", now=T("2026-11-01"))`. As `person:andy`: register
  persons `county-steward`, `ph-steward`, `pr-steward`, `sw-steward`, `sw2`, `jenn` and `amy` (Amy's home layer stays
  empty, so a use she is a subject of refuses with `NO_ALLOW` at `place:home/amy`, P 7.4; Task 11's U5 test and Task
  25's U17 tests use this Amy), and the root
  `place:la-county` ("LA County", stewards `[person:county-steward]`). As `person:county-steward`: register
  `public-health` ("Public Health", `[person:ph-steward]`) and `parks-and-rec` ("Parks and Recreation",
  `[person:pr-steward]`). As `person:ph-steward`: register `clinic-3` (`[person:ph-steward]`); register
  `agent:ph-coordinator` acting for clinic-3 and put it in clinic-3. As `person:pr-steward`: register
  `agent:parks-planner` acting for parks-and-rec and put it there; register `agent:parks-intern` acting for
  parks-and-rec, in no place. As `person:andy`: register `agent:rio-grande` acting for him and put it at
  `place:home/andy`. No store and no record.
- `e1_ledger_through_andys_side(tmp_path)`: `county_ledger`, then as `person:andy`: register store `S` (Andy's
  engram, owner `person:andy`, at `place:home/andy`), store `HOUSE` (the published house, same owner and place) and
  store `K` (a keeper's store for `COPY_OF_M3`, same owner and place); `make-collection`
  `collection:andy/medical-history`; `collect` m1, m2 and m3 (lanes `personal`, `created_at` 2026-10-01);
  `add-subject` m3 `person:jenn`. Then through `_append`, as `person:andy` at 2026-11-01: R1 and G1 exactly as P 13.
  M5 and M6 are refs in S with no row beyond their subjects. The ids namespace is on `led.ids`.
- `e1_county_ledger(tmp_path)`: `e1_ledger_through_andys_side`, then the joint place `summer-wellness` ("Summer
  Wellness", parents public-health and parks-and-rec, stewards `[person:sw-steward]`; filed by `ph-steward`, signed
  by `pr-steward`), `agent:sw-helper` acting for and in it, and P 13's county records C1, H1, H2, K1, K2, W1 and L1,
  each through `_append` as its layer's steward.
- `copies_ledger(tmp_path, chain)`: `county_ledger` plus stores K0 to K5 at `place:home/andy` and a chain of `chain`
  copies `mem:K1/episode/c1` ← … made with `record_copy`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_acts.py`
Expected: FAIL, `AttributeError: 'Ledger' object has no attribute 'perform'`.

- [ ] **Step 3: Implement `perform` for registry acts, `record_copy`, `store_row` and `cosubjects`**

`perform` takes the state, calls `authorize`, refuses with `RuleError`, files a proposal when it says so (P 7.7's body
holds the full change), otherwise writes the row and its projection, then returns `Outcome` with the gluing reports of
`affected_joints` (R5). `register-person` creates the home with an empty layer; `register-place` writes a 16-byte
salt (R16); `collect` writes a first lane note, at the passed `created_at` with the passed lane, for a memory that
has none and whose `lanes` entry is not null (P 5.3).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_ledger.py engram/tests/permissions_support.py engram/tests/test_permissions_acts.py
git commit -m "Permission ledger: registry acts, co-subjects and kept copies through one perform (P 4.4, 7.4)"
```

### Task 12: Records, grants and proposals

**Files:**
- Modify: `engram/permission_ledger.py`
- Test: `engram/tests/test_permissions_records.py`, `engram/tests/test_permissions_properties.py`

**Interfaces:**
- Consumes: Task 11.
- Produces: act kinds `allow`, `deny` (args `layer`, `selector`, `valid_from`, `valid_until`, `reason`), `revoke`
  (`record`, `reason`), `shorten` (`record`, `valid_until`), `narrow` (`record`, `selector`), `grant` (`grantee`,
  `layer`, `ops`, `envelope`, `max_days`, `depth`, `hours`, `parent`), `revoke-grant`, `give-up-grant`; `sign` and
  `decline` (Task 11) extended to record proposals, which expire after `PROPOSAL_DAYS` and are signed by their
  `for_person` only; `Ledger.proposals(*, now: int) -> list[dict]` (open ones, each with `words` generated by
  `proposal_words` and the agent's reason apart); a replacement keeps its original's `anchor` and backing (P 7.3).
  An agent's widening registry act on channel `tool` (R26: `grant`, `group`, `register-agent`, `put-agent`,
  `add-steward`, `register-place`, `add-parent`, `register-store`, `remove-subject`, a person-backed `collect`) is
  filed as a proposal for the ledger owner, with the full `Act` in its body, and `sign` by the owner completes it by
  running that `Act` as the owner on channel `terminal`. Task 13 adds `gate` to these kinds.

- [ ] **Step 1: Write the failing tests**

```python
def test_r26_an_agents_widening_registry_act_is_a_proposal_that_sign_completes(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    for act in R26_SAMPLE_ACTS:        # one Act of each kind R26 names, each valid for Andy to make
        before = led.tables()
        out = led.perform(act, actor="agent:rio-grande", channel="tool", now=T("2026-11-03"))
        assert out.status == "proposal" and only_proposal_rows_changed(before, led.tables()), act.kind
        done = led.perform(Act("sign", {"proposal": out.ref}), actor="person:andy", channel="terminal",
                           now=T("2026-11-03"))
        assert done.status == "done" and applied(led.state(), act), act.kind

def test_u7_revoking_a_grant_ends_its_shares_and_collects_and_keeps_the_rest(tmp_path):
    led, ids = e1_through_use_9(tmp_path)    # G1; a share by rio-grande; m4 collected; R1′ by shortening; D1
    led.perform(Act("revoke-grant", {"grant": ids.G1}), actor="person:andy", channel="terminal", now=T("2026-11-20"))
    s = led.state()
    assert not decide(s, read_by_ph(ids.SHARED_BY_AGENT, T("2026-11-21"))).allowed
    assert not decide(s, read_by_ph(M4, T("2026-11-21"))).allowed
    assert decide(s, read_by_ph(M1, T("2026-11-21"))).allowed          # R1′ is person-backed
    assert s.records[ids.D1].revoked_seq is None and s.records[ids.R1P].backing == "person"

def test_u14_proposals(tmp_path):
    led = e1_ledger_with_g1(tmp_path)
    out = led.perform(Act("allow", parks_body()), actor="agent:rio-grande", channel="tool", now=T("2026-11-03"))
    assert out.status == "proposal"
    [p] = led.proposals(now=T("2026-11-03"))
    assert p["words"].startswith("Share collection andy/medical-history with place:la-county/parks-and-rec")
    assert led.proposals(now=T("2026-11-10") + 1) == []                       # 7 days
    with pytest.raises(RuleError, match="expired"):
        led.perform(Act("sign", {"proposal": out.ref}), actor="person:andy", channel="terminal",
                    now=T("2026-11-10") + 1)
    second = led.perform(Act("allow", parks_body()), actor="agent:rio-grande", channel="tool", now=T("2026-11-04"))
    done = led.perform(Act("sign", {"proposal": second.ref}), actor="person:andy", channel="terminal",
                       now=T("2026-11-04"))
    rec = led.state().records[done.ref]
    assert rec.backing == "person" and rec.proposal_id == second.ref
    before = led.tables()
    third = led.perform(Act("allow", parks_body()), actor="agent:rio-grande", channel="tool", now=T("2026-11-04"))
    led.perform(Act("decline", {"proposal": third.ref}), actor="person:andy", channel="terminal", now=T("2026-11-04"))
    assert only_proposal_rows_changed(before, led.tables())

def test_shortening_and_narrowing_write_a_replacement_inside_the_original(tmp_path):   # P 7.3, 5.3 rule 4, E1 use 8
    led = e1_ledger_with_g1(tmp_path); ids = led.ids
    out = led.perform(Act("shorten", {"record": ids.R1, "valid_until": T("2026-12-15")}), actor="agent:rio-grande",
                      channel="tool", now=T("2026-11-10"))
    s = led.state(); r1, r1p = s.records[ids.R1], s.records[out.ref]
    assert out.status == "done" and r1.revoked_seq == r1p.created_seq                   # one transaction
    assert (r1p.replaces, r1p.anchor, r1p.backing, r1p.set_by, r1p.under_grant) == (
        ids.R1, r1.anchor, "person", "agent:rio-grande", ids.G1)                           # R1 was person-backed
    assert (r1p.selector, r1p.valid_from, r1p.valid_until) == (r1.selector, r1.valid_from, T("2026-12-15"))
    narrower = dataclasses.replace(r1p.selector, actions=("read", "recall"))              # inject_context dropped
    out2 = led.perform(Act("narrow", {"record": out.ref, "selector": selector_json(narrower)}),
                       actor="agent:rio-grande", channel="tool", now=T("2026-11-11"))
    r1pp = led.state().records[out2.ref]
    assert (r1pp.replaces, r1pp.anchor, r1pp.selector, r1pp.valid_until) == (out.ref, r1.anchor, narrower,
                                                                              T("2026-12-15"))
    assert led.state().records[out.ref].revoked_seq == r1pp.created_seq
    before = led.tables()
    wider_audience = dataclasses.replace(narrower, audience=("place:la-county/parks-and-rec",
                                                             "place:la-county/public-health"))
    for widening in (Act("shorten", {"record": out2.ref, "valid_until": T("2027-01-31")}),   # later than its end
                     Act("narrow", {"record": out2.ref, "selector": selector_json(wider_audience)})):
        with pytest.raises(RuleError):                     # check_narrower: not inside the record it replaces
            led.perform(widening, actor="person:andy", channel="terminal", now=T("2026-11-12"))
    assert led.tables() == before

def test_an_agents_try_on_a_consent_deny_is_a_proposal(tmp_path):   # P27, E1 use 9
    led, ids = e1_through_use_9(tmp_path)                      # D1 denies m2 from 2026-12-01; G1 meets it
    d1 = led.state().records[ids.D1].selector               # audience public-health, memories [m2]
    at_clinic = dataclasses.replace(d1, audience=("place:la-county/public-health/clinic-3",))
    for act in (Act("revoke", {"record": ids.D1, "reason": "r"}),
                Act("shorten", {"record": ids.D1, "valid_until": T("2026-12-10")}),
                Act("narrow", {"record": ids.D1, "selector": selector_json(at_clinic)})):
        before = led.tables()
        out = led.perform(act, actor="agent:rio-grande", channel="tool", now=T("2026-11-13"))
        assert out.status == "proposal" and only_proposal_rows_changed(before, led.tables()), act.kind
        [p] = [p for p in led.proposals(now=T("2026-11-13")) if p["id"] == out.ref]
        assert (p["by_agent"], p["for_person"]) == ("agent:rio-grande", "person:andy"), act.kind
    assert led.state().records[ids.D1].revoked_seq is None
    assert decide(led.state(), read_by_ph(M2, T("2026-12-01"))).refusal == Refusal("DENIED", "place:home/andy",
                                                                                   "recall")
    own = led.perform(Act("deny", {"layer": "agent:rio-grande", "selector": selector_json(d1),
                                   "valid_from": T("2026-11-13"), "valid_until": None, "reason": "r"}),
                      actor="agent:rio-grande", channel="tool", now=T("2026-11-13"))
    revoked = led.perform(Act("revoke", {"record": own.ref, "reason": "r"}), actor="agent:rio-grande",
                          channel="tool", now=T("2026-11-13"))
    assert (own.status, revoked.status) == ("done", "done")   # its own restriction deny needs no one (P 7.1)

def test_the_grantee_can_give_its_own_grant_up(tmp_path): ...            # U4's last sentence
```

In `test_permissions_properties.py`: `test_pt2_narrowing_ops` — on a random ledger, a random op from 7.2's narrowing
list (revoke, shorten or narrow an allow, add a deny, add a subject, remove a collection member) applied through
`perform` never adds an allowed use (checked against `decide` and the oracle); every narrowing op tried on a random
consent-layer deny by an agent is refused or filed as a proposal (P27).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_records.py`
Expected: FAIL, `RuleError: unknown act kind 'allow'`.

- [ ] **Step 3: Implement the record, grant and proposal acts**

Each act calls `check_record`, `check_narrower`, `within_envelopes`, `check_root_grant` or `check_child_grant` as P 7
says, then writes. A shortening or narrowing revokes R and writes R′ with `replaces` R in one transaction. A deny an
agent writes under a grant is person-backed (P 7.3).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_records.py tests/test_permissions_properties.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_ledger.py engram/tests/permissions_support.py engram/tests/test_permissions_records.py \
        engram/tests/test_permissions_properties.py
git commit -m "Permission ledger: records, replacements, grants and proposals (P 7.1-7.3, 7.7)"
```

### Task 13: The gate, the houses and `PlaceRules`

**Files:**
- Modify: `engram/permission_ledger.py`
- Test: `engram/tests/test_permissions_gate.py`

**Interfaces:**
- Consumes: Tasks 10 to 12; `lighthouse_protocol.artifact_digest`.
- Produces:
  - `houses(engram_home: Path) -> list[Path]`: `.engram/graph.db` and every `.engram/instances/<name>/graph.db`
    that exists, sorted;
  - `Gate(mode: str, cause: str | None)` with mode `off`, `shadow`, `enforce` or `closed`;
  - `effective_gate(engram_home: Path, served: Sequence[Path], *, busy_ms: int = 5000) -> Gate`: P 12.3 rules 1 to 3,
    reading at most `GATE_HOUSES` houses' `meta` for the `off` rule and `closed` past that. It opens the ledger with
    `busy_ms` as its busy timeout (the daemon passes `LEDGER_BUSY_MS`, Task 19). A served path that is not a file is
    left out (R32): it is no house and serves nothing;
  - act kind `gate` (args `mode` only; any other argument is refused with `RuleError`): `perform` computes, when it
    applies the act, the published house `<root>/.engram/instances/lighthouse/graph.db` and `houses(root)`, where
    `root` is the `engram_home` the ledger was created or opened with. So whether the owner acts at the terminal or
    signs an agent's proposal, the houses are those on disk at the yes, never ones named by a caller or held in a
    proposal's body (R26). The first move above `off` sets `gate_raised` and marks every house (R17), refusing when the
    published house does not exist; running it again marks houses that lack the id. Its log body records the mode and
    the houses it marked. From an agent on channel `tool` it is filed as a proposal holding `{"mode": ...}` alone,
    which the owner's `sign` completes (R26). Its `Outcome` lists the houses that lack migration 029 (R27), so the CLI
    can print them;
  - `Ledger.gate_plan() -> dict` with `published_house`, `houses` and `lacking_029`: what a `gate` act would use if
    applied now. The CLI's `gate` (Task 27) and its `sign` of a gate proposal (Task 26A) print it before the yes;
  - `ledger_for_house(db_path: Path) -> Path | None` and `house_mark(db_path: Path) -> str | None` (the id to write
    into a house created now, `"unreadable"`, or `None` when no raised ledger exists), used by Task 16;
  - `Ledger.place_rules(place: str, *, now: int) -> dict`, P 9.4's artifact; it raises `RuleError` for a home.

- [ ] **Step 1: Write the failing tests**

```python
def test_u16_off_with_no_ledger_and_no_marked_house(tmp_path):
    make_house(tmp_path, "lighthouse")
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("off", None)

def test_u16_a_raise_with_no_published_house_is_refused(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    with pytest.raises(RuleError, match="published house"):
        raise_gate(led, "shadow")

def test_u16_the_raise_marks_every_house(tmp_path):
    led = raised_ledger(tmp_path, houses=("lighthouse", "why"))
    for house in houses(tmp_path):
        assert house_meta(house)["permissions_ledger_id"] == led.meta()["ledger_id"]
    assert effective_gate(tmp_path, houses(tmp_path)).mode == "shadow"
    absent = tmp_path / ".engram" / "instances" / "pending" / "graph.db"        # configured, not yet made (R32)
    assert effective_gate(tmp_path, houses(tmp_path) + [absent]).mode == "shadow"

def test_rs2_a_gate_proposal_holds_only_its_mode_and_sign_marks_the_houses_on_disk_at_the_yes(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    make_house(tmp_path, "lighthouse"); register_default_agent_at_home(led)    # agent:default acts for Andy
    with pytest.raises(RuleError, match="only mode"):
        led.perform(Act("gate", {"mode": "shadow", "houses": []}), actor="agent:default", channel="tool",
                    now=T("2026-11-02"))
    out = led.perform(Act("gate", {"mode": "shadow"}), actor="agent:default", channel="tool", now=T("2026-11-02"))
    assert out.status == "proposal" and proposal_act(led, out.ref) == Act("gate", {"mode": "shadow"})
    make_house(tmp_path, "late")                       # made after the agent asked; no raised ledger yet, so no mark
    assert led.gate_plan()["houses"] == houses(tmp_path)
    led.perform(Act("sign", {"proposal": out.ref}), actor="person:andy", channel="terminal", now=T("2026-11-02"))
    late = tmp_path / ".engram" / "instances" / "late" / "graph.db"
    assert house_meta(late)["permissions_ledger_id"] == led.meta()["ledger_id"]
    assert effective_gate(tmp_path, houses(tmp_path)).mode == "shadow"

def test_u16_after_the_raise_each_of_these_fails_closed(tmp_path):
    for damage in (delete_ledger, make_ledger_unreadable, swap_in_another_ledger, set_unknown_gate_value,
                   delete_gate_key):
        root = fresh_raised(tmp_path / damage.__name__)
        damage(root)
        assert effective_gate(root, houses(root)).mode == "closed", damage.__name__

def test_u16_a_deleted_ledger_reads_closed_for_every_reader(tmp_path):
    root = fresh_raised(tmp_path); delete_ledger(root); make_house(root, "late")   # made after the deletion
    assert effective_gate(root, [root / ".engram/instances/late/graph.db"]).mode == "closed"

def test_u16_with_no_ledger_and_more_than_64_houses_a_reader_reads_closed(tmp_path):
    for i in range(65):
        make_house(tmp_path, f"h{i}")
    assert effective_gate(tmp_path, houses(tmp_path)[:1]).mode == "closed"

def test_u8_home_rules_are_not_exported(tmp_path):
    led = e1_county_ledger(tmp_path)
    with pytest.raises(RuleError, match="9.4"):
        led.place_rules("place:home/andy", now=T("2026-11-02"))
    art = led.place_rules("place:la-county/public-health", now=T("2026-11-02"))
    assert art["kind"] == "PlaceRules" and verify_artifact_digest(art) and art["payload"]["ledgerSeq"] == led.seq()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_gate.py`
Expected: FAIL, `ImportError: cannot import name 'effective_gate'`.

- [ ] **Step 3: Implement the gate, the houses and `place_rules`**

`effective_gate` opens the ledger read-only (Task 10) and each house's `meta` with `mode=ro`. Every cause is a short
sentence the daemon and server print, for example `"ledger missing but house why carries its id"`. A hot journal left
by a writer that died mid-commit reads `closed` (R1), with the cause "ledger has a hot journal; any writing open
clears it, such as engram-permissions sweep".
`place_rules`' payload is `{place, parents, stewards, retired, ledgerSeq, logDigest, records}` with every effective
record in all fields; `issuer` is `urn:engram:<ledger_id>`. `register_default_agent_at_home` and `proposal_act` (the
`Act` a proposal's body holds) are added to `permissions_support.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_ledger.py engram/tests/permissions_support.py engram/tests/test_permissions_gate.py
git commit -m "Permission ledger: the gate, the effective gate over houses, and PlaceRules (P 9.4, 12.3)"
```

### Task 14: The receipts file

**Files:**
- Create: `engram/permission_uses.py`
- Modify: `engram/pyproject.toml` (`py-modules` gains `"permission_uses"`)
- Test: `engram/tests/test_permissions_uses.py`

**Interfaces:**
- Consumes: `permissions.Decision`, `Use`, `BulkUse`; `lighthouse_protocol.canonical_json`.
- Produces:
  - `uses_path(engram_home) -> Path` (`.engram/permission-uses.db`);
  - `UseRow`, a frozen dataclass of P 9.1's `uses` columns other than `seq`, `prev_digest` and `digest`;
  - `row_for_decision(decision, use, *, acting_for, content_digest=None, shadow=False) -> UseRow` (one read or
    delivery item, or one answer use on a road or trail: `object` the road or trail ref, `returned` the memories it
    named, R15); `row_for_recall(decisions, use, *, acting_for, returned: Sequence[str], filtered: int,
    shadow=False) -> UseRow` (R8); `row_for_bulk(decision, bulk, *, acting_for) -> UseRow` (named: count and SHA-256;
    counted: count) (R15);
  - `class Uses` with `open(engram_home) -> Uses`, `open_read_only(engram_home) -> Uses`, `append(row: UseRow,
    subjects: Sequence[tuple[str, str]]) -> str` (returns `id`; one `BEGIN IMMEDIATE`), `append_imported(row: UseRow,
    subjects)` (asserts the imported form of P 9.1: `object` null, `copy` an `imprint:` ref, `cited` record ids only,
    `returned` may be null for a counted row), `verify() -> int | None`, `fold(*, now: int) -> int`;
  - `cited` JSON: a list of `{"layer", "kind", "action", "verdict", "record" | "records", "version"}`; `refusal` JSON:
    `{"code", "layer", "action"}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_u8_a_recall_writes_one_receipt_with_returned_and_filtered_and_no_filtered_subjects(tmp_path):
    uses = Uses.open(tmp_path)
    rid = uses.append(recall_row(returned=[M1, M2], filtered=1), subjects=[("person:andy", M1), ("person:andy", M2)])
    [row] = rows(uses)
    assert json.loads(row["returned"]) == [M1, M2] and row["filtered"] == 1 and row["copy"] == HOUSE
    assert {r["object"] for r in subject_rows(uses)} == {M1, M2}

def test_u8_a_read_writes_one_receipt_per_item_and_none_holds_content_or_query(tmp_path):
    uses = write_read_of_three_items(tmp_path, content="Jenn drove me to the clinic", query="who drove")
    assert len(rows(uses)) == 3
    raw = uses_path(tmp_path).read_bytes()
    assert b"Jenn drove" not in raw and b"who drove" not in raw and all(r["copy"] for r in rows(uses))

def test_u8_the_chain_verifies_and_one_changed_byte_fails(tmp_path):   # the receipts chain; Task 10 tests the log's
    uses = Uses.open(tmp_path)
    for i in range(10):
        uses.append(recall_row(returned=[M1], filtered=0, at=T("2026-11-02") + i), subjects=[("person:andy", M1)])
    assert uses.verify() is None
    flip_one_byte(uses_path(tmp_path), table="uses", seq=4, column="cited")   # its own sqlite3 connection
    assert Uses.open(tmp_path).verify() == 4

def test_u22_five_roads_are_five_route_uses_with_five_receipts(tmp_path):
    s = five_road_world()                         # roads ROADS[0] to ROADS[4], each naming A and B, all allowed
    uses = Uses.open(tmp_path)
    for road in ROADS:                            # one answer that walks five roads: five route uses
        u = route(road, names=(A, B), shows={A})
        d = decide(s, u)
        assert d.allowed, road
        uses.append(row_for_decision(d, u, acting_for=HOME),
                    subjects=[(p, road) for p in subjects_of(s, road, u.at, u.names)])
    route_rows = [r for r in rows(uses) if r["action"] == "route"]
    assert [r["object"] for r in route_rows] == list(ROADS) and len({r["id"] for r in route_rows}) == 5
    assert all(json.loads(r["returned"]) == sorted([A, B]) for r in route_rows)   # the memories each named (R15)

def test_u22_a_counted_bulk_use_writes_one_receipt_naming_no_object(tmp_path):
    uses = Uses.open(tmp_path)
    uses.append(row_for_bulk(allowed_bulk_route(3), BULK, acting_for=HOME), subjects=[("person:andy", HOUSE)])
    [row] = rows(uses)
    assert row["object"] is None and json.loads(row["returned"]) == {"count": 3}
    assert [r["object"] for r in subject_rows(uses)] == [HOUSE]

def test_u22_a_named_batch_holds_its_count_and_the_sha256_of_its_sorted_objects(tmp_path):
    objects = sorted(batch_refs(512))
    row = write_named_batch(tmp_path, objects)
    assert json.loads(row["returned"]) == {"count": 512,
                                           "sha256": hashlib.sha256("\n".join(objects).encode()).hexdigest()}

def test_xs2_an_imported_counted_row_may_hold_null_returned(tmp_path): ...

def test_u27_the_daemon_and_a_server_writing_at_once_keep_one_chain(tmp_path):
    run_in_two_processes_appending(tmp_path, each=100)
    assert Uses.open(tmp_path).verify() is None

def test_u27_after_the_400_day_fold_the_chain_verifies_from_its_anchor(tmp_path):
    uses = rows_spanning_days(tmp_path, days=420)
    folded = uses.fold(now=T("2026-11-01") + 420 * 86400)
    assert folded > 0 and uses.verify() is None and monthly_counts(uses)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_uses.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'permission_uses'`.

- [ ] **Step 3: Implement `engram/permission_uses.py`**

P 9.1's four `CREATE TABLE` statements verbatim. Journal mode per R1. `append` reads the last digest inside its
transaction. `fold` moves rows older than `RETENTION_DAYS` into `uses_monthly`, deletes them and their
`use_subjects`, and writes one `uses_anchor` row with the last folded `seq` and digest; `verify` starts from the
latest anchor. Add `"permission_uses"` to `py-modules`. The test helpers `flip_one_byte(path, *, table, seq, column)`
(changes one character of that row's column through its own `sqlite3` connection), `five_road_world` (Task 7's
`road_world` with five roads `ROADS` in ref order, each naming A and B, and allows covering everything a `route`
answer that shows A needs, P 6.4) and `recall_row(..., at=...)` live in the test file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 9 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_uses.py engram/pyproject.toml engram/tests/test_permissions_uses.py
git commit -m "Permission uses: the receipts file, single, bulk and imported rows, the fold (P 9.1)"
```

### Task 15: Views of the receipts

**Files:**
- Modify: `engram/permission_uses.py`
- Test: `engram/tests/test_permissions_views.py`

**Interfaces:**
- Consumes: Task 14; `permissions.State` for place names, stewards and salts.
- Produces:
  - `pseudonym(salt: bytes, subject: str) -> str` (first 16 hex of HMAC-SHA256);
  - `UseList(counts: dict, rows: list[dict])`. `counts` holds `total`, `local` and `imported` (imported rows counted
    apart, R14), and in a place view also `filtered`. Each row holds `notes: list[str]` (a blocked share's reason, a
    self-claim);
  - `Uses.owner_list(state, *, since=None, until=None, place=None, action=None, purpose=None, collection=None,
    obj=None, refused=False) -> UseList`: counts first, then at most `USE_LIST_ROWS` rows, newest first; imported rows
    marked with their station and counted apart (R14); a blocked share's reason ("needs Jenn's yes"); self-claims; no
    filtered recalls;
  - `Uses.place_view(state, place, **filters) -> UseList` (P 9.2's stewards row);
  - `Uses.agent_view(agent: str) -> list[dict]` (P 9.2's agents row); `Uses.subject_view(subject: str) -> list[dict]`;
  - `Uses.deliveries(agent: str, *, now: int) -> list[UseRow]`: allowed `inject_context` rows for that agent with
    `now - GUARD_SECONDS < at <= now` (a delivery counts for 24 hours, half-open like every interval here), at most
    `GUARD_RECEIPTS`, newest first (Task 25).

- [ ] **Step 1: Write the failing tests**

```python
def test_u8_an_agent_sees_its_refusals_only_as_not_allowed(tmp_path):
    uses, state = e1_receipts(tmp_path)               # use 2's refused m3 read, and a refused bulk use
    single = [r for r in uses.agent_view("agent:ph-coordinator") if r["object"] == M3][0]
    assert single["outcome"] == "not allowed" and set(single) == {"object", "at", "outcome"}
    bulk = [r for r in uses.agent_view("agent:station-imprints") if r.get("count") is not None][0]
    assert set(bulk) <= {"count", "sha256", "at", "outcome"} and "code" not in bulk     # BN4
    owner = uses.owner_list(state, obj=M3).rows[0]
    assert owner["refusal"]["layer"] == "place:home/jenn" and "m3: needs Jenn's yes" in owner["notes"]   # BN3

def test_u8_a_steward_sees_a_home_only_as_its_persons_pseudonym(tmp_path):
    uses, state = e1_receipts(tmp_path)
    view = uses.place_view(state, "place:la-county/public-health/clinic-3")
    refused = [r for r in view.rows if not r["allowed"]][0]
    jenn = pseudonym(state.places["place:la-county/public-health/clinic-3"].pseudonym_salt, "person:jenn")
    assert refused["refusal"]["layer"] == jenn and "place:home" not in json.dumps(view.rows)
    assert all(not rec.startswith("r-") or rec in county_record_ids(state) for rec in cited_ids(view.rows))
    assert view.counts["filtered"] >= 1

def test_u8_pseudonyms_are_stable_in_a_place_and_differ_across_places(tmp_path):
    uses, state = e1_receipts(tmp_path)
    clinic = state.places["place:la-county/public-health/clinic-3"].pseudonym_salt
    ph = state.places["place:la-county/public-health"].pseudonym_salt
    jenn_at_clinic, jenn_at_ph = pseudonym(clinic, "person:jenn"), pseudonym(ph, "person:jenn")
    assert re.fullmatch(r"[0-9a-f]{16}", jenn_at_clinic) and jenn_at_clinic == pseudonym(clinic, "person:jenn")
    assert jenn_at_clinic != jenn_at_ph and jenn_at_clinic != pseudonym(clinic, "person:andy")
    first = uses.place_view(state, "place:la-county/public-health/clinic-3").rows
    assert uses.place_view(state, "place:la-county/public-health/clinic-3").rows == first        # stable
    at_ph = json.dumps(uses.place_view(state, "place:la-county/public-health").rows)   # use 2 is at clinic-3, below it
    assert jenn_at_clinic in json.dumps(first) and jenn_at_ph in at_ph and jenn_at_clinic not in at_ph

def test_u8_agents_in_a_place_see_no_filtered_counts(tmp_path):
    uses, state = e1_receipts(tmp_path)    # use 1's recall filtered m3; use 3's recall by parks-planner filtered 3
    assert uses.place_view(state, "place:la-county/public-health/clinic-3").counts["filtered"] == 1   # stewards do
    assert uses.place_view(state, "place:la-county/parks-and-rec").counts["filtered"] == 3
    for agent in ("agent:ph-coordinator", "agent:parks-planner", "agent:station-imprints"):
        view = uses.agent_view(agent)
        assert all(set(r) <= {"object", "at", "outcome", "count", "sha256", "permission"} for r in view), agent
        assert "filtered" not in json.dumps(view), agent
    assert uses.agent_view("agent:parks-planner") == []    # its one receipt is a recall that returned nothing
def test_u8_a_subject_sees_only_receipts_naming_them_at_the_time(tmp_path):
    # m5 read on 2026-11-02; Jenn added as m5's co-subject on 2026-11-03; m5 read again on 2026-11-04; m1 read on
    # 2026-11-04 (Andy's alone). Each read's use_subjects is written at the time of the use.
    uses, state = receipts_around_a_late_co_subject(tmp_path)
    jenn = uses.subject_view("person:jenn")
    assert [(r["object"], r["at"]) for r in jenn] == [(M5, T("2026-11-04"))]     # the earlier use stays hidden
    assert set(jenn[0]) >= {"requester", "place", "action", "purpose", "records", "at", "outcome"}
    assert sorted(r["at"] for r in uses.subject_view("person:andy") if r["object"] == M5) == [
        T("2026-11-02"), T("2026-11-04")]
    assert uses.subject_view("person:amy") == []                                  # never a subject

def test_u8_imported_rows_are_marked_and_counted_apart_and_found_by_object(tmp_path):
    uses, state = local_and_imported_rows(tmp_path)   # the imprints spec's form, station peer id "5d…"
    lst = uses.owner_list(state)
    assert lst.counts["imported"] and all(r["station"] == STATION for r in lst.rows if r["imported"])
    assert uses.owner_list(state, obj="mem:S/episode/e17").rows                     # --object finds a batch row

def test_yn6_imported_admission_rows_are_per_action_and_purpose(tmp_path):
    uses, state = imported_admission_with_route(tmp_path)   # memory rows: (recall, calibration), (read, calibration),
    lst = uses.owner_list(state, action="read")              # (imprint, calibration), (recall, trail-evaluation),
    assert {r["purpose"] for r in lst.rows} == {"calibration", "trail-evaluation"}   # (read, trail-evaluation)
    assert uses.owner_list(state, action="read", purpose="trail-evaluation").counts["imported"] == 1

def test_xs2_a_null_returned_row_is_listed_as_not_counted(tmp_path):
    uses, state = imported_denied_with_route(tmp_path)
    [row] = [r for r in uses.owner_list(state).rows if r["kind"] == "roads-and-trails"]
    assert row["count"] == "not counted"

def test_the_list_shows_counts_then_the_200_newest_rows(tmp_path):
    uses, state = many_rows(tmp_path, 250)
    lst = uses.owner_list(state)
    assert lst.counts["total"] == 250 and len(lst.rows) == 200 and lst.rows[0]["at"] >= lst.rows[-1]["at"]

def test_u5_a_self_claim_appears_in_the_owners_list(tmp_path):
    uses, state = receipts_with_self_claim(tmp_path)   # Jenn claimed m3 on 2026-11-03 (a ledger fixture)
    assert "Jenn claimed m3 on 2026-11-03" in [n for r in uses.owner_list(state).rows for n in r["notes"]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_views.py`
Expected: FAIL, `AttributeError: 'Uses' object has no attribute 'owner_list'`.

- [ ] **Step 3: Implement the views**

P 9.2's table row by row. A place view of P covers uses at P and at every place P dominates, and uses of copies they
hold, and gives every pseudonym with P's salt (R33). A steward's view replaces every home layer, cited or refusing, with the
pseudonym that place gives the home's person, and drops home record ids. `e1_receipts(tmp_path)` writes, through
`Uses.append`, the receipts of E1's uses 1 to 3 (use 1's recall that returned m1 and m2 and filtered m3, and its
delivery of m1; use 2's refused read of m3; use 3's recall by `parks-planner` that returned nothing and filtered 3),
plus one refused bulk use by `agent:station-imprints`, and returns them with the E1 state. The agent view of a
refusal is exactly `{object, at, outcome: "not allowed"}`, or for a bulk refusal `{count, sha256?, at, outcome}`. `--collection C` matches rows whose
`use_subjects` objects are C's members at any time.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 10 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_uses.py engram/tests/test_permissions_views.py
git commit -m "Permission uses: owner, place, agent and subject views; pseudonyms (P 9.2, 9.3)"
```

### Task 16: Migration 029 and new houses

**Files:**
- Create: `engram/migrations/029_share_identity.sql`
- Modify: `engram/storage.py:225-235` (the migration loop), new method `Storage._mark_house_for_ledger(created_now)`
- Test: `engram/tests/test_permissions_migration_029.py`

**Interfaces:**
- Consumes: Task 13's `house_mark`.
- Produces: `shared_memories.source_instance_id TEXT`, `shared_memories.record_id TEXT`, and table
  `shared_memories_changes(id INTEGER PRIMARY KEY CHECK (id = 1), count INTEGER NOT NULL)` with one row, raised by
  triggers `shared_memories_changes_insert`, `_update` and `_delete`. `Storage.placement_changes() -> int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_029_adds_columns_and_a_counter_that_counts_insert_update_and_delete(tmp_path):
    store = Storage(str(house_dir(tmp_path, "lighthouse") / "graph.db"), migrations_dir=MIGRATIONS_DIR)
    cols = {r[1] for r in store.conn.execute("PRAGMA table_info(shared_memories)")}
    assert {"source_instance_id", "record_id"} <= cols and store.placement_changes() == 0
    insert_share(store, memory_id="a", content="x"); update_one_share(store); delete_one_share(store)
    insert_share(store, memory_id="b", content="y")
    assert store.placement_changes() == 4          # a count and highest rowid would miss the delete-then-insert

def test_u16_a_house_created_after_the_raise_gets_the_ledger_id(tmp_path):
    led = raised_ledger(tmp_path, houses=("lighthouse",))
    late = Storage(str(house_dir(tmp_path, "late") / "graph.db"), migrations_dir=MIGRATIONS_DIR)
    assert late.conn.execute("SELECT value FROM meta WHERE key='permissions_ledger_id'").fetchone()[0] \
        == led.meta()["ledger_id"]

def test_u16_a_house_created_while_the_ledger_cant_be_read_gets_unreadable_and_reads_closed(tmp_path):
    raised_ledger(tmp_path, houses=("lighthouse",)); make_ledger_unreadable(tmp_path)
    late_path = house_dir(tmp_path, "late") / "graph.db"
    Storage(str(late_path), migrations_dir=MIGRATIONS_DIR).close()
    assert house_meta(late_path)["permissions_ledger_id"] == "unreadable"
    assert effective_gate(tmp_path, [late_path]).mode == "closed"

def test_029_with_no_ledger_writes_no_mark(tmp_path):
    path = house_dir(tmp_path, "lighthouse") / "graph.db"
    Storage(str(path), migrations_dir=MIGRATIONS_DIR).close()
    assert "permissions_ledger_id" not in house_meta(path) and not ledger_path(tmp_path).exists()

def test_029_on_a_house_made_by_001_to_028_adds_its_columns_and_counter(tmp_path):
    path = house_before_029(tmp_path, "old")            # built with a copy of migrations 001 to 028 only
    assert not {"source_instance_id", "record_id"} & share_columns(path)
    Storage(str(path), migrations_dir=MIGRATIONS_DIR).close()
    assert {"source_instance_id", "record_id"} <= share_columns(path) and counter_row(path) == 0

def test_rs4_a_pre_029_house_restored_after_the_raise_stays_closed_when_a_server_opens_it(tmp_path):
    led = raised_ledger(tmp_path, houses=("lighthouse",))
    restored = house_before_029(tmp_path, "restored")  # as restored from a backup made before 029 and the raise
    Storage(str(restored), migrations_dir=MIGRATIONS_DIR).close()   # 029 runs now, on a house it did not create
    assert {"source_instance_id", "record_id"} <= share_columns(restored)
    assert "permissions_ledger_id" not in house_meta(restored)       # no mark without the yes (P 12.3 rule 2)
    assert effective_gate(tmp_path, [restored]).mode == "closed"
    raise_gate(led, "shadow")                                         # gate again, with the yes, marks it
    assert effective_gate(tmp_path, [restored]).mode == "shadow"
```

`house_dir(root, name)` makes and returns `root/.engram/instances/<name>/`: `Storage` makes no directory
(`engram/storage.py:93`), so without it the first failure would be "unable to open database file". `house_before_029`
copies `migrations/001_*.sql` to `028_*.sql` into `tmp_path/m028/` and opens a `Storage` with that `migrations_dir`; it
is the builder Tasks 20, 21 and 28 use for houses older than 029 (SF4).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_migration_029.py`
Expected: FAIL, the column assertion (`source_instance_id` missing).

- [ ] **Step 3: Write the migration and the storage step**

`029_share_identity.sql` holds the two `ALTER TABLE ... ADD COLUMN` lines, the counter table, `INSERT OR IGNORE` of its
one row, and the three `CREATE TRIGGER IF NOT EXISTS ... BEGIN UPDATE shared_memories_changes SET count = count + 1
WHERE id = 1; END;`. In `_run_migrations`, beside `if ver == 28: self._assign_instance_id(created_now)`, add
`if ver == 29: self._mark_house_for_ledger(created_now)`, with the same `created_now` (`engram/storage.py:224`,
`:230`). It returns at once unless `created_now`: P 12.3 marks a house "when it is created", and a house 029 upgrades
was not, so one restored from before the raise stays closed until `gate` marks it with the yes (P 12.3 rule 2). Every
house that exists when the raise runs is marked by the raise itself (R17), 029 or no 029, so G3's order still works.
For a new house it imports `permission_ledger` inside the method, calls `house_mark(Path(self.db_path))`, and writes
the result into `meta` inside 029's transaction.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_migration_029.py tests/test_storage.py tests/test_store_identity.py tests/test_sharing.py`
Expected: PASS, and the existing storage, identity and sharing tests pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add engram/migrations/029_share_identity.sql engram/storage.py engram/tests/test_permissions_migration_029.py \
        engram/tests/permissions_support.py
git commit -m "Migration 029: share identity columns, the placement change counter, and marking new houses (P 12.2, 12.3)"
```

### Task 17: Lane notes

**Files:**
- Modify: `engram/storage.py:162-187` (`transaction`, `_commit`) and `:598-610` (`set_episode_lanes`),
  `engram/compress.py:508-510` and `:563`, `engram/server.py` (`_init_unlocked`, beside the storage open at
  `:1313-1315`), `engram/permission_ledger.py`
- Test: `engram/tests/test_permissions_lanes.py`

**Interfaces:**
- Consumes: Tasks 10 and 13.
- Produces:
  - `class LaneNoteError(RuntimeError)` in `storage.py`; `Storage.lane_listener: Callable[[str, list[dict], str],
    None] | None = None`, called with phase `"before"`, `"after"` or `"failed"`, the rows `{"id", "lane",
    "created_at"}` read just before the `UPDATE`, and the target lane;
  - `Storage.after_outcome(on_commit: Callable[[], None], on_rollback: Callable[[], None]) -> None`. Outside any
    `transaction()` (depth 0), it is called right after a write that `_commit` has just committed, so it runs
    `on_commit` at once. Inside `transaction()`, where `_commit` does nothing (`engram/storage.py:182-187`), it queues
    both on the outermost transaction: `on_commit` runs after that transaction's `self.conn.commit()` returns, and
    `on_rollback` on every exceptional exit from the outermost block, a failed commit included, whether or not
    `rollback()` ran: `transaction()` rolls back only `if outermost and self.conn.in_transaction`
    (`engram/storage.py:176-177`), and SQLite rolls back on its own after some errors. The queues are cleared when the
    outermost block ends, either way. An `Exception` from a callback is logged and not raised, since
    the store's outcome is already final; the note it failed to write leaves `pending`, which the sweep settles (Task
    24). A `BaseException` such as `SystemExit` propagates, as a crash would. This is what makes the settling note
    follow the store's commit, not `_commit`'s call (P 5.3, L5): compression's one re-lane
    (`engram/compress.py:510`) runs inside `with self._storage.transaction():` (`:466`);
  - `Ledger.note_lanes(phase: str, rows: list[dict], target: str, *, store_id: str, now: int) -> None`: before, a
    first note at each memory's `created_at` (its current lane) for refs with none, then `pending` at now; after, the
    target lane; failed, each row's old lane;
  - `Ledger.latest_lane_note(ref: str) -> str | None` (for the imprints plan);
  - `server._lane_notes(phase, rows, target)`, installed as `_storage.lane_listener` at init; it computes the gate each
    call: `off` returns at once, `shadow` and `enforce` write, `closed` raises `LaneNoteError`.

- [ ] **Step 1: Write the failing tests**

```python
def test_u6_a_failing_first_note_refuses_the_re_lane(tmp_db):
    ep = add_personal_episode(tmp_db)
    tmp_db.lane_listener = refusing_listener()
    with pytest.raises(LaneNoteError):
        tmp_db.set_episode_lanes([ep], "work")
    assert tmp_db.get_episode(ep)["lane"] == "personal"

def test_u25_a_failed_update_settles_to_the_old_lane(tmp_path):
    led, store, ep = raised_ledger_and_store(tmp_path, mode="shadow")
    store.lane_listener = ledger_listener(led, store)
    fail_the_next_update(store)
    with pytest.raises(sqlite3.OperationalError):
        store.set_episode_lanes([ep], "work")
    assert [n.lane for n in led.state().lane_notes[ref(store, ep)]] == ["personal", "pending", "personal"]

def test_u25_a_crash_between_the_calls_leaves_a_pending_note(tmp_path):
    led, store, ep = raised_ledger_and_store(tmp_path, mode="shadow")
    store.lane_listener = ledger_listener(led, store, crash_at="after")   # the UPDATE committed, no settling note
    with pytest.raises(SystemExit):
        store.set_episode_lanes([ep], "work")
    s = led.state()
    assert latest(s, ref(store, ep)) == "pending"
    assert not record_matches(s, work_lane_allow(s), home_use(ref(store, ep), now()), "recall")
    assert record_matches(s, personal_lane_deny(s), home_use(ref(store, ep), now()), "recall")

def test_mf2_inside_a_transaction_the_settling_note_waits_for_the_outer_commit(tmp_path):
    led, store, ep = raised_ledger_and_store(tmp_path, mode="shadow")
    store.lane_listener = ledger_listener(led, store)
    with store.transaction():
        store.set_episode_lanes([ep], "work")
        assert latest(led.state(), ref(store, ep)) == "pending"        # the store's UPDATE is not committed yet
    assert latest(led.state(), ref(store, ep)) == "work" and store.get_episode(ep)["lane"] == "work"

def test_mf2_a_re_lane_inside_a_transaction_that_raises_settles_to_the_old_lane(tmp_path):
    led, store, ep = raised_ledger_and_store(tmp_path, mode="shadow")
    store.lane_listener = ledger_listener(led, store)
    with pytest.raises(RuntimeError, match="later step"):
        with store.transaction():
            store.set_episode_lanes([ep], "work")
            raise RuntimeError("a later step of the commit failed")
    assert store.get_episode(ep)["lane"] == "personal"
    assert [n.lane for n in led.state().lane_notes[ref(store, ep)]] == ["personal", "pending", "personal"]
    work_allow = allow_anchored_now(led, lanes=["work"])                # anchored after the failed move
    assert not record_matches(led.state(), work_allow, home_use(ref(store, ep), now()), "recall")

def test_mf2_a_compression_commit_that_rolls_back_leaves_no_work_note(shadow_server, monkeypatch):
    eps = remember_personal_cluster()                                   # three personal episodes, one cluster
    cid, summaries = prepare_compression_relaning_to("work")            # the review sets the cluster's lane to work
    monkeypatch.setattr(server._storage, "add_semantic", raising(RuntimeError("disk full")))
    with pytest.raises(RuntimeError, match="disk full"):
        server._compressor.commit(cid, summaries)                       # inside storage.transaction() (:466)
    assert {store_lane(ep) for ep in eps} == {latest_note(ep) for ep in eps} == {"personal"}

def test_compression_keeps_the_lane_when_the_note_cannot_be_written(closed_server, caplog):   # R20
    eps = remember_personal_cluster()                                   # the gate reads closed: no note can be written
    cid, summaries = prepare_compression_relaning_to("work")
    result = server._compressor.commit(cid, summaries)
    assert result["semantics_created"] == 1 and "lane" in caplog.text
    assert {store_lane(ep) for ep in eps} == {"personal"}
    assert new_semantic_lane(result) == "personal"                      # the summary keeps its evidence's lane

def test_off_writes_no_note_and_closed_refuses_the_re_lane(engram_server_env, tmp_path):
    ep = server.remember(content="a personal note long enough")["episode_id"]
    assert server._storage.set_episode_lanes([ep], "work") == 1 and not ledger_path(tmp_path).exists()   # off
    close_the_gate(tmp_path)                                            # a raised ledger, then made unreadable
    with pytest.raises(LaneNoteError):
        server._storage.set_episode_lanes([ep], "personal")
    assert server._storage.get_episode(ep)["lane"] == "work"
```

`shadow_server` is `engram_server_env` with a published house and a ledger raised to `shadow` through `perform` as
`person:andy`; `closed_server` is the same, with the ledger then made unreadable so the gate reads `closed`. The
helpers `remember_personal_cluster`, `prepare_compression_relaning_to`, `store_lane`, `latest_note`,
`new_semantic_lane`, `allow_anchored_now` and `close_the_gate` live in the test file. `server._compressor` is the
server's compressor, which `engram_server_env` resets.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_lanes.py`
Expected: FAIL, `ImportError: cannot import name 'LaneNoteError' from 'storage'`.

- [ ] **Step 3: Implement the listener, `note_lanes`, the server hook and compress's catch**

`set_episode_lanes` keeps its `ValueError` checks, reads the rows, calls the listener with `"before"` (an `Exception`
from it becomes `LaneNoteError` and nothing is updated; a `BaseException` such as `SystemExit` propagates), runs the
`UPDATE` and `_commit`, then calls `self.after_outcome(lambda: listener("after", rows, lane), lambda:
listener("failed", rows, lane))`. On an exception from the `UPDATE`, or from `_commit` at depth 0, it calls
`"failed"` and re-raises. At depth 0 it first rolls back when `self.conn.in_transaction`: a `COMMIT` that fails with
`SQLITE_BUSY` leaves the transaction open, and a later `_commit` on that connection would otherwise commit the new
lane after a settled note naming the old one. So the `"after"` note is written only once the outermost transaction
has committed, and a rollback writes `"failed"` with the old lanes. `transaction()` runs the queued calls after its own `commit()` or
`rollback()`. With no listener it behaves exactly as today, and with no queued call `transaction()` does too. In
`compress.py`, the catch of R20 also sets `lane` back to the cluster's lane before `add_semantic` (`:563`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_lanes.py tests/test_storage.py tests/test_compression.py tests/test_remember_lane.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/storage.py engram/compress.py engram/server.py engram/permission_ledger.py \
        engram/tests/test_permissions_lanes.py
git commit -m "Lane notes: a pending note before each re-lane and a settling note after (P 5.3)"
```

### Task 18: Config, the policy generator and the `share` argument

**Files:**
- Modify: `engram/config.py:301-357` (`load_config`), `engram/policy_gen.py:16-44` (`load_groups`),
  `engram/server.py:1951-1980` (`share`)
- Test: `engram/tests/test_permissions_edges.py`

**Interfaces:**
- Produces: `load_config` logs one warning on logger `engram.config` when `config.toml` has a `[permissions]`
  section, naming `engram-permissions gate`, and loads nothing from it; `load_groups` raises
  `ValueError("group name outside-home is reserved")`; the `share` tool returns `{"error": ...}` for
  `audience == "group:outside-home"` in every mode, before anything else.

- [ ] **Step 1: Write the failing tests**

```python
def test_u16_a_permissions_section_logs_one_warning_and_changes_no_mode(tmp_path, caplog):
    write_config(tmp_path, "[permissions]\ngate = \"off\"\n")
    raised_ledger(tmp_path, houses=("lighthouse",), mode="enforce")
    load_config(tmp_path)
    warnings = [r for r in caplog.records if "permissions" in r.getMessage()]
    assert len(warnings) == 1 and "engram-permissions gate" in warnings[0].getMessage()
    assert effective_gate(tmp_path, houses(tmp_path)).mode == "enforce"

def test_u23_policy_gen_refuses_a_group_named_outside_home(tmp_path):
    (tmp_path / "groups.toml").write_text('[groups.outside-home]\nmembers = ["why"]\n')
    with pytest.raises(ValueError, match="outside-home"):
        load_groups(tmp_path / "groups.toml")

def test_u23_share_refuses_group_outside_home_as_an_argument(engram_server_env, tmp_path):
    _published_house(tmp_path); seed()
    ep = server.remember(content="a thing worth sharing")
    out = server.share(memory_id=ep["episode_id"], audience="group:outside-home", reason="r")
    assert "error" in out and "reserved" in out["error"]
```

U16's "a config that fails to parse changes no mode" is in Task 23: it runs through the server, a reader that loads
config, once `server._permission_gate()` exists. `effective_gate` alone never reads config, so a test of it here could
not fail.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_edges.py`
Expected: FAIL on all three.

- [ ] **Step 3: Implement the three edges**

`share`'s check runs before `_published_house_storage`. `sharing.validate_audience` is unchanged, since the server's
own mapping writes the name (P 12.1).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_edges.py tests/test_config.py tests/test_policy_gen.py tests/test_share_tools.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/config.py engram/policy_gen.py engram/server.py engram/tests/test_permissions_edges.py
git commit -m "Permissions edges: the [permissions] warning, a reserved group name, and share's argument (P 12.1, 12.3)"
```

### Task 19: The daemon's gate and the outside-home rule

**Files:**
- Modify: `engram/lighthouse_daemon.py:156-170` (`_allowed_audiences`), `:294-359` (`PublisherDaemon.__init__`,
  `handle_frame`), `:521-551` (`main`)
- Test: `engram/tests/test_permissions_daemon_gate.py`

**Interfaces:**
- Consumes: Task 13's `effective_gate`.
- Produces: `PublisherDaemon(publishers, socket_path, embeddings, *, clock=None, engram_home: Path | None = None)`
  (R19); `_allowed_audiences(policy, receiver, *, mode: str = "off") -> frozenset[str]` strips
  `group:outside-home` under every mode, and with no ledger, and adds it back only when `mode == "enforce"` and the publisher policy has a rule
  whose `publishers` names the receiver; `handle_frame`, right after today's publisher check
  (`engram/lighthouse_daemon.py:331-337`, which still answers `PUBLISHER_UNAVAILABLE` for an unknown publisher or a
  missing store), computes the effective gate over every house the daemon serves, `[p.db_path for p in
  self.publishers.values()]` in name order, as P 12.3 says ("the daemon over the houses it serves"), with
  `busy_ms=LEDGER_BUSY_MS`. A served path with no file is left out (R32): a configured publisher whose `graph.db`
  doesn't exist yet serves nothing and closes nothing, and the frame's own house, checked just before, is always in
  the gate. So one served house that reads closed, such as one added to the config after the raise, closes every
  frame, whichever publisher it names. Under `closed` it answers a recall with no candidates and a read with every
  item's `content` null, logging the cause once per request. The gate is read again at every frame, never cached.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("mode", ["no-ledger", "off", "shadow"])
def test_u23_an_outside_home_placement_is_never_served_below_enforce(tmp_path, mode):
    daemon, pub = daemon_with_outside_home_placement(tmp_path, mode=mode,
                                                     hand_written_audiences=["commons", "group:outside-home"])
    assert daemon.handle_frame(recall(pub))["candidates"] == []
    assert all(i["content"] is None for i in daemon.handle_frame(read(pub, OUTSIDE_ID))["items"])

def test_u16_closed_serves_nothing_and_warns(tmp_path, caplog):
    daemon, pub = raised_daemon(tmp_path, mode="enforce"); delete_ledger(tmp_path)
    assert daemon.handle_frame(recall(pub))["candidates"] == []
    assert "closed" in caplog.text and "ledger" in caplog.text

def test_u16_a_served_house_added_without_the_id_closes_every_frame_until_gate_marks_it(tmp_path, caplog):
    daemon, pub = raised_daemon(tmp_path, mode="shadow"); late = add_publisher_house(daemon, tmp_path, "late")
    assert daemon.handle_frame(recall(late))["candidates"] == []
    assert daemon.handle_frame(recall(pub))["candidates"] == []      # the gate is over every served house
    assert "late" in caplog.text
    rerun_gate(tmp_path, "shadow")                       # perform(Act("gate", ...)) marks it
    assert daemon.handle_frame(recall(late))["candidates"] and daemon.handle_frame(recall(pub))["candidates"]

def test_rf2_locked_ledger_reads_closed(tmp_path):
    daemon, pub = raised_daemon(tmp_path, mode="enforce", busy_timeout_ms=50)
    with hold_ledger_lock(tmp_path, "IMMEDIATE"):        # RESERVED: readers still read the last commit
        assert daemon.handle_frame(recall(pub))["candidates"]
    with hold_ledger_lock(tmp_path, "EXCLUSIVE"):        # what a commit or a cache spill holds
        assert daemon.handle_frame(recall(pub))["candidates"] == []
    assert daemon.handle_frame(recall(pub))["candidates"]               # once the lock is gone, it serves again

def test_rs5_a_configured_publisher_with_no_store_yet_closes_nothing(tmp_path):
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    pending = add_publisher_without_store(daemon, tmp_path, "pending")   # configured; its graph.db does not exist
    assert daemon.handle_frame(recall(pub))["candidates"]                # the gate leaves the missing path out
    assert daemon.handle_frame(recall(pending))["code"] == "PUBLISHER_UNAVAILABLE"     # as today
    make_house(tmp_path, "pending")                       # made now: 029 gives it the ledger's id (Task 16)
    assert daemon.handle_frame(recall(pub))["candidates"]
```

`add_publisher_house` restores a copy of a house that ran 029 before the raise, so it carries no id, and adds it to
the daemon's publishers. `hold_ledger_lock(root, kind)` opens its own `sqlite3` connection to the ledger, runs
`BEGIN <kind>`, yields, then rolls back. With R1's rollback journal, only `EXCLUSIVE` blocks a `mode=ro` reader
(checked on this Pi by the reviewer, with `busy_timeout` 50 ms). `raised_daemon(..., busy_timeout_ms=50)` sets
`LEDGER_BUSY_MS`, which reaches `effective_gate` as `busy_ms`, so a locked frame waits 50 ms, not 5 s.
`add_publisher_without_store` adds a publisher named in the daemon's config whose `instances/<name>/` holds no
`graph.db`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_daemon_gate.py`
Expected: FAIL, the no-ledger and off cases return the outside-home candidate.

- [ ] **Step 3: Implement the gate check and the audience rule in the daemon**

The busy timeout used by the daemon's read-only ledger open is a module constant `LEDGER_BUSY_MS = 5000` that the test
lowers. A read under `closed` still writes the disclosures sidecar as today.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_daemon_gate.py tests/test_lighthouse_daemon.py tests/test_daemon_audiences.py tests/test_neighbors.py tests/test_sharing.py tests/test_context_lighthouse.py`
Expected: PASS. With no ledger, the existing daemon, neighbor and sharing tests pass unchanged (U16, first bullet).

- [ ] **Step 5: Commit**

```bash
git add engram/lighthouse_daemon.py engram/tests/test_permissions_daemon_gate.py
git commit -m "Daemon: the effective gate, closed serves nothing, and group:outside-home only under enforce (P 12.1, 12.3)"
```

### Task 20: The daemon's decisions, receipts and annotation

**Files:**
- Modify: `engram/lighthouse_daemon.py:204-291` (`_rank_shared_layer`, `retrieve`), `:361-453` (`_recall`, `_read`)
- Modify: `engram/permissions.py` (the annotation)
- Test: `engram/tests/test_permissions_daemon.py`

**Interfaces:**
- Consumes: Tasks 5 to 7, 10, 14, 19.
- Produces:
  - `permissions.annotation(state, decision: Decision, *, laid_by: str, receipt_id: str) -> dict` (P 11's object:
    `laid_by`, `allowed_by` in step 2's order with each layer's distinct cited records, `until` as an RFC 3339 date
    or null, `receipt`); `permissions.annotation_line(obj: dict) -> str` (at most `ANNOTATION_CHARS`, names cut at
    `ANNOTATION_NAME_CHARS` to 31 and `…`, `allowed_by` entries dropped from the end with `+N`, short names as P 11);
  - in the daemon, under `shadow` and `enforce`: the requester is `agent:<receiver>` in its one place; each placement's
    object is `mem:<source_instance_id>/<layer>/<source_id>` and its copy `store:<house instance_id>`; `recall` is
    decided per placement before ranking, and refused copies are filtered before ranking; a read frame is decided per
    item as `inject_context` (P18); the legacy layers are the publisher's and the receiver's (R30). The publisher's
    layer is `LegacyLayer("publisher", lambda use, x: frame_decision.effect == "allow")`: it answers every action of
    `need` with this frame's one publisher decision, the policy decided once for `recall` (`:362`) or `read` (`:402`),
    as today. It never asks the publisher's policy about `inject_context`, which neither `policy_gen.py:75` nor E1's
    publisher policy lists. The receiver's layer decides each action of `need` with its own `PolicyRequest`, below;
    one recall receipt and one receipt per read item go to `permission-uses.db`; an allowed item gains `permission`
    (R9); under `enforce` an item is served only when both paths allow it; under `shadow` the legacy path decides and
    every receipt has `shadow = 1`; a house with more than `MAX_PLACEMENTS` placements serves nothing under `enforce`
    and warns;
  - the receiver's legacy layer (P 6.3 item 4, SF14). Today the daemon loads only the publisher's policy
    (`engram/lighthouse_daemon.py:342`). Under `shadow` and `enforce` it also reads the receiver's, at every frame and
    never cached, the way the receiver itself finds it: `load_settings(engram_home / ".engram" / "instances" /
    <receiver> / "lighthouse-receiver.toml")` (`engram/neighbors.py:183-184`), then
    `load_receiver_policy(settings["policy_path"], receiver)`, with `engram_home` from R19. For each action x of
    `need` it decides the same `PolicyRequest` the receiver makes (`engram/neighbors.py:53-60`: the publisher's urn,
    profile, `memory.recall`, action x, the frame's context and purpose, audience `self`, `at` = t), as the receiver
    asks for `recall`, `read` and `inject_context` (`:120`, `:138`). A receiver with no settings file, a disabled
    one, or one that fails to load has a legacy layer that refuses (`LEGACY_DENY`); under `shadow` that is only
    recorded. So E1's `cited` holds both legacy layers, as `LegacyLayer("publisher", ...)` and
    `LegacyLayer("receiver", ...)`;
  - a house without 029 (R27): under `shadow` and `enforce`, a publisher whose house lacks `source_instance_id`,
    `record_id` or `shared_memories_changes` answers every frame with no candidates and null content, and warns,
    naming the house.

- [ ] **Step 1: Write the failing tests**

```python
def test_u9_enforce_needs_both_decisions(tmp_path):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=False)
    assert d.read(M1_ITEM)["content"] is None
    d = enforce_daemon(tmp_path / "b", legacy_allows=False, ledger_allows=True)
    assert d.read(M1_ITEM)["content"] is None

def test_u9_shadow_delivers_by_the_legacy_path_and_records_both(tmp_path):
    d = shadow_daemon(tmp_path, legacy_allows=True, ledger_allows=False)
    assert d.read(M1_ITEM)["content"] and "permission" not in d.read(M1_ITEM)
    [row] = receipt_rows(tmp_path, action="inject_context")
    assert row["shadow"] == 1 and row["allowed"] == 0 and any(c["kind"] == "legacy" for c in json.loads(row["cited"]))

def test_u9_the_ledger_bytes_are_unchanged_and_total_changes_is_0(tmp_path):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=True)
    before = ledger_path(tmp_path).read_bytes(); d.recall(); d.read(M1_ITEM)
    assert ledger_path(tmp_path).read_bytes() == before and d.ledger_total_changes() == 0

def test_u9_a_frame_at_in_the_future_extends_nothing(tmp_path):
    d = enforce_daemon(tmp_path, clock=at(T("2027-01-31")))      # R1 ends here
    assert d.read(M1_ITEM, frame_at="2026-12-01T00:00:00Z")["content"] is None

def test_u9_refused_copies_never_appear_among_candidates(tmp_path, monkeypatch):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows_only={M1})   # m2 and m3 placed, both refused
    ranked = spy_on_retrieve(monkeypatch, d)          # records the `eligible` set each retrieve call is given
    reply = d.recall(query=M3_TEXT, k=5)              # the query that would rank m3 first
    assert {c["memoryId"] for c in reply["candidates"]} == {M1_ID}
    assert ranked[-1] == frozenset({M1_ID})           # refused before ranking, not dropped after it
    [row] = receipt_rows(tmp_path, action="recall")
    assert json.loads(row["returned"]) == [M1] and row["filtered"] == 2

def test_e1_cited_holds_the_publishers_and_the_receivers_legacy_layers(tmp_path):
    d, ids = e1_daemon_at(tmp_path, T("2026-11-02"))  # both ConnectionPolicy files written by hand (P 13)
    d.read(M1_ITEM)
    [row] = receipt_rows(tmp_path, action="inject_context")
    assert {c["layer"] for c in json.loads(row["cited"]) if c["kind"] == "legacy"} == {"publisher", "receiver"}
    remove_receiver_settings(tmp_path, "ph-coordinator")
    assert d.read(M1_ITEM)["content"] is None         # with no receiver policy its legacy layer refuses

def test_rs1_the_publishers_layer_answers_each_action_with_the_frames_one_decision(tmp_path):
    d, ids = e1_daemon_at(tmp_path, T("2026-11-02"))  # under enforce; the publisher's policy allows recall and read
    item = d.read(M1_ITEM)
    assert item["content"] and item["permission"]     # E1's use 1 is delivered: inject_context was never asked of it
    [row] = receipt_rows(tmp_path, action="inject_context")
    publisher = [c for c in json.loads(row["cited"]) if c["kind"] == "legacy" and c["layer"] == "publisher"]
    assert {(c["action"], c["verdict"]) for c in publisher} == {(x, "allow") for x in ("recall", "read",
                                                                                       "inject_context")}
    write_receiver_policy(tmp_path, "ph-coordinator", actions=["recall", "read"])   # the receiver drops inject_context
    assert d.read(M1_ITEM)["content"] is None         # the receiver's layer answers per action
    row = receipt_rows(tmp_path, action="inject_context")[-1]
    assert json.loads(row["refusal"]) == {"code": "LEGACY_DENY", "layer": "receiver", "action": "inject_context"}

def test_r27_a_house_without_029_serves_nothing_under_shadow_and_enforce_and_warns(tmp_path, caplog):
    for mode in ("shadow", "enforce"):
        d, pub = raised_daemon(tmp_path / mode, mode=mode, house=house_before_029)   # migrations 001 to 028 only
        assert d.handle_frame(recall(pub))["candidates"] == []
        assert all(i["content"] is None for i in d.handle_frame(read(pub, SHARED_ID))["items"])
        assert "029" in caplog.text and pub in caplog.text
    d, pub = daemon_with_no_ledger(tmp_path / "off", house=house_before_029)
    assert d.handle_frame(recall(pub))["candidates"]   # off: as today

def test_u9_a_refused_read_item_has_null_content_empty_audiences_and_no_permission(tmp_path):
    item = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=False).read(M3_ITEM)
    assert item["content"] is None and item["audiences"] == [] and "permission" not in item
    assert set(item["decision"]) == {"effect", "ruleId", "code"}

def test_e1_use_1_annotation_line(tmp_path):
    d, ids = e1_daemon_at(tmp_path, T("2026-11-02"))
    line = annotation_line(d.read(M1_ITEM)["permission"])
    assert line == (f"laid by andy (engram) · allowed by home/andy {short_id(ids.R1)}, la-county {short_id(ids.C1)}, "
                    f"public-health {short_id(ids.H1)}, clinic-3 {short_id(ids.L1)} · until 2027-01-31 · "
                    f"receipt {receipt_short(ids.last_receipt())}")

def test_the_annotation_line_truncates_long_names_and_drops_from_the_end(): ...   # 240 characters, +N

def test_rf1_no_receipt_no_content(tmp_path, caplog):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=True); make_uses_file_unwritable(tmp_path)
    assert d.read(M1_ITEM)["content"] is None and "receipt" in caplog.text
    assert d.recall()["candidates"] == []                         # a recall with no receipt returns nothing
    s = shadow_daemon(tmp_path / "s", legacy_allows=True, ledger_allows=True); make_uses_file_unwritable(tmp_path / "s")
    assert s.read(M1_ITEM)["content"] and s.recall()["candidates"]    # shadow: the legacy path, with a warning

def test_more_than_20000_placements_serve_nothing_under_enforce(tmp_path, caplog):   # P 12.2, "Bounds"
    d, pub = raised_daemon(tmp_path / "over", mode="enforce", placements=MAX_PLACEMENTS + 1)
    assert d.handle_frame(recall(pub))["candidates"] == []
    assert all(i["content"] is None for i in d.handle_frame(read(pub, SHARED_ID))["items"])
    assert "20,000" in caplog.text and pub in caplog.text
    d, pub = raised_daemon(tmp_path / "at", mode="enforce", placements=MAX_PLACEMENTS)
    assert d.handle_frame(recall(pub))["candidates"]                     # at the bound it still serves
    d, pub = raised_daemon(tmp_path / "shadow", mode="shadow", placements=MAX_PLACEMENTS + 1)
    assert d.handle_frame(recall(pub))["candidates"]                     # shadow: the legacy path decides
```

`raised_daemon(..., placements=n)` makes the three placements m1 to m3 linked to one inside-home allow that covers
every memory of the registered source store, then writes n − 3 more `shared_memories` rows by plain SQL in one
transaction, as older code could leave them: each names its own `source_id` in that store and a `memory_id` with no
copy, so `retrieve` never ranks it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_daemon.py`
Expected: FAIL, `ImportError: cannot import name 'annotation'`, then the enforce assertions.

- [ ] **Step 3: Implement the decisions, receipts and annotation**

`retrieve` gains an `eligible: frozenset[str] | None` argument: when given, only those memory ids are ranked.
`_recall` computes it (Task 21 caches it); `_read` decides each item. `laid_by` is `<owner handle> (<store name>)` from
the source store's `stores` row. Receipt subjects are `subjects_of` the object at t. Under `shadow`, a receipt failure
logs and delivery follows the legacy path; under `enforce`, no receipt means `content: null` for that item, and a
recall whose receipt can't be written returns no candidates (Review Focus 1). The recall receipt is written before
the reply is sent, so a reply never names a candidate whose receipt failed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_daemon.py tests/test_permissions_daemon_gate.py tests/test_lighthouse_daemon.py tests/test_daemon_audiences.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/lighthouse_daemon.py engram/permissions.py engram/tests/test_permissions_daemon.py
git commit -m "Daemon: decisions before retrieval and read, receipts, and the permission annotation (P 11, 12.2)"
```

### Task 21: The eligible-set cache

**Files:**
- Modify: `engram/lighthouse_daemon.py`, `engram/permissions.py`
- Test: `engram/tests/test_permissions_daemon_cache.py`

**Interfaces:**
- Consumes: Task 20.
- Produces:
  - `permissions.Placement(memory_id: str, obj: str | None, copy: str)` and
    `permissions.eligible_set(state, placements: Sequence[Placement], *, requester, place, purpose, action, at)
    -> EligibleSet`, with `EligibleSet(memory_ids: frozenset[str], decisions: Mapping[str, Decision], at: int,
    horizon: int | None)`. It takes no legacy layer: the set holds ledger decisions only (subjects, places, the
    holding place and the restriction layer);
  - `permissions.meet_legacy(decision: Decision, use: Use, legacy: Sequence[LegacyLayer]) -> Decision`: the
    cached ledger decision met with this request's legacy verdicts, each in its place in step 2's order, so `allowed`,
    `refusal` and `cited` are what `decide(state, use, legacy=legacy)` gives; `until` and `horizon` are unchanged
    (R7). The frame's legacy decision, the receiver's legacy layer (Task 20) and the legacy audience check
    (`_allowed_audiences`) run on every request, never cached (P 6.3 item 4);
  - the daemon keeps at most `CACHE_ENTRIES` entries, over all houses together, keyed by (house, agent, place,
    purpose, action) (R31), each valid while the ledger's `seq` and that house's `placement_changes()` are unchanged
    and `entry.at <= t < entry.horizon` (Review Focus 3 adds the lower bound). The house is the publisher's
    `db_path`, so an entry built from one house's placements is never checked against another's counter or served
    for it. The rebuild runs at the first recall after a change. A house without 029's
    counter never gets an entry (R27).

- [ ] **Step 1: Write the failing tests**

```python
def test_u9_the_cache_recomputes_on_a_new_seq_a_new_change_count_and_at_the_horizon(tmp_path):
    d, led, house = cached_daemon(tmp_path)
    d.recall(); assert d.rebuilds == 1
    d.recall(); assert d.rebuilds == 1
    write_any_ledger_row(led); d.recall(); assert d.rebuilds == 2
    insert_then_delete_a_placement(house); d.recall(); assert d.rebuilds == 3
    d.clock_to(d.cache_horizon()); d.recall(); assert d.rebuilds == 4
    # two publishers, one agent: one entry per house (R31)
    d2, (pub_a, house_a), (pub_b, house_b) = cached_daemon_two_publishers(tmp_path / "two")   # A places M1, B M5
    assert d2.recall_ids(pub_a) == {M1} and d2.recall_ids(pub_b) == {M5} and d2.rebuilds == 2
    assert d2.recall_ids(pub_a) == {M1} and d2.recall_ids(pub_b) == {M5} and d2.rebuilds == 2
    insert_then_delete_a_placement(house_b)
    assert d2.recall_ids(pub_a) == {M1} and d2.rebuilds == 2              # B's counter is not A's
    assert d2.recall_ids(pub_b) == {M5} and d2.rebuilds == 3

def test_e1_use_11_the_cache_entry_ends_at_its_horizon(tmp_path):
    d, ids = e1_daemon_after_use_10(tmp_path)               # no ledger write after 2026-11-20
    d.clock_to(T("2026-11-30") - 1); assert M2 in d.recall_ids()
    d.clock_to(T("2026-12-01")); assert M2 not in d.recall_ids() and M1 in d.recall_ids()

def test_rf3_cache_not_served_before_its_time(tmp_path):
    d = cached_daemon_with_allow_starting(tmp_path, T("2026-11-05"))
    d.clock_to(T("2026-11-06")); assert M1 in d.recall_ids()
    d.clock_to(T("2026-11-04")); assert M1 not in d.recall_ids()

def test_sf9_a_policy_change_between_two_cached_recalls_takes_effect_with_no_rebuild(tmp_path):
    d, led, house = cached_daemon(tmp_path)
    assert M1 in d.recall_ids() and d.rebuilds == 1
    write_publisher_policy(tmp_path, allows_recall=False)        # the legacy file changes; the ledger does not
    assert d.recall_ids() == set() and d.rebuilds == 1
    write_publisher_policy(tmp_path, allows_recall=True)
    write_receiver_policy(tmp_path, allows_recall=False)
    assert d.recall_ids() == set() and d.rebuilds == 1
    write_receiver_policy(tmp_path, allows_recall=True)
    write_publisher_policy(tmp_path, allows_recall=True, receiver_audiences=["group:other"])   # engram:audiences
    assert M1 not in d.recall_ids() and d.rebuilds == 1          # the legacy audience check runs on every request

def test_meet_legacy_equals_deciding_with_legacy():
    for case in range(500):
        rng = random.Random(f"{SEED}-meet-legacy-{case}")
        w = random_world(rng)
        for u in sample_uses(rng, w, 10):
            legacy = random_legacy_layers(rng)
            got = meet_legacy(decide(w.state(), u), u, legacy)
            assert got.to_json() == decide(w.state(), u, legacy=legacy).to_json(), (SEED, case)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_daemon_cache.py`
Expected: FAIL, `ImportError: cannot import name 'eligible_set'`.

- [ ] **Step 3: Implement `eligible_set` and the cache**

`eligible_set` runs P 6.5's pre-filter once per (layer, action) for the requester, place, action and purpose, then
matches each placement's object against only those records. The cache's horizon is the earliest over its decisions.
At each recall the daemon takes the cached set, meets each placement's decision with this frame's legacy verdicts
through `meet_legacy`, and keeps the placements whose hand-written audiences pass `_allowed_audiences` for this
frame. The receipt's `cited` holds both the cached ledger citations and this frame's legacy ones.
`d.rebuilds` is a counter the daemon keeps for tests and logs. `cached_daemon_two_publishers` is `cached_daemon` with
a second publisher house B, registered at `place:home/andy` like A, holding one placement of M5 that the same allow
covers; `recall_ids(pub)` sends the recall frame to that publisher.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_daemon_cache.py tests/test_permissions_daemon.py tests/test_permissions_daemon_gate.py tests/test_lighthouse_daemon.py tests/test_daemon_audiences.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/lighthouse_daemon.py engram/permissions.py engram/tests/test_permissions_daemon_cache.py \
        engram/tests/permissions_support.py
git commit -m "Daemon: the eligible-set cache keyed on seq, placement changes and the horizon (P 12.2, L8)"
```

### Task 22: The receivers

**Files:**
- Modify: `engram/lighthouse_client.py:286-337` (`validate_read`), `engram/neighbors.py` (`neighbor_arm`'s delivered
  items and the receipt's `extensions`), `engram/context_lighthouse.py:28-34` (`_evidence`, `_version`)
- Test: `engram/tests/test_permissions_receivers.py`

**Interfaces:**
- Consumes: Task 20's `annotation_line`.
- Produces: `validate_read` accepts an item whose keys are `{"memoryId", "content", "audiences", "decision"}` plus an
  optional `"permission"` object of exactly `{"laid_by", "allowed_by", "until", "receipt"}` with P 11's types, and
  still rejects any other member; the verified entry keeps it. `neighbor_arm` replaces each delivered item's
  `permission` object by its `annotation_line` string, and sets `receipt["extensions"]["engram:permissions"] =
  {"receipts": [...], "records": [...]}` (sorted ids) when any delivered item had one. `_evidence` copies `permission`
  when the item has it, as its one line: a search item already holds the string (it came through `neighbor_arm`),
  and an item that holds the object gets its `annotation_line`. So an item without one keeps its digest, and the
  model sees the line.
- `_version(item)` hashes `_evidence` of the item **without** its `permission` member. The context runtime checks
  each candidate again before dispatch: `_read_entries` reads the item again through `validate_read`
  (`engram/context_lighthouse.py:170`) and keeps it only when its version equals the version from search
  (`:180-181`), and `prepare_dispatch` drops any candidate whose version differs (`:208-210`). The re-read item holds
  the `permission` object, not the line, and each read writes a new receipt (P 9.1), so the line's `receipt #…`
  changes every read. Were `permission` in the version, under `shadow` and `enforce` every Lighthouse candidate would
  fail that check and none would be delivered. The version still names the content and its source. A re-read whose
  decision now refuses has `content: null`, so `validate_read` skips it (`engram/lighthouse_client.py:324-325`), its
  key is missing from `verified`, and `prepare_dispatch` drops the candidate (`engram/context_lighthouse.py:209-210`),
  as today.

- [ ] **Step 1: Write the failing tests**

```python
def test_u9_the_client_accepts_permission_and_still_rejects_any_other_member():
    assert validate_read(reply_with(permission=PERMISSION_OBJ), selected=SELECTED)[0]["permission"] == PERMISSION_OBJ
    for bad in [reply_with(extra=1), reply_with(permission={**PERMISSION_OBJ, "x": 1})]:
        with pytest.raises(NeighborUnavailable):
            validate_read(bad, selected=SELECTED)

def test_u10_permission_reaches_each_delivered_item_as_one_line(crossing_with_ledger):
    out = run_neighbor_arm(crossing_with_ledger, long_place_names=True)
    for item in out["delivered"]:
        assert isinstance(item["permission"], str) and len(item["permission"]) <= 240
        assert "\n" not in item["permission"] and re.search(r"receipt #[0-9a-f]{8}$", item["permission"])
    assert "…" in out["delivered"][0]["permission"] and re.search(r"\+\d+", out["delivered"][0]["permission"])

def test_u10_the_context_runtime_evidence_carries_it(context_crossing_with_ledger):
    source = context_crossing_with_ledger.source                   # a LighthouseSource; E1's use 1 is allowed
    [candidate] = source.search("allergy", limit=1)
    line = candidate.representations[0]
    assert re.search(r"receipt #[0-9a-f]{8}", line) and "laid by andy (engram)" in line
    plain = {k: v for k, v in source.entries[candidate.id]["item"].items() if k != "permission"}
    assert _version(plain) == candidate.version                      # the line is not in the version

def test_mf1_a_candidate_with_a_permission_line_survives_prepare_dispatch(context_crossing_with_ledger):
    for mode in ("shadow", "enforce"):
        source = context_crossing_with_ledger.source_at(mode)
        [candidate] = source.search("allergy", limit=1)
        first = latest_receipt_id(context_crossing_with_ledger, action="inject_context")
        invalid, info = source.prepare_dispatch([candidate], "0" * 64)
        assert invalid == set() and info["invalidated_ids"] == [], mode
        assert latest_receipt_id(context_crossing_with_ledger, action="inject_context") != first   # a new receipt

def test_mf1_a_re_read_that_is_now_refused_still_drops_the_candidate(context_crossing_with_ledger):
    source = context_crossing_with_ledger.source_at("enforce")
    [candidate] = source.search("allergy", limit=1)
    revoke_r1(context_crossing_with_ledger)                         # the next decision refuses m1
    invalid, _ = source.prepare_dispatch([candidate], "0" * 64)
    assert invalid == {candidate.id}

def test_u10_the_recall_receipt_validates_with_the_engram_permissions_extension(crossing_with_ledger):
    receipt = stored_receipt(crossing_with_ledger)
    validate_receipt(receipt)
    assert set(receipt["extensions"]["engram:permissions"]) == {"receipts", "records"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_receivers.py`
Expected: FAIL, `NeighborUnavailable: INVALID_READ` on the first test.

- [ ] **Step 3: Implement the three changes**

The protocol version stays `0.1` (P 12.2).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_receivers.py tests/test_lighthouse_client.py tests/test_neighbors.py tests/test_context_lighthouse.py tests/test_lighthouse_receipts.py tests/test_recall_neighbors.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/lighthouse_client.py engram/neighbors.py engram/context_lighthouse.py \
        engram/tests/test_permissions_receivers.py
git commit -m "Receivers: accept and pass the permission line; the engram:permissions receipt extension (P 11, 12.1)"
```

### Task 23: `share`, `permit` and `permissions`

**Files:**
- Modify: `engram/sharing.py:99-173` (`share` gains `source_instance_id`, `record_id`, the placement bound, and the
  existing-row path at `:118-129`), `engram/server.py:1949-2020` (`share`, `unshare`, and two new tools beside them),
  `engram/permissions.py` (`share_cover`)
- Modify (R29, the one existing test line this plan changes): `engram/tests/test_packaging.py:225`, `== 43` to `== 45`
- Test: `engram/tests/test_permissions_server.py`

**Interfaces:**
- Consumes: Tasks 9, 11 to 13, 15, 18.
- Produces:
  - `sharing.share(..., source_instance_id: str | None = None, record_id: str | None = None)` writes both columns,
    and refuses the 20,001st placement in a house with `ValueError` naming the bound, in every mode. The bound is
    checked after the existing-row path, since sharing an existing row again adds no placement. When the
    `(source_instance, source_id, audience)` row already exists (`engram/sharing.py:118-129`), it fills that row's
    `source_instance_id` and `record_id` where they are null and a value is given, in the same transaction, and
    never overwrites a value that is set. So a row `migrate` left unmatched is mended when Andy shares it again (P 12.3
    step 2), and the reply is the same share id;
  - `permissions.share_cover(state, *, owner: str, obj: str, audience: str, at: int) -> str | None`: the id of an
    effective allow in the owner's home layer that covers `obj` for `recall`, `read` and `inject_context` for some
    purpose and that audience, chosen as `decide` chooses (latest effective end, then smallest id), else `None`;
  - `server._permission_gate() -> Gate` over the published house. It reads no config and needs no `_init`;
  - the `share` tool: under `off` as today plus `source_instance_id`. Under `shadow` as today plus both columns,
    `record_id` being `share_cover`'s answer or null. Under `shadow` and `enforce`, placing a copy also writes the
    memory's first lane note when it has none (P 5.3), with the lane and `created_at` read from the server's own
    storage. Under `enforce` it never writes a record: it maps `commons` to `place:home/<owner>`, `group:g` to the
    ledger group, accepts `place:Z`, and places a copy only when `share_cover` finds an allow, with
    `audience = placement_audience(...)` and `record_id` of that allow; otherwise it returns
    `{"status": "needs-allow", "permit": {...}, "cli": "engram-permissions allow ..."}`. Under `closed` it refuses;
  - `permit(op: str, selector: dict | None = None, valid_from: int | None = None, valid_until: int | None = None,
    reason: str = "", record: str | None = None, collection: str | None = None, memory: str | None = None,
    args: dict | None = None) -> dict`: through `Ledger.perform` with channel `tool` and actor `agent:<instance>`
    (R13), returning `{"status": "done" | "proposal", "ref", "under_grant"}`; refused under `closed`. `op` is one of
    the seven grant ops, with the named arguments, or one of R26's act kinds (`grant`, `group`, `register-agent`,
    `put-agent`, `add-steward`, `register-place`, `add-parent`, `register-store`, `remove-subject`, `gate`), with
    `args` holding that act's arguments as Tasks 11 to 13 name them. For `gate` that is `{"mode": ...}` alone: the
    agent names no house (R26, Task 13). Each of R26's kinds is always filed as a
    proposal for the owner. `op="migrate"` returns `{"error": "migrate is not a tool act; the person runs
    engram-permissions migrate in their terminal"}` and writes nothing. Any other `op` is an error;
  - `permissions(focus: str = "uses", since: str | None = None, until: str | None = None, action: str | None = None,
    purpose: str | None = None, obj: str | None = None) -> dict`, read-only. For an agent whose registered principal
    is `meta.owner` it returns the owner's list (`focus="uses"`), the rules, the open proposals or the grants. For any
    other registered agent it returns `{"focus": "uses", "rows": Uses.agent_view(agent)}` for `uses` and the error of
    R28 for the rest; for an unregistered agent, that error for every focus;
  - `unshare` unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_u11_share_with_no_covering_allow_changes_nothing_and_returns_the_permit_call(enforce_server):
    out = server.share(memory_id=M_LOCAL, audience="place:la-county/public-health", reason="r")
    assert out["status"] == "needs-allow" and out["permit"]["op"] == "share" and server.shares()["shares"] == []

def test_u11_with_a_covering_allow_it_places_a_copy_with_the_placement_audience_and_record_id(enforce_server):
    rid = andy_allows(M_LOCAL, audience=["place:la-county/public-health"])
    out = server.share(memory_id=M_LOCAL, audience="place:la-county/public-health", reason="r")
    row = placement_row(out["share_id"])
    assert row["audience"] == "group:outside-home" and row["record_id"] == rid and row["source_instance_id"]

def test_u11_permit_inside_the_envelope_is_grant_backed_and_outside_is_a_proposal(enforce_server):
    gid = andy_grants_default(ops={"share"}, envelope=HOME_SELECTOR, max_days=30)   # a root grant, through perform
    inside = server.permit(op="share", selector=HOME_SELECTOR, valid_until=now() + 30 * 86400, reason="r")
    assert inside["status"] == "done" and inside["under_grant"] == gid
    rec = ledger_state().records[inside["ref"]]
    assert (rec.backing, rec.set_by, rec.channel) == (f"grant:{gid}", "agent:default", "tool")
    before = ledger_tables()
    outside = server.permit(op="share", selector=PUBLIC_HEALTH_SELECTOR, valid_until=now() + 30 * 86400, reason="r")
    assert outside["status"] == "proposal" and outside["under_grant"] is None    # its audience is outside the envelope
    assert only_proposal_rows_changed(before, ledger_tables())
    [p] = [p for p in ledger_tables()["proposals"] if p["id"] == outside["ref"]]
    assert (p["by_agent"], p["for_person"]) == ("agent:default", "person:andy")

def test_u11_unshare_always_works(enforce_server, tmp_path):
    rid = andy_allows(M_LOCAL, audience=["place:home/andy"])
    first = server.share(memory_id=M_LOCAL, audience="commons", reason="r")["share_id"]
    andy_allows(M_OTHER, audience=["place:home/andy"])
    second = server.share(memory_id=M_OTHER, audience="commons", reason="r")["share_id"]
    revoke_as_andy(rid)                                       # no allow covers the first one now
    before = ledger_tables()
    assert server.unshare(share_id=first) == {"removed": True} and placement_row(first) is None
    assert (ledger_tables()["records"], ledger_tables()["proposals"]) == (before["records"], before["proposals"])
    make_ledger_unreadable(tmp_path)                          # closed: share and permit refuse, unshare does not
    assert server.unshare(share_id=second) == {"removed": True} and placement_row(second) is None

def test_u9_the_20001st_placement_is_refused(tmp_path):     # P 12.2, "Bounds"; at the sharing layer, every mode
    house, source, old = house_with_placements(tmp_path, n=MAX_PLACEMENTS)
    new = source_episode(source, "a new memory")
    with pytest.raises(ValueError, match="20,000"):
        sharing.share(source_storage=source, published_storage=house, source_id=new, layer="episode",
                      audience="commons", reason="r", source_instance="default")
    assert placement_count(house) == MAX_PLACEMENTS
    again = sharing.share(source_storage=source, published_storage=house, source_id=old, layer="episode",
                          audience="commons", reason="r", source_instance="default")   # an existing row is no new one
    assert again.share_id == share_id_of(house, old) and placement_count(house) == MAX_PLACEMENTS
    sharing.unshare(published_storage=house, share_id=again.share_id)
    sharing.share(source_storage=source, published_storage=house, source_id=new, layer="episode",
                  audience="commons", reason="r", source_instance="default")         # below the bound again
    assert placement_count(house) == MAX_PLACEMENTS
def test_u16_closed_refuses_share_and_permit(enforce_server, tmp_path):
    make_ledger_unreadable(tmp_path)                                   # the gate now reads closed
    before = house_bytes(tmp_path)
    for out in (server.share(memory_id=M_LOCAL, audience="commons", reason="r"),
                server.permit(op="share", selector=HOME_SELECTOR, reason="r")):
        assert "error" in out and "closed" in out["error"]
    assert house_bytes(tmp_path) == before

def test_u18_each_widening_act_through_the_mcp_tools_is_filed_as_a_proposal(enforce_server):
    for op, kwargs in WIDENING_THROUGH_PERMIT:    # one per row of P 7.6's table that is one Act (R26), below
        before = ledger_tables()
        assert server.permit(op=op, **kwargs)["status"] == "proposal", op
        assert only_proposal_rows_changed(before, ledger_tables()), op
    before = ledger_bytes()
    assert "engram-permissions migrate" in server.permit(op="migrate")["error"] and ledger_bytes() == before
    assert not [r for r in ledger_tables()["records"] if r["set_by"] == "agent:default"]

def test_permissions_tool_is_read_only(enforce_server):
    before = ledger_bytes()
    for focus in ("uses", "rules", "proposals", "grants"):
        assert "error" not in server.permissions(focus=focus)
    assert ledger_bytes() == before

def test_r28_an_agent_not_acting_for_the_owner_sees_only_its_own_receipts(keep_world):   # Task 25's fixture
    deliver_m1_through(keep_world, "neighbors"); refused_read_of_m3(keep_world)   # E1 uses 1 and 2
    out = server.permissions(focus="uses")
    assert {"object", "at", "outcome"} <= set(out["rows"][0]) and "counts" not in out
    assert all(set(r) <= {"object", "at", "outcome", "count", "sha256", "permission"} for r in out["rows"])
    text = json.dumps(out)
    assert "jenn" not in text and "place:home" not in text and "NO_ALLOW" not in text
    for focus in ("rules", "proposals", "grants"):
        assert server.permissions(focus=focus) == {"error": "only agents acting for the ledger owner can read this"}

def test_sf8_sharing_an_unmigrated_row_again_fills_its_identity(enforce_server):
    sid = unmigrated_commons_row(M_LOCAL)            # a share row with null source_instance_id and record_id
    rid = andy_allows(M_LOCAL, audience=["place:home/andy"])
    out = server.share(memory_id=M_LOCAL, audience="commons", reason="again")
    row = placement_row(sid)
    assert out["share_id"] == sid and row["source_instance_id"] == STORE_ID and row["record_id"] == rid
    set_record_id(sid, "r-" + "0" * 32)
    server.share(memory_id=M_LOCAL, audience="commons", reason="again")
    assert placement_row(sid)["record_id"] == "r-" + "0" * 32                  # a set value is never overwritten

def test_u16_a_config_that_fails_to_parse_changes_no_mode(enforce_server, tmp_path, monkeypatch, caplog):
    (tmp_path / ".engram" / "config.toml").write_text("[permissions\n")       # moved here from Task 18
    assert resolve_db_path(tmp_path) == tmp_path / ".engram" / "graph.db"     # the resolver warns and falls back
    assert "Could not load config" in caplog.text
    monkeypatch.setattr(server, "_initialized", False)
    with pytest.raises(tomllib.TOMLDecodeError):
        server._init()                                                        # as today: no server starts on it
    assert server._permission_gate() == Gate("enforce", None)
```

The fixtures:

- `enforce_server`: `engram_server_env` (instance unset, so its agent is `agent:default`, R13). The published house
  `instances/lighthouse/graph.db` is made through `Storage` (with `house_dir`). `Ledger.create(tmp_path, "andy")`,
  then as `person:andy` on channel `terminal` through `perform`: `county_ledger`'s registry rows (so
  `place:la-county/public-health` exists); stores for the server's own store (`STORE_ID`, read from its `meta`) and
  for the published house, both owned by Andy at `place:home/andy`; `agent:default` acting for Andy, at his home;
  `make-collection collection:andy/local`; and `Act("gate", {"mode": "enforce"})`. `M_LOCAL` and `M_OTHER` are
  episodes made through `server.remember`.
- `HOME_SELECTOR`: audience `["place:home/andy"]`, kinds `["memory"]`, collections `["collection:andy/local"]`,
  actions `recall`, `read` and `inject_context`, purposes `"*"`, every other field `"*"`. `PUBLIC_HEALTH_SELECTOR` is
  the same with audience `["place:la-county/public-health"]` and purposes `["care-coordination"]`, outside home and
  within P 5.4's rules. `andy_grants_default(ops, envelope, max_days)` performs a root `grant` to `agent:default` as
  `person:andy` on channel `terminal` and returns its id; `revoke_as_andy(rid)` performs `revoke` the same way.
- `house_with_placements(tmp_path, n)` makes a published house and a source store, places one source episode `old`
  through `sharing.share`, then writes n − 1 more `shared_memories` rows by plain SQL in one transaction, each with its
  own `source_id`, so the test needs no embedder. It returns `(house, source, old)`. `source_episode(source, text)`
  adds an episode to the source; `placement_count` counts `shared_memories` rows; `share_id_of(house, source_id)`
  reads that row's share id.
- `WIDENING_THROUGH_PERMIT`: `share` outside any grant (a person-backed allow), `withdraw`, `shorten` and `narrow` on
  a consent deny, `collect` outside any grant, and R26's ten kinds: `grant` (a root grant), `group`,
  `register-agent`, `put-agent`, `add-steward`, `register-place`, `add-parent`, `register-store`, `remove-subject`
  and `gate`, each with valid `args` (for `gate`, `{"mode": "shadow"}` alone).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_server.py`
Expected: FAIL, `AttributeError: module 'server' has no attribute 'permit'`.

- [ ] **Step 3: Implement the tools**

Decorate `permit` and `permissions` with `@_server_tool()`, and `permit` also with `@_mutation_logged`, as `share` is.
That makes 45 tools, so change `tests/test_packaging.py:225` from `== 43` to `== 45` (R29), and nothing else in that
file.
Each call runs the sweep afterwards (Task 24 adds it; until then a no-op hook `_after_share()`). `permissions`
decides which answer to give from the ledger's `agents` row for `agent:<instance>`, read at each call.
`test_r28_...` uses Task 25's `keep_world`: write that fixture in `permissions_support.py` here, and Task 25 reuses
it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_server.py tests/test_share_tools.py tests/test_sharing.py tests/test_packaging.py::test_installed_wheel_starts_outside_checkout`
Expected: PASS, the packaging test with 45 tools. Then `git diff -U0 -- engram/tests/test_packaging.py | grep '^[-+][^-+]'`
prints exactly two lines, `-assert len(server.mcp._tool_manager.list_tools()) == 43` and the same line ending `== 45`.

- [ ] **Step 5: Commit**

```bash
git add engram/sharing.py engram/server.py engram/permissions.py engram/tests/test_permissions_server.py \
        engram/tests/permissions_support.py engram/tests/test_packaging.py
git commit -m "Server: share through records under enforce, permit, and the read-only permissions tool (P 12.1; R29: 45 tools)"
```

### Task 24: The sweep

**Files:**
- Modify: `engram/sharing.py` (new `sweep_placements`), `engram/server.py` (startup and `_after_share`)
- Test: `engram/tests/test_permissions_sweep.py`

**Interfaces:**
- Consumes: Tasks 9, 13, 17, 23.
- Produces: `sharing.sweep_placements(*, published_storage, ledger, mode: str, now: int, limit: int = 256)
  -> SweepReport(relinked: int, removed: int, would_remove: int, settled: int)`. Under `enforce` it relinks a
  placement whose record no longer counts to another effective allow of the same subject covering the same object with
  the same placement audience, or removes it (and the copy and vector with its last share row, as `unshare` does);
  under `shadow` it only counts `would_remove`; it settles pending lane notes by reading the source store's lane
  read-only. At most `limit` placements per pass, oldest first. The server's startup, under `shadow` and `enforce`,
  and the CLI's `sweep` also run `Uses.fold(now=...)`, so receipts past 400 days are folded (P 9.1, "Retention"). The
  server reads that `now` from `server._permission_now()`, integer UTC seconds, a seam this task adds for its test.

- [ ] **Step 1: Write the failing tests**

```python
def test_u12_after_a_revocation_the_placements_go_within_one_pass(tmp_path):
    house, led = enforce_house_with_placements(tmp_path, n=300, linked_to="R")
    revoke(led, "R")
    first = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-05"))
    assert first.removed == 256
    second = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-05"))
    assert second.removed == 44 and copies_left(house) == 0

def test_u12_after_an_expiry_a_placement_is_relinked_when_another_allow_covers_it(tmp_path):
    house, led = enforce_house_with_placements(tmp_path, n=1, linked_to="R")   # R: outside home, ends 2026-11-10
    r2 = andy_allows(led, like="R", valid_until=T("2027-01-31"))   # same subject, object and placement audience
    other = andy_allows(led, like="R", audience=["group:g1"])      # covers the object, another placement audience
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-10"))
    assert (report.relinked, report.removed) == (1, 0)
    [row] = placement_rows(house)
    assert row["record_id"] == r2 and row["audience"] == "group:outside-home" and copies_left(house) == 1
    revoke(led, r2)
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-11"))
    assert (report.relinked, report.removed) == (0, 1) and copies_left(house) == 0     # `other` never relinks it
    assert other in led.state().records                                                 # and is left alone

def test_u12_the_copy_goes_with_its_last_share_row(tmp_path):
    house, led = enforce_house_with_placements(tmp_path, n=1, linked_to="R")   # one copy, its row linked to R
    add_share_row_for_the_same_copy(house, led, audience="group:g1", linked_to="RG")   # a second row, same copy
    revoke(led, "R")
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-05"))
    assert report.removed == 1 and len(placement_rows(house)) == 1
    assert copies_left(house) == 1 and vectors_left(house) == 1               # a row still holds the copy
    revoke(led, "RG")
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-05"))
    assert report.removed == 1 and placement_rows(house) == []
    assert copies_left(house) == 0 and vectors_left(house) == 0               # its last row: copy and vector go
def test_u12_the_sweep_settles_pending_lane_notes(tmp_path):
    house, led, store, ep = enforce_house_with_a_pending_note(tmp_path)    # the store committed `work`; no settling note
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-05"))
    assert report.settled == 1 and led.latest_lane_note(ref(store, ep)) == "work"   # read from the store, read-only

def test_shadow_only_reports_what_it_would_remove(tmp_path):
    house, led = shadow_house_with_placements(tmp_path, n=3, linked_to="R")
    revoke(led, "R"); before = house_bytes(house)
    report = sweep_placements(published_storage=house, ledger=led, mode="shadow", now=T("2026-11-05"))
    assert (report.would_remove, report.removed, report.relinked) == (3, 0, 0) and house_bytes(house) == before
def test_server_startup_folds_old_receipts(engram_server_env, tmp_path, monkeypatch):   # P 9.1, "Retention"
    _published_house(tmp_path); raise_gate_through_perform(tmp_path, "shadow")
    receipts_spanning_days(tmp_path, days=420)          # one receipt a day from 2026-11-01
    monkeypatch.setattr(server, "_permission_now", lambda: T("2026-11-01") + 420 * 86400)
    monkeypatch.setattr(server, "_initialized", False); server._init()
    uses = Uses.open(tmp_path)
    assert uses.verify() is None and monthly_counts(uses)
    assert min(r["at"] for r in rows(uses)) >= T("2026-11-01") + 20 * 86400    # older than 400 days: folded
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_sweep.py`
Expected: FAIL, `ImportError: cannot import name 'sweep_placements'`.

- [ ] **Step 3: Implement `sweep_placements` and its calls**

The server runs it at startup (after the storage opens), in `_after_share`, and after `unshare`. A use is refused at
once whether or not the sweep ran (P 10), so nothing waits on it. The test helpers `add_share_row_for_the_same_copy`
(a second `shared_memories` row naming the same copy, linked to its own allow), `vectors_left` (rows of
`episode_vectors` in the house), `raise_gate_through_perform(root, mode)` (a ledger owned by Andy with the published
house registered, raised through `perform`) and `receipts_spanning_days` (as Task 14's `rows_spanning_days`) live in
the test file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_sweep.py tests/test_sharing.py tests/test_share_tools.py tests/test_startup_maintenance.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/sharing.py engram/server.py engram/tests/test_permissions_sweep.py
git commit -m "Sharing: the sweep relinks or removes placements and settles pending lane notes (P 10)"
```

### Task 25: The `remember` guard and kept copies

**Files:**
- Modify: `engram/server.py:1826-1880` (`remember`), `:1443-1452` (genome sync call), `engram/federation.py:155-206`
  (`sync_genome`)
- Test: `engram/tests/test_permissions_keep.py`

**Interfaces:**
- Consumes: Tasks 5, 11, 13, 15.
- Produces:
  - `server._keep_check(content: str, *, agent: str, now: int, raw: str | None = None) -> dict | None`: `None` lets
    `remember` go on; else the reply. `content` is the stripped content `remember` keeps, `raw` the content as passed,
    before the strip (`engram/server.py:1849`). It acts only when the digest of either equals the `content_digest` of
    a delivery `Uses.deliveries(agent, now=now)` finds, and `decide`, over ledger layers only, refuses `imprint` for
    that item (R10). Under `off` it returns `None`. Under `shadow` it returns `None`
    and `remember` adds `"would_refuse": True` to its response. Under `enforce` it refuses; under `closed` it refuses as
    R11 says. When `permission-uses.db` exists but can't be read, it refuses every `remember` under `enforce` and
    `closed`, naming the cause, and under `shadow` logs the cause and lets it go on with `"would_refuse": True` (R11).
    To an agent that doesn't act for the owner the reply
    is exactly `{"error": "keeping this content is not allowed", "layer": "rejected"}`; to the owner's agents it adds
    the refusal's code, layer and action. When `imprint` is allowed, `remember` calls `Ledger.record_copy` for the new
    episode's ref before writing it (P25);
  - `federation.sync_genome(genome_path, instance_storage, *, ledger=None) -> int`: with a ledger it calls
    `record_copy(mem:<instance id>/episode/<local id>, mem:<genome id>/episode/<origin id>)` for each synced episode;
    the server passes one under `shadow` and `enforce`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("path", ["neighbors", "context_runtime"])
def test_u17_verbatim_delivered_content_is_refused_unless_imprint_is_allowed(keep_world, path):
    deliver_m1_through(keep_world, path)                  # writes an allowed inject_context receipt
    out = server.remember(content=M1_TEXT)
    assert out == {"error": "keeping this content is not allowed", "layer": "rejected"}

def test_u17_when_allowed_the_kept_memory_carries_its_source_subjects(keep_world_with_imprint_allowed):
    out = server.remember(content=M1_TEXT)
    kept = f"mem:{STORE_ID}/episode/{out['episode_id']}"
    assert ledger_state().copies[kept] == M1 and "person:andy" in subjects_of(ledger_state(), kept, now())

def test_u17_a_co_subject_added_to_the_source_afterwards_refuses_the_kept_copys_next_use(
        keep_world_with_imprint_allowed):
    out = server.remember(content=M1_TEXT)
    kept = f"mem:{STORE_ID}/episode/{out['episode_id']}"
    use = KEPT_USE(kept, at=now())                      # a read of the kept copy that Andy's and ph-steward's homes allow
    assert decide(ledger_state(), use).allowed
    add_subject(M1, "person:amy")                        # by Andy, on the source, after the copy was kept
    assert "person:amy" in subjects_of(ledger_state(), kept, now())          # through `copies` (7.4)
    # Amy is registered with an empty home (county_ledger, Task 11), so P 7.4 gives NO_ALLOW; Task 5's U28 case
    # holds the unregistered one, NO_LAYER
    assert decide(ledger_state(), use).refusal == Refusal("NO_ALLOW", "place:home/amy", "recall")

def test_u17_an_amy_co_subject_names_no_code_layer_or_action_to_the_agent(keep_world):
    deliver_m1_through(keep_world, "neighbors"); add_subject(M1, "person:amy")   # place:home/amy fails first
    out = server.remember(content=M1_TEXT)
    assert "amy" not in json.dumps(out) and set(out) == {"error", "layer"}
    view = Uses.open(ENGRAM_HOME).agent_view("agent:ph-coordinator")
    assert all(set(r) <= {"object", "at", "outcome", "count", "sha256", "permission"} for r in view)
    assert "amy" not in json.dumps(view)

def test_the_guard_reads_only_the_last_24_hours_and_200_receipts(keep_world):
    t0 = deliver_m1_through(keep_world, "neighbors")     # returns the delivery receipt's `at`
    agent = "agent:ph-coordinator"
    assert server._keep_check(M1_TEXT, agent=agent, now=t0 + GUARD_SECONDS - 1) is not None
    assert server._keep_check(M1_TEXT, agent=agent, now=t0 + GUARD_SECONDS) is None      # 24 hours, half-open
    deliver_other_items(keep_world, GUARD_RECEIPTS, at=t0 + 1)        # 200 newer deliveries of other content
    assert len(Uses.open(ENGRAM_HOME).deliveries(agent, now=t0 + 60)) == GUARD_RECEIPTS
    assert server._keep_check(M1_TEXT, agent=agent, now=t0 + 60) is None                 # m1's is the 201st

def test_the_guard_catches_a_verbatim_copy_with_surrounding_whitespace(keep_world):
    deliver_item_with_content(keep_world, "  " + M1_TEXT + "\n")        # delivered with whitespace around it
    out = server.remember(content="  " + M1_TEXT + "\n")                # remember strips it before hashing
    assert out == {"error": "keeping this content is not allowed", "layer": "rejected"}

def test_genome_sync_records_kept_copy_subjects_under_shadow(tmp_path):   # P 12.1's genome sync row; P25
    led, genome_path, instance, ids = genome_world(tmp_path, mode="shadow")
    assert federation.sync_genome(str(genome_path), instance, ledger=led) == 1
    [local] = [r["id"] for r in instance.conn.execute("SELECT id FROM episodes WHERE episode_type = 'genome_sync'")]
    copy, source = f"mem:{ids.I}/episode/{local}", f"mem:{ids.G}/episode/{ids.g1}"
    s = led.state()
    assert s.copies[copy] == source
    assert subjects_of(s, copy, T("2026-11-02")) == ("person:andy", "person:jenn")    # the source's, carried
    assert {(r["subject"], r["added_by"]) for r in led.tables()["subjects"] if r["object"] == copy} == {
        ("person:jenn", f"copy:{source}")}
    assert federation.sync_genome(str(genome_path), instance, ledger=led) == 0 and led.state().copies == s.copies
    plain = genome_world(tmp_path / "no-ledger", mode=None)                       # no ledger: as today
    assert federation.sync_genome(str(plain[1]), plain[2]) == 1 and not ledger_path(tmp_path / "no-ledger").exists()

def test_r11_an_unreadable_receipts_file_refuses_every_remember_under_enforce(keep_world, caplog):
    make_uses_file_unreadable(ENGRAM_HOME)
    out = server.remember(content="a note that was never delivered")
    assert out == {"error": "keeping this content is not allowed", "layer": "rejected"}
    assert "permission-uses.db" in caplog.text

def test_off_has_no_guard(engram_server_env, tmp_path, monkeypatch):
    write_delivery_receipt(tmp_path, content=M1_TEXT, agent="agent:default")   # a receipts file, and no ledger
    monkeypatch.setattr(Uses, "open_read_only", fails_the_test)               # off never opens it
    out = server.remember(content=M1_TEXT)
    assert out.get("episode_id") and "would_refuse" not in out and not ledger_path(tmp_path).exists()
```

`keep_world` (written in Task 23, in `permissions_support.py`): `engram_server_env` with the server's instance name
set to `ph-coordinator`, so its agent is `agent:ph-coordinator` (R13) and its store `instances/ph-coordinator/graph.db`
(made with `house_dir`, then opened once with `Storage` before `_init`: `_init_unlocked` uses that path only when the
file exists, `engram/server.py:1309`, and otherwise falls back to the default store, which `attach_neighbors` then
refuses with `RECEIVER_STORE_MISMATCH`, `engram/neighbors.py:188-189`). The ledger is `e1_county_ledger`'s (so
`person:amy` is registered, with an empty home), plus that store registered as `PHC_STORE`, owned by
`person:ph-steward` at clinic-3, and the published house holding m1, m2 and m3 linked as P 13 says; both
ConnectionPolicy files and the receiver's `lighthouse-receiver.toml` are written by hand as P 13 says; the gate is
raised to `enforce` through `perform`. `deliver_m1_through(world, path)` runs E1's use 1 at 2026-11-02 through
`neighbor_arm` or the context runtime against a `PublisherDaemon` on a socket in `tmp_path`, so the daemon writes the
allowed `inject_context` receipt, and returns its `at`. `keep_world_with_imprint_allowed` adds allows for `imprint` of
m1 in `place:home/andy`, la-county, public-health and clinic-3, and an allow in Andy's home and in ph-steward's home
(the kept copy's two subjects) for `KEPT_USE`, a read of the kept copy by `agent:ph-coordinator` for
care-coordination; Amy's home stays empty. `add_subject(ref, subject)` performs `add-subject` as `person:andy` on
channel `terminal`. `genome_world(root, mode)` makes a genome store G at `.engram/genome/graph.db` holding one core-2
episode g1 and an empty instance store I; with a mode it also makes a ledger owned by Andy, raised to that mode
through `perform`, with G and I registered as Andy's stores at his home and `person:jenn` as g1's co-subject, and it
returns `(ledger or None, genome path, I's Storage, ids)`. `make_uses_file_unreadable` writes bytes that are not a
SQLite file to `permission-uses.db`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_keep.py`
Expected: FAIL, `AttributeError: module 'server' has no attribute '_keep_check'`.

- [ ] **Step 3: Implement the guard and the kept-copy rows**

The guard runs after `remember`'s input checks and before the embedding. `remember` keeps the content as passed in a
local before its strip and passes it as `raw`. The guard compares `content_digest(content)["value"]` and
`content_digest(raw)["value"]` with each delivery receipt's `content_digest`. Under `off` it opens no file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_keep.py tests/test_federation.py tests/test_remember_lane.py tests/test_server.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/server.py engram/federation.py engram/tests/test_permissions_keep.py
git commit -m "Keeping it is an imprint: the remember guard, and kept-copy subjects for remember and genome sync (P 7.4, 10)"
```

### Task 26: The CLI, the terminal yes and the registry commands

**Files:**
- Create: `engram/permission_cli.py`
- Modify: `engram/pyproject.toml` (`py-modules` gains `"permission_cli"`; `[project.scripts]` gains
  `engram-permissions = "permission_cli:main"`)
- Test: `engram/tests/test_permissions_cli.py`

The record, grant and proposal commands are Task 26A, so each task stays a handful of subcommands.

**Interfaces:**
- Consumes: Tasks 9 to 13.
- Produces:
  - `main(argv: list[str] | None = None) -> int`; `build_parser() -> argparse.ArgumentParser`; `TTY = "/dev/tty"`;
    `confirm(words: str, change: str) -> bool` prints the words, then the full change, then a code from `_code()`,
    and reads the code from `TTY`; it raises `NoTerminal` when `TTY` can't be opened. Exit codes per R12: 0 done, 1
    refused by a rule, 3 no terminal or a wrong code (2 stays argparse's usage error);
  - `init`: refuses when a ledger exists; takes the owner's handle from the Unix login (R24), prints "Create a ledger
    owned by person:<handle>", asks the yes, then `Ledger.create`;
  - registry subcommands that write, each acting as `meta.owner` with channel `terminal` after `confirm`: `person add
    <handle>` and `person retire <handle>`, `agent add <name> --acts-for <ref>`, `agent place <name> <place>`,
    `agent unplace <name> <place>`, `store add <instance_id> --name N --place P [--imprint-of ID]`, `place register
    <place> [--parent P]... [--name TEXT] [--steward PERSON]...` (default steward: the owner), `place parent <place>
    <parent>`, `place steward add|remove <place> <person>`, `place retire <place>`, `group set <name> <agent>...`,
    `collection add|remove <collection> <ref>...`, `subject add|remove <ref> <subject>`. `collection add` reads each
    ref's lane and `created_at` from its store with `Storage.open_read_only` and passes them as `lanes` (Task 11);
  - every id argument goes through `resolve_prefix` against the ledger; times take `YYYY-MM-DD` or RFC 3339 UTC; no
    subcommand takes an argument naming who acts.

- [ ] **Step 1: Write the failing tests**

```python
def test_u18_refused_without_a_terminal(cli_home, monkeypatch, capsys):
    monkeypatch.setattr(permission_cli, "TTY", str(cli_home / "no-such-tty"))
    before = ledger_bytes(cli_home)
    assert main(["person", "add", "jenn"]) == 3 and ledger_bytes(cli_home) == before

def test_u18_a_wrong_code_writes_nothing(cli_home, fake_tty):
    fake_tty.answer("wrong1"); before = ledger_bytes(cli_home)
    assert main(["person", "add", "jenn"]) == 3 and ledger_bytes(cli_home) == before

def test_r12_a_usage_error_is_argparses_2_not_the_yes_code(cli_home, fake_tty):
    with pytest.raises(SystemExit) as exit_:
        main(["person", "add"])                       # the handle is missing
    assert exit_.value.code == 2

def test_r24_init_names_the_login_as_owner_and_refuses_a_second_ledger(tmp_path, fake_tty, monkeypatch, capsys):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path)); monkeypatch.setattr(getpass, "getuser", lambda: "andy")
    fake_tty.answer_the_printed_code(); assert main(["init"]) == 0
    assert "Create a ledger owned by person:andy" in capsys.readouterr().out
    assert Ledger.open(tmp_path).meta()["owner"] == "person:andy"
    fake_tty.answer_the_printed_code(); assert main(["init"]) == 1     # a ledger exists
    monkeypatch.setattr(getpass, "getuser", lambda: "Andy Z")
    assert main_in(tmp_path / "other", ["init"]) == 1                  # a login that is not a handle

def test_u18_no_registry_command_acts_as_anyone_but_the_owner(cli_home, fake_tty):
    for argv in every_registry_subcommand_with_sample_args(cli_home):
        fake_tty.answer_the_printed_code()
        main(argv)
    assert {row["actor"] for row in log_rows(cli_home) if row["channel"] == "terminal"} == {"person:andy"}
    assert not all_option_names(permission_cli.build_parser()) & {"--as", "--actor", "--person", "--by", "--owner"}

def test_collection_add_passes_each_memorys_lane_and_created_at(cli_home_with_store, fake_tty):
    fake_tty.answer_the_printed_code()
    assert main(["collection", "add", "collection:andy/c", M1]) == 0
    assert latest_lane_note_row(cli_home_with_store, M1) == ("personal", M1_CREATED_AT)
```

`fake_tty` monkeypatches `permission_cli.TTY` to a FIFO in `tmp_path` and `permission_cli._code` to a fixed code it
can answer. `cli_home` sets `ENGRAM_HOME` to `tmp_path`, sets `getpass.getuser` to `"andy"`, and runs `init` once.
`cli_home_with_store` adds an engram store at `.engram/graph.db` holding M1 (`personal`, made at `M1_CREATED_AT`),
registered through `store add`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_cli.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'permission_cli'`.

- [ ] **Step 3: Implement `engram/permission_cli.py`**

`argparse` subparsers. Each writing command builds its `Act`, prints the act's plain words plus the full change,
calls `confirm`, then `Ledger.perform(..., actor=meta["owner"], channel="terminal")`. After a write it prints the
gluing reports whose `notify` holds the owner and runs the sweep (R18). Refusals print the rule and exit 1.
`NoTerminal` and a wrong code exit 3.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_cli.py tests/test_packaging.py::test_lockfile_matches_project_metadata`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_cli.py engram/pyproject.toml engram/tests/test_permissions_cli.py
git commit -m "engram-permissions: the terminal yes, init and the registry commands (P 4.4, 7.6, 14)"
```

### Task 26A: The CLI's record, grant and proposal commands

**Files:**
- Modify: `engram/permission_cli.py`
- Test: `engram/tests/test_permissions_cli_records.py`

**Interfaces:**
- Consumes: Tasks 12 and 26.
- Produces:
  - subcommands that write, each as `meta.owner` on channel `terminal` after `confirm`: `allow` and `deny`
    (`--layer --selector JSON|@file --from --until --reason`), `revoke <id> [--reason]`, `shorten <id> --until`,
    `narrow <id> --selector`, `grant --to --ops --envelope --max-days --depth --hours [--parent]`,
    `revoke-grant <id>`, `sign <id>`, `decline <id>`. `allow` prints `allow_words`; every command prints the full
    change (selector in canonical JSON, `valid_from`, `valid_until`, the layer, the replaced record). `sign` prints
    the proposal's words and the full change it will make, for every proposal kind of R26. For a gate proposal that
    change is `Ledger.gate_plan()` at the time of the yes (Task 13): the published house, every house it will mark,
    and each house that lacks migration 029, saying it serves nothing under `shadow` or `enforce` until an engram
    server opens it once (R26, R27), as Task 27's `gate` prints;
  - a reading subcommand, no yes: `proposals`.

- [ ] **Step 1: Write the failing tests**

```python
def test_u18_no_command_acts_as_anyone_but_the_owner(cli_home, fake_tty):
    for argv in every_writing_subcommand_with_sample_args(cli_home):      # Task 26's and this task's
        fake_tty.answer_the_printed_code()
        main(argv)
    assert {row["actor"] for row in log_rows(cli_home) if row["channel"] == "terminal"} == {"person:andy"}

def test_u18_each_widening_act_works_only_with_the_yes(cli_home, fake_tty):
    for argv in P76_TABLE_ARGV:                       # one command per row of P 7.6's table except migrate and gate
        before = ledger_bytes(cli_home)
        fake_tty.answer("wrong1"); assert main(argv) == 3 and ledger_bytes(cli_home) == before, argv
        fake_tty.answer_the_printed_code(); assert main(argv) == 0, argv

def test_u26_the_cli_takes_full_ids_and_unique_prefixes_and_refuses_ambiguous_ones(cli_home, fake_tty, capsys):
    a, b = two_records_sharing_a_4_hex_prefix(cli_home)
    fake_tty.answer_the_printed_code()
    assert main(["revoke", a[:8], "--reason", "r"]) == 0
    assert main(["revoke", a[:6], "--reason", "r"]) == 1 and a in capsys.readouterr().err

def test_u14_sign_prints_the_full_selector_before_asking(cli_home, fake_tty, capsys):
    pid = file_parks_proposal_through_permit(cli_home)
    fake_tty.answer_the_printed_code(); main(["sign", pid])
    out = capsys.readouterr().out
    assert out.index('"audience":["place:la-county/parks-and-rec"]') < out.index("code:")
    assert "valid_from" in out and "place:home/andy" in out

def test_r26_sign_completes_each_kind_the_tool_files(cli_home_with_house, fake_tty):   # gate needs the house
    for kind, pid in file_one_proposal_of_each_r26_kind(cli_home_with_house):   # through Ledger.perform, channel tool
        fake_tty.answer_the_printed_code()
        assert main(["sign", pid]) == 0, kind
    assert open_proposals(cli_home_with_house) == []

def test_rs2_sign_of_a_gate_proposal_lists_the_houses_and_those_lacking_029_before_the_yes(
        cli_home_with_house, fake_tty, capsys):
    pid = file_gate_proposal(cli_home_with_house, mode="shadow")    # its body holds {"mode": "shadow"} alone
    house_before_029(cli_home_with_house, "old")                    # made after the agent asked (Task 16's builder)
    fake_tty.answer_the_printed_code(); assert main(["sign", pid]) == 0
    out = capsys.readouterr().out
    assert out.index("instances/old/graph.db") < out.index("code:") and "serves nothing" in out
    assert out.index("instances/lighthouse/graph.db") < out.index("code:")
    old = cli_home_with_house / ".engram" / "instances" / "old" / "graph.db"
    assert house_meta(old)["permissions_ledger_id"] == Ledger.open(cli_home_with_house).meta()["ledger_id"]
```

`cli_home_with_house` (written here; Task 27 uses it too) is `cli_home` plus the published house
`instances/lighthouse/graph.db`, made through `Storage` with `house_dir`. `file_gate_proposal(home, mode)` registers
`agent:default` acting for the owner, at his home, through `perform` as the owner, then files `Act("gate", {"mode":
mode})` as that agent on channel `tool` and returns the proposal id.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_cli_records.py`
Expected: FAIL, `SystemExit: 2` from argparse (`invalid choice: 'allow'`).

- [ ] **Step 3: Implement the subcommands**

As Task 26's. `sign` resolves the proposal by prefix, prints `proposal_words` and the full `Act` it holds, and for a
gate proposal also `Ledger.gate_plan()`, asks the yes, then performs `sign`. A house made between the print and the
yes is marked too, since `perform` reads the houses again when it applies the act.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_cli_records.py tests/test_permissions_cli.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_cli.py engram/tests/test_permissions_cli_records.py
git commit -m "engram-permissions: allow, deny, revoke, shorten, narrow, grants, sign and decline (P 7.1-7.7)"
```

### Task 27: The CLI's gate, reading and checking commands

**Files:**
- Modify: `engram/permission_cli.py`
- Test: `engram/tests/test_permissions_cli_read.py`

**Interfaces:**
- Consumes: Tasks 7, 8, 13, 15, 23, 24, 26, 26A.
- Produces: subcommands `gate off|shadow|enforce` (with the yes; it refuses a raise without a published house and
  re-marks houses), `rebuild --out PATH`, `uses [--since] [--until] [--place] [--action] [--purpose] [--collection]
  [--object] [--refused] [--json]`, `check [place]`, `sweep`, `explain --agent --place (--object REF | --objects FILE
  [--counted]) --copy --action --purpose [--at] [--names FILE] [--json]`, `report shadow [--json]`, `place show <place>
  [--json]`. `explain` prints the decision of `decide` or `decide_bulk` and why, citing records.

- [ ] **Step 1: Write the failing tests**

```python
def test_u16_only_the_terminal_yes_moves_the_gate(cli_home_with_house, fake_tty):
    fake_tty.answer("wrong1"); assert main(["gate", "shadow"]) == 3
    assert effective_gate(cli_home_with_house, houses(cli_home_with_house)).mode == "off"
    fake_tty.answer_the_printed_code(); assert main(["gate", "shadow"]) == 0
    assert effective_gate(cli_home_with_house, houses(cli_home_with_house)).mode == "shadow"

def test_u16_gate_refuses_a_raise_without_a_published_house(cli_home, fake_tty, capsys):
    fake_tty.answer_the_printed_code()
    assert main(["gate", "shadow"]) == 1 and "published house" in capsys.readouterr().err

def test_u15_check_prints_the_summer_wellness_sentence(cli_e1_county, capsys):
    assert main(["check", "place:la-county/summer-wellness"]) == 0
    assert "Summer Wellness may only recall." in capsys.readouterr().out

def test_r27_gate_lists_the_houses_that_lack_029_before_the_yes(cli_home_with_house, fake_tty, capsys):
    house_before_029(cli_home_with_house, "old")
    fake_tty.answer_the_printed_code(); assert main(["gate", "shadow"]) == 0
    out = capsys.readouterr().out
    assert out.index("old") < out.index("code:") and "serves nothing" in out

def test_uses_place_shows_the_place_view_for_a_place_the_owner_stewards(cli_e1_world_andy_stewards_clinic_3, capsys):
    assert main(["uses", "--place", "place:la-county/public-health/clinic-3", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert "place:home" not in json.dumps(rows)                        # homes as pseudonyms (P 9.2, 9.3)
    assert main(["uses", "--place", "place:la-county/parks-and-rec", "--json"]) == 0   # not his: his list, filtered
    assert all(r["place"] == "place:la-county/parks-and-rec" for r in json.loads(capsys.readouterr().out)["rows"])

def test_report_shadow_lists_the_disagreements_and_the_shares_that_would_need_a_proposal(cli_shadow_world, capsys):
    # one shadow receipt the legacy path allowed and the ledger refused; one placement linked to a covering allow;
    # one placement shared under shadow that no allow covers (record_id null)
    assert main(["report", "shadow", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in out["disagreements"]] == [cli_shadow_world.refused_receipt]
    assert [s["share_id"] for s in out["would_need_a_proposal"]] == [cli_shadow_world.uncovered_share]

def test_explain_agrees_with_decide_for_a_single_and_a_bulk_use(cli_e1_world, capsys):   # P 14's `explain`
    s = Ledger.open(cli_e1_world).state()
    who = ["--agent", "agent:ph-coordinator", "--place", CLINIC_3, "--copy", HOUSE_COPY, "--purpose",
           "care-coordination", "--at", "2026-11-02"]
    assert main(["explain", *who, "--object", M3, "--action", "read", "--json"]) == 0      # E1 use 2: refused
    assert json.loads(capsys.readouterr().out) == decide(s, Use("agent:ph-coordinator", CLINIC_3, M3, HOUSE_COPY,
                                                                "read", "care-coordination", T("2026-11-02"))).to_json()
    objects = write_objects_file(cli_e1_world, [M1, M2])
    assert main(["explain", *who, "--objects", str(objects), "--counted", "--action", "recall", "--json"]) == 0
    bulk = BulkUse("agent:ph-coordinator", CLINIC_3, (M1, M2), HOUSE_COPY, "recall", "care-coordination",
                   T("2026-11-02"), named=False)
    assert json.loads(capsys.readouterr().out) == decide_bulk(s, bulk).to_json()
def test_place_show_prints_place_rules_and_refuses_a_home(cli_e1_county, capsys): ...
def test_rebuild_writes_a_file_with_the_same_tables(cli_e1_world, tmp_path): ...
def test_uses_json_matches_owner_list(cli_e1_world, capsys): ...
```

`CLINIC_3` is `place:la-county/public-health/clinic-3`, `HOUSE_COPY` is `store:<the published house's instance_id>`
in `cli_e1_world`, and `write_objects_file(home, refs)` writes one ref per line to a file in `home` and returns its
path. `explain --json` prints the decision's `to_json()`, so the test compares it with `decide` and `decide_bulk`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_cli_read.py`
Expected: FAIL, `SystemExit: 2` from argparse (`invalid choice: 'gate'`).

- [ ] **Step 3: Implement the subcommands**

`gate` builds `Act("gate", {"mode": mode})` (R26: the act names no house), and before the yes prints
`Ledger.gate_plan()`: the published house `ENGRAM_HOME/.engram/instances/lighthouse/graph.db`, every house of
`houses(ENGRAM_HOME)` it will mark, and each house that lacks migration 029, saying it serves nothing under `shadow` or
`enforce` until an engram server opens it once (R27). `uses --place P` shows `Uses.place_view` for a
place the owner stewards (P 9.3) and otherwise the owner's list filtered by place. `report shadow` lists:

- the disagreements: receipts with `shadow = 1` whose legacy verdicts all allow and whose `allowed` is 0;
- the shares that would have needed a proposal: every placement of the published house, opened read-only, whose
  `record_id` is null or names a record that no longer counts, and for which `permissions.share_cover` (Task 23)
  finds no allow at the time of the report. These are exactly the placements `share` under `enforce` would have
  answered with `needs-allow`. A placement with no `source_instance_id` is listed with them, as "no object".

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 10 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_cli.py engram/tests/test_permissions_cli_read.py
git commit -m "engram-permissions: gate, rebuild, uses, check, sweep, explain, report shadow, place show (P 14)"
```

### Task 28: `migrate`

**Files:**
- Modify: `engram/permission_cli.py`
- Test: `engram/tests/test_permissions_migrate.py`

**Interfaces:**
- Consumes: Tasks 10 to 13, 26; `policy_gen.load_groups`; `lighthouse_validation.load_owned_policy`.
- Produces: `engram-permissions migrate`, P 12.3 step 2 exactly: it creates the ledger with Andy as owner (channel
  `migration`), registers `person:andy` and his home, one agent per receiver named in the publisher policies' rules,
  in his home and acting for him, every house and each source store a share row resolves to as stores owned by Andy
  at `place:home/andy`, the groups of `groups.toml`, one collection per legacy audience with person-backed
  memberships, and one inside-home allow per collection (audience `place:home/andy` for commons, or `group:g`;
  `kinds: ["memory"]`, as R25 needs for a selector that names a collection; actions `recall`, `read`,
  `inject_context`; purposes `"*"`; no end; reason `legacy share`). Each row's source is opened read-only and checked
  by `content_digest`; a passing row gets `source_instance_id`, `record_id` and a first lane note (its lane and
  `created_at` read from that source, Task 11's `lanes`); a failing row is listed and left unmigrated. Before the yes
  it prints the count per audience, the unmatched rows, and each house other than the published one that lacks
  migration 029 (R27), and writes every row it will migrate to `ENGRAM_HOME/.engram/permissions-migrate-<at>.json`,
  printing the path;
  - the owner's handle comes from the Unix login, as for `init` (R24);
  - when a ledger already exists, `migrate` refuses (exit 1) and writes nothing: it runs once, before any ledger.
    Its message says that a row shared since can be shared again with `share`, which links it (Task 23), or added
    with `collection add`;
  - the published house is opened with `Storage` (not read-only, not plain `sqlite3`), so migrations up to 029 run
    on it before `migrate` fills `source_instance_id` and `record_id`. Every real house predates 029, and nothing
    else would add those columns before the daemon reads them.

- [ ] **Step 1: Write the failing tests**

```python
def test_u13_shares_become_one_collection_and_one_allow_per_legacy_audience(legacy_home, fake_tty):
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    s = Ledger.open(legacy_home).state()
    assert set(s.collections) == {"collection:andy/legacy-commons", "collection:andy/legacy-group-team",
                                  "collection:andy/legacy-group-lab"}
    assert len([r for r in s.records.values() if r.reason == "legacy share"]) == 3

def test_u13_more_than_256_shares_migrate(legacy_home_with_300_commons_shares, fake_tty):
    home = legacy_home_with_300_commons_shares
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    led = Ledger.open(home); s = led.state()
    members = [m for m in led.tables()["collection_members"] if m["collection"] == "collection:andy/legacy-commons"]
    assert len(members) == 300 and {m["backing"] for m in members} == {"person"}
    [allow] = [r for r in s.records.values() if r.reason == "legacy share"]   # one record, within the 256 bound
    house = share_rows(home / ".engram/instances/lighthouse/graph.db")
    assert len(house) == 300 and {r["record_id"] for r in house} == {allow.id}
    assert all(r["source_instance_id"] for r in house)

def test_u13_a_row_whose_source_fell_back_is_listed_and_refused_under_enforce(fallback_home, fake_tty, capsys):
    fake_tty.answer_the_printed_code(); main(["migrate"])
    assert "unmatched" in capsys.readouterr().out
    raise_to_enforce(fallback_home)
    assert fallback_row_never_served(fallback_home)                  # NO_LAYER: it has no object

def test_u13_in_shadow_the_legacy_path_allows_nothing_the_new_one_refuses_except_listed_rows(
        legacy_home_full, fake_tty, capsys):
    # commons, groups team and lab, both legacy policies, and one row whose source fell back (unmatched)
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    unmatched = unmatched_memory_ids(capsys.readouterr().out)
    assert len(unmatched) == 1
    raise_gate(legacy_home_full, "shadow")
    d = daemon_for(legacy_home_full)
    for receiver in receivers_named_in_policies(legacy_home_full):
        d.recall(receiver=receiver)
        for item in read_every_placement(d, receiver):
            row = receipt_for(legacy_home_full, receiver, item["memoryId"])
            legacy = all(c["verdict"] == "allow" for c in json.loads(row["cited"]) if c["kind"] == "legacy")
            if item["memoryId"] in unmatched:
                assert row["allowed"] == 0 and json.loads(row["refusal"])["code"] == "NO_LAYER"
            elif legacy:
                assert row["allowed"] == 1, (receiver, item["memoryId"])
    assert main(["report", "shadow", "--json"]) == 0                 # a reading command: no yes
    report = json.loads(capsys.readouterr().out)
    assert report["disagreements"] and {r["refusal"]["code"] for r in report["disagreements"]} == {"NO_LAYER"}

def test_migrate_opens_the_published_house_with_storage_so_029_runs(legacy_home_before_029, fake_tty):
    # every house built from migrations 001 to 028 only (house_before_029, Task 16)
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    house = legacy_home_before_029 / ".engram/instances/lighthouse/graph.db"
    assert {"source_instance_id", "record_id"} <= share_columns(house) and counter_row(house) is not None
    assert all(r["source_instance_id"] for r in share_rows(house) if r["memory_id"] not in UNMATCHED)

def test_migrate_refuses_when_a_ledger_exists(legacy_home, fake_tty, capsys):
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    before = ledger_bytes(legacy_home)
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 1
    assert ledger_bytes(legacy_home) == before and "already" in capsys.readouterr().err

def test_u13_each_source_store_is_byte_identical_while_source_instance_id_is_filled(legacy_home, fake_tty):
    sources = source_store_paths(legacy_home)            # .engram/graph.db and instances/why/graph.db
    before = {p: (p.read_bytes(), sorted(q.name for q in p.parent.iterdir())) for p in sources}
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    assert {p: (p.read_bytes(), sorted(q.name for q in p.parent.iterdir())) for p in sources} == before
    rows = share_rows(legacy_home / ".engram/instances/lighthouse/graph.db")
    assert rows and all(r["source_instance_id"] == instance_id_of(source_for(legacy_home, r)) for r in rows)

def test_u13_every_house_and_source_store_is_registered_at_andys_home_and_use_1s_holding_place_resolves(
        legacy_home, fake_tty):                          # 12.3 step 2; the re-check's RN6
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    s = Ledger.open(legacy_home).state()
    expected = {instance_id_of(p) for p in houses(legacy_home) + source_store_paths(legacy_home)}
    assert expected <= set(s.stores)
    assert {(s.stores[i].owner, s.stores[i].place) for i in expected} == {("person:andy", "place:home/andy")}
    house_id = instance_id_of(legacy_home / ".engram/instances/lighthouse/graph.db")
    receiver = receivers_named_in_policies(legacy_home)[0]
    u = Use(requester=f"agent:{receiver}", place="place:home/andy", obj=migrated_ref(legacy_home, "commons"),
            copy=f"store:{house_id}", action="recall", purpose="session-recall", at=now())
    assert Layer("place:home/andy", "consent") in required_layers(s, u)   # the holding place resolves
    assert decide(s, u).allowed                          # use 1's shape: a placement decided on its source ref, via h
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_migrate.py`
Expected: FAIL, `invalid choice: 'migrate'`.

- [ ] **Step 3: Implement `migrate`**

`default` names `ENGRAM_HOME/.engram/graph.db`, a name n `.engram/instances/n/graph.db` (P 12.3). Source stores open
with `Storage.open_read_only`. The published house is opened with `Storage`, so 029 runs, and is written only to fill
`source_instance_id` and `record_id`, inside one transaction (`Storage.transaction()`) after the ledger rows commit.
Other houses are read for their `instance_id` with `mode=ro` and are not migrated; those lacking 029 are listed
(R27). Collections are named `collection:<owner handle>/legacy-commons` and `collection:<owner handle>/legacy-group-<g>`
(R24); the tests set the login to `andy`.

The fixtures, in the test file: `legacy_home` is an `ENGRAM_HOME` with a default store `.engram/graph.db`, an instance
store `instances/why/graph.db`, the published house holding shares to `commons`, `group:team` and `group:lab` from
both, `groups.toml`, and a generated publisher policy naming two receivers; every row matches its source.
`legacy_home_with_300_commons_shares` is the same with 300 `commons` rows from the default store.
`source_store_paths(home)` lists the source stores; `source_for(home, row)` is the store a row's `source_instance`
names; `instance_id_of(path)` reads `meta.instance_id` with `mode=ro`; `migrated_ref(home, audience)` is the source
ref, `mem:<source instance id>/<layer>/<source id>`, of one migrated row of that audience.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of step 2. Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engram/permission_cli.py engram/tests/test_permissions_migrate.py
git commit -m "engram-permissions migrate: legacy shares to collections and inside-home allows (P 12.3)"
```

### Task 29: E1, the worked example end to end

**Files:**
- Test: `engram/tests/test_permissions_e1.py`

**Interfaces:**
- Consumes: everything above. Fixtures go through `Ledger.perform` (the county's stewards as actors, channel
  `terminal`, P 13), the daemon's `handle_frame` with E1's hand-written legacy policies (P 13, "Legacy layers"),
  `permissions.gluing`, `server._keep_check`, and `Uses.owner_list`.

- [ ] **Step 1: Write the failing test**

One test, `test_e1_andys_medical_history`, on one ledger, under `enforce`, with the clock set per step. Each step's
assertions carry the use's number in their message. The expected values, all from P 13:

| Use | Expected |
|---|---|
| 1 | copy h `store:<house id>`; recall returns m1 and m2, m3 filtered (`filtered` 1); delivery of m1 allowed; `until` and horizon 2027-01-31; cited R1, C1, H1, L1 for each of `recall`, `read`, `inject_context`; the annotation line of Task 20's test |
| 2 | read of m3 refused `NO_ALLOW` at `place:home/jenn`; item `content` null, no reason; agent view "not allowed"; owner list "m3: needs Jenn's yes"; clinic-3's stewards see Jenn's pseudonym, never `place:home/jenn` |
| 3 | `parks-planner` recall: no candidates; the receipt counts 3 filtered and names no subject |
| 4 | `sw-helper` recall: no candidates |
| 5 | `gluing` at Summer Wellness: the sentence of Task 8; no ineffective part |
| 6 | Rio Grande's widening is a proposal with P 13's words; Andy declines; tables unchanged but for the proposal |
| 7 | `collect` of m4 under G1 allowed, grant-backed; m4's `until` and horizon 2026-11-30 |
| 8 | 2026-11-10: R1′ `replaces` R1, same anchor, person-backed, `set_by agent:rio-grande`, `under_grant` G1, inside R1 |
| 9 | 2026-11-12: D1; m2's next decision has `until` and horizon 2026-12-01; Rio Grande's try on D1 is a proposal |
| 10 | 2026-11-20: G1 revoked; R1′ stays; m4 read `GRANT_INVALID` at `place:home/andy`, `recall`; from 2026-11-30 `EXPIRED` |
| 11 | 2026-12-01, no write since use 10: the cache ends at its horizon; m2 delivery `DENIED` at `place:home/andy`; m1 allowed |
| 12 | imprint of m1 refused `NO_ALLOW` at `place:home/andy` |
| 13 | 2026-12-15T00:00:00Z: m1 delivery `EXPIRED`; the sweep removes the placements; `_keep_check` of m1's text by `ph-coordinator` is refused when the clock is set just after use 1's delivery (2026-11-02), and passes at 2026-12-15 with no source subjects on the kept memory |
| 14 | `owner_list(collection="collection:andy/medical-history")` holds the allowed recall of m1 and m2, the allowed delivery of m1, the refused m3 read, the refused m2 read on 2026-12-01, the refused imprint and the expired read; each row shows place, agent, purpose, records and time; no filtered recall; public health's stewards see the same uses with Andy as a pseudonym, and the filtered counts |

- [ ] **Step 2: Run the test to verify it fails, then that it passes**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_e1.py`
Expected: it fails first only where the test itself is wrong (every part it uses exists by now). Show it failing once
by asserting use 1's `until` as 2027-02-01, seeing the message `use 1`, then restoring 2027-01-31. Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add engram/tests/test_permissions_e1.py
git commit -m "Permissions E1: the worked example of section 13, every step under enforce"
```

### Task 30: F1, the conformance fixtures

**Files:**
- Create: `engram/tests/fixtures/permissions/f1/*.json`
- Test: `engram/tests/test_permissions_f1.py`

**Interfaces:**
- Consumes: `State.from_tables`, `decide`, `decide_bulk`.
- Produces: one JSON file per fixture, `{"name", "tables": {<P 5.5 table>: [rows]}, "seq", "seq_at", "meta", "names",
  "cases": [{"use": {...}} or {"bulk": {...}}, "legacy": [{"name", "allows": [actions]}], "expected": {"allowed",
  "cited", "refusal", "until", "horizon"}]}`. Every use carries its copy h. The fixtures hold: E1's decisions for uses
  1, 2, 3, 4 and 9 to 13; one case per refusal code; the `EXPIRED`, `GRANT_INVALID` and `NOT_YET` record; a road and a
  trail answer use; bulk uses named and counted; and the trail evaluation on an imprint of P 6.4's last paragraph,
  with the operator's home layer written as ledger records over the imprint's collection, which a fixture of one copy
  can express. Expected values are written by hand from P 5 and 6, never generated by `decide`.

- [ ] **Step 1: Write the fixtures and the runner**

```python
FIXTURES = sorted((Path(__file__).parent / "fixtures" / "permissions" / "f1").glob("*.json"))

@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_f1_fixture(path):
    doc = json.loads(path.read_text())
    s = State.from_tables(doc["tables"], seq=doc["seq"], seq_at={int(k): v for k, v in doc["seq_at"].items()},
                          meta=doc["meta"], names=doc.get("names", {}))
    for case in doc["cases"]:
        got = run_case(s, case)           # decide or decide_bulk, legacy layers from the case
        assert {k: got.to_json()[k] for k in case["expected"]} == case["expected"], (path.stem, case.get("note"))

def test_f1_has_every_kind_of_case():
    kinds = {kind_of(c) for p in FIXTURES for c in json.loads(p.read_text())["cases"]}
    assert {"single", "road", "trail", "bulk-named", "bulk-counted", "imprint-evaluation"} <= kinds
    assert all("copy" in (c.get("use") or c["bulk"]) for p in FIXTURES for c in json.loads(p.read_text())["cases"])
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_f1.py`
Expected: PASS. To see the runner fail first, change one expected `until` in a scratch copy of a fixture and confirm
the failure names that fixture and case; then delete the copy.

- [ ] **Step 3: Commit**

```bash
git add engram/tests/fixtures/permissions engram/tests/test_permissions_f1.py
git commit -m "Permissions F1: conformance fixtures any implementation can run (P 15, 17)"
```

### Task 31: U24, the Pi budget

**Files:**
- Test: `engram/tests/test_permissions_pi_budget.py`, `engram/tests/test_permissions_pi_budget_fixture.py`

**Interfaces:**
- Consumes: `permissions.eligible_set` (Task 21), `decide_bulk` (Task 7).

- [ ] **Step 1: Write the tests**

```python
pytestmark = pytest.mark.skipif(os.environ.get("ENGRAM_PI_BUDGET") != "1",
                                reason="U24 runs on the station's Raspberry Pi 5 with ENGRAM_PI_BUDGET=1")

def test_u24_one_eligible_set_rebuild_within_2_seconds():
    s, placements = generated_world(placements=20_000, layers=43, records_per_layer=256)
    start = time.perf_counter()
    eligible_set(s, placements, requester=AGENT, place=PLACE, purpose="care-coordination", action="recall",
                 at=T("2026-11-02"))
    assert time.perf_counter() - start <= REBUILD_BUDGET_S

def test_u24_explain_on_the_largest_bulk_imprint_within_40_seconds():
    s = generated_world(placements=0, layers=43, records_per_layer=256)[0]
    bulk = BulkUse(requester=AGENT, place=PLACE, objects=derived_trails(100_000), copy=COPY, action="imprint",
                   purpose="trail-evaluation", at=T("2026-11-02"), named=False,
                   names=lambda trail: touches(trail, 512, universe=100_000))   # 51.2 million reads (XN3)
    start = time.perf_counter()
    decide_bulk(s, bulk, group=False)                                         # objects that don't group (R22)
    assert time.perf_counter() - start <= BULK_BUDGET_S
```

`generated_world` builds 8 subject homes, a requester chain and a holding chain of 16 places each, one restriction
layer and two legacy layers (callables that allow), with the record mix of R23: in each of the 41 ledger layers, 256
effective records, of which 32 pass the pre-filter for (`AGENT`, `PLACE`, the measured action, the measured purpose)
and 224 fail it, 56 each on `audience`, `requesters`, `actions` and `purposes`. Of the 32: 8 allows each name one of 8
collections of 2,500 memories, 8 allows each name a `memories` list of 512 refs, 8 allows name `lanes: ["work"]`
(every other memory has a `work` note), and 8 denies each name 64 refs outside the placed memories. Every memory has
the 8 homes as subjects (its store's owner and 7 co-subjects), so each decision meets all 43 layers, and every
placement is allowed, so none stops early. The rebuild's 20,000 placements are the 20,000 memories, one each. The bulk
test's world is built the same way over a universe of 100,000 memories (so its 8 collections hold 12,500 each), and
its 100,000 trails name memories from that universe, so `decide_bulk` makes at most 100,000 memory decisions for
`recall` (Task 7's memo) while it streams the 51.2 million touches. `touches` is a deterministic generator, never a stored list. A second file,
`tests/test_permissions_pi_budget_fixture.py`, runs in the default suite with
`test_u24_the_fixture_is_the_one_r23_names`: it builds the same layers with 200 placements, and checks the per-layer
counts (256 effective, 32 passing the pre-filter, the 8/8/8/8 split), 43 layers per decision, and that every
placement is allowed.

- [ ] **Step 2: Run them on the Pi**

Run: `cd engram && ENGRAM_PI_BUDGET=1 PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider --durations=0 tests/test_permissions_pi_budget.py`
Expected: PASS, 2 passed, with both durations printed. Without `ENGRAM_PI_BUDGET=1`: 2 skipped. If a budget fails, the
fix is in `eligible_set` or `decide_bulk`, never in the bound (P 15 calls these calibration hypotheses; a miss goes to
Rio Grande).

- [ ] **Step 3: Commit**

```bash
git add engram/tests/test_permissions_pi_budget.py engram/tests/test_permissions_pi_budget_fixture.py \
        engram/tests/permissions_support.py
git commit -m "Permissions U24: the Pi budget for a rebuild and for the largest bulk use (P 6.4, 12.2, 15)"
```

### Task 32: `engram/CLAUDE.md` and the whole suite

**Files:**
- Modify: `engram/CLAUDE.md` (a "Permissions" section before "## MCP Tools"; rows for `permit` and `permissions` in
  the MCP Tools table; four rows in "## Key Files")

- [ ] **Step 1: Write the paragraph and the rows**

The section says, in plain words: what the four modules do; that the ledger and receipts files live at their fixed
paths; that the gate is `off` until the owner raises it; and this rule, verbatim: "Agents never run, for the person,
any `engram-permissions` command that writes, such as `sign`, `allow`, `grant`, `migrate` or `gate`. Each needs the
person's own terminal yes." (P 7.6, 16; AN4.)

- [ ] **Step 2: Check the rule is there**

Run: `grep -n "never run, for the person" engram/CLAUDE.md`
Expected: one line.

- [ ] **Step 3: Run every new test file and the suites they touch**

Run: `cd engram && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_permissions_*.py tests/test_packaging.py`
Expected: PASS, with U24's two tests skipped, and `test_installed_wheel_starts_outside_checkout` counting 45 tools
(R29). Report the counts.

- [ ] **Step 4: Commit**

```bash
git add engram/CLAUDE.md
git commit -m "engram/CLAUDE.md: permissions, its tools and files, and the rule that agents never run its writes"
```

---

## Verification before merge (station law section 2)

Section 2 merges a branch only when a fresh reviewer has approved it in the room and its test suites pass on the Pi.
The reviewer is a fresh agent started on the Pi that took no part in writing the branch. It runs these from the build
worktree, `/home/andy/superyak/.worktrees/permissions-core`, and posts its verdict whole in the room ("Superyak: city
of AI", 39fd79, or the room that replaced it), with the branch head and every result below. It never @mentions a
ship.

1. **Up to date with main, by a merge, never a rebase.**
   `git merge-base --is-ancestor main HEAD || git merge --no-ff main -m "Merge main into permissions-core"`
2. **The diff is what the plan says.** `git diff --stat main...HEAD` lists only the files in "File Structure" and the
   note under it.
   `git diff --name-only --diff-filter=MDR main...HEAD -- engram/tests/` prints exactly `engram/tests/test_packaging.py`,
   the one exception R29 allows, and no other existing test file. That file's change is one line:
   `git diff -U0 main...HEAD -- engram/tests/test_packaging.py | grep '^[-+][^-+]'` prints exactly
   `-assert len(server.mcp._tool_manager.list_tools()) == 43` and `+assert len(server.mcp._tool_manager.list_tools()) == 45`.
   `git diff --check main...HEAD` prints nothing.
3. **The engram suite on the Pi, capped** (engram's CLAUDE.md, "Testing"):
   `cd engram && LIGHTHOUSE_REPO="$(cd .. && pwd)/lighthouse" PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked --extra dev python -m pytest -q -ra --tb=short -p no:cacheprovider`
   Expected: every test passes except any that also fail on `main` at the merge base. Run the same command on a
   checkout of the merge base first, and report both counts and the names of any failures. The interop tests skip on
   the Pi, which lacks the built Lighthouse packages.
4. **U24 on the station's Pi 5** (this Pi): the command of Task 31, step 2. Revision 8's file holds 16 tests (the
   final review's I3). Expected: 16 passed. Three are timed: one eligible-set rebuild of 20,000 placements within 2 s,
   the same with sharing off within 30 s, and the largest bulk `imprint` within 300 s. Eleven measure one operation's
   peak in a process of its own, each under 512 MiB of `VmHWM` plus `VmSwap` (state, eligible, bulk, perform-allow,
   perform-collect, rebuild, check, uses-owner, uses-place, fold, migrate); two of them are also timed, the eligible
   probe within 6 s and the bulk probe within 300 s. Two measure the daemon's peak under 512 MiB, on the reference
   ledger and at the records bound. So five time budgets (2, 30, 300, 6 and 300 s) and 13 peaks. Report every
   duration and every peak with its swap (`peaks.jsonl` holds them). Without `ENGRAM_PI_BUDGET=1`: 16 skipped.
5. **The peer suite** (unchanged by this branch; section 2 names the suites):
   `cd peer && PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet -p MemoryMax=4G -p MemorySwapMax=0 uv run --locked python -m pytest -q -p no:cacheprovider`
   Expected: as on `main`.
6. **Off by default, checked by hand.** In a fresh directory:
   `cd engram && D=$(mktemp -d /var/tmp/perm-off.XXXX) && uv run --locked --extra dev python -c "import pathlib, permission_ledger as L; print(L.effective_gate(pathlib.Path('$D'), []))"`
   Expected: `Gate(mode='off', cause=None)`. Then `rm -r "$D"`.
7. **Read the safety-critical code against the spec**, at least: `decide`'s order and codes (P 6.5), `authorize`
   against P 7.1 and 7.6, `_allowed_audiences` against P 12.1's daemon rule, `effective_gate` against P 12.3, the
   agent's refusal views against P 9.2, and the `remember` guard's reply against P 10.
8. **Not a Pi suite.** `make check-integration` needs Node.js 24 and pnpm 11.20.0; the Pi has Node 18.20.4 and no pnpm
   (checked 2026-10-25). It must pass in CI or on the Mac before the merge, and its result is posted with the verdict.
9. **The shared embedder on small-hardware daemon machines (gate G0; spec 12.2; the final review's I4; R37).** The
   lighthouse daemon does not refuse to start when `ENGRAM_EMBEDDER_SOCKET` is unset (`engram/lighthouse_daemon.py`,
   `main`): it embeds in process through `create_embedding_provider()` and logs a warning that names
   `scripts/superyak-embedder.service` and says the model is loaded in this process. So the Mac, which has no shared
   embedder, keeps starting. On every small-hardware machine of Andy's that runs the daemon (the Pi), someone on that
   machine checks both before the merge, so the model is never loaded twice there:
   `python3 -c "import json, pathlib; print(json.load(open(pathlib.Path.home() / '.config/superyak/runtime.json')).get('embedder_socket'))"`
   prints a socket path, not `None`; and `systemctl --user is-active superyak-embedder` prints `active`. The verdict
   names each such machine and what it showed. A machine without the socket still runs, with the model in the
   daemon's own process and the warning in its log.

The merging ship then merges as section 2 says. This branch changes only engram, which no Pi service runs (the Pi's
user units on 2026-10-25: `superyak-door`, `superyak-lighthouse`, `superyak-odo`, `superyak-ship`,
`superyak-wormhole`), so no Pi service restarts. If that has changed, section 2's restart and check apply.

## Gates (for later)

None of these is run by this plan. Each waits for the person named.

| # | Gate | Why it waits |
|---|---|---|
| G0 | Before G1 and G2: every small-hardware machine (the Pi) that runs the engram lighthouse daemon has `embedder_socket` in its `~/.config/superyak/runtime.json` and runs the embedder unit (`superyak-embedder`), checked on each such machine as Verification step 9 says. Other machines, the Mac among them, may run without it (R37). | Spec 12.2: "before the daemon's refusal ships, every machine that runs the daemon has that key and runs the embedder unit". R37 took the refusal out of the code, so a machine without the socket still starts (the final review's I4). On the Pi a second model in the daemon's process would not fit beside the service's (spec 15), so the socket stays a deploy item there. Andy's machines, so Andy or an agent on each one checks. |
| G1 | The merge itself, under section 2 (above). | Station law. |
| G2 | Engram servers in running Claude Code sessions, and any engram daemon on Andy's machines, load the new code only at their next start. Nothing restarts them. | Nothing live here. With no ledger they behave as today except the two fail-closed changes, and a daemon starts only where G0 holds. |
| G3 | `engram-permissions migrate` on Andy's machine, the one whose `ENGRAM_HOME` holds the published house the daemon serves, after he checks that the words of the yes name `person:andy` (R24), then `gate shadow`, then reading `report shadow`. Before `gate shadow`, each house that `migrate` and `gate` list as lacking 029 is opened once by its own engram server at its next start (G2), or it serves nothing under `shadow` (R27). | Andy's own terminal yes (P 7.6, 12.3). No agent runs them (Task 32's rule). |
| G4 | Andy's home grant for his own agents (P 12.3 step 4), and his answer on agent shares at home lasting at most 720 hours. | Section 19, "Agent shares at home under `enforce`". |
| G5 | `gate enforce`. | Andy's yes, after G3's report and G4; and his answer on whether the terminal yes is enough at home (P 19). |
| G6 | The imprints plan's build: `import-receipts`, `pending(m)`, `cosubjects(m)` and D37 read this plan's files. `Ledger.cosubjects(ref, at=None)` now follows copies (M6: `subjects_of` less the default subject), builds a State per call and raises `RuleError` on a malformed ref ("What the other plans use"), so the imprints plan's Task 8 assertion `led.cosubjects(copy) == frozenset()` becomes `{"person:jenn"}` at its rebase. | Build order: imprints after this merges. |
| G7 | The trails step 1 plan's build: `laid_by` reads `stores.owner`. | Build order: trails after imprints. |
| G8 | YN6's wording in P 9.1 item 1 ("per action and purpose") in the spec's next revision. | This plan edits no spec; the code already counts per (action, purpose). |
| G11 | R10's departure in the spec's next revision: P 6.3 item 4 and section 10 say that the `remember` guard decides `imprint` from ledger layers only, ignoring any legacy `imprint` rule, allow or deny, and why (today's generated files and E1's give no `imprint`; both legacy layers already allowed the delivery under `enforce`; every person the memory is about still says yes in the ledger). | This plan edits no spec. The re-check confirmed R10 on this condition. |
| G12 | The spec's next revision records the final review's changes that its text does not hold: R34's three bounds in section 15; R36's `audience` entry of a shadow receipt's `cited` in 9.1; and, in 15's "Measured", that the probes' `MemoryMax=512M` was not enforced on the station's Pi (no memory controller), that the peaks are `VmHWM` read directly, and that the probe now records `VmSwap` beside it (M10). And, in 12.2's "Modes", a departure (the final fix wave's concern 5, M3): under `shadow`, an item one of whose placements has no object gets no receipt, as an item with no object at all, while the legacy path still delivers it; `report shadow` lists that placement ("no object") instead. 12.2 says "both decisions go to the receipts", so its next revision must say so. | This plan edits no spec; spec changes need their own reviewer. |
| G13 | `engram/CLAUDE.md`'s Permissions paragraph names R43 beside the two fail-closed changes it lists: with a ledger, under every gate, `shares` and `unshare` are for an agent acting for the ledger owner. | This wave edits no CLAUDE.md; the controller or Andy updates it. |
| G9 | Step 2's items: the browser yes and station signatures (P 14 step 2), what a subject sees of another subject's home (BS3), which item of `Req` holds a station ceiling (XN6), a copy held away reading lanes from the imprint (P 5.3), and the `remember` guard seeing deliveries decided elsewhere (P 10). | Later specs. Not built here. |
| G10 | Section 19's open questions: the license, one permission an agent may set alone, what the county sets, pseudonyms, the two departures from principle 5, who decides in the county steps, and memories that mention other people. | Andy's. Each spec keeps its default. |

## Self-review: every component and test to its task

| Spec item | Task |
|---|---|
| Component `engram/permissions.py` | 1 to 9, 20, 21, 23 (`share_cover`) |
| Component `engram/permission_ledger.py` | 10 to 13, 16, 17 |
| Component `engram/permission_uses.py` | 14, 15 |
| Component `engram/permission_cli.py` and `pyproject.toml` | 26, 26A, 27, 28 (py-modules: 1, 10, 14, 26) |
| Component `engram/lighthouse_daemon.py` | 19 to 21 |
| Component `lighthouse_client.py`, `neighbors.py`, `context_lighthouse.py` | 22 |
| Component `sharing.py`, `server.py` | 17, 18, 23 to 25 |
| Component `storage.py` | 16, 17 |
| Component `federation.py` | 25 |
| Component `policy_gen.py` | 18 |
| Component migration `029_share_identity.sql` | 16 |
| Component tests and `fixtures/permissions/` | 1 to 31 |
| Component `config.py` | 18 |
| Component `engram/CLAUDE.md` | 32 |
| PT1, PT4 (nesting), PT5, PT7, PT8, PT3 | 5A (PT4 dominance: 2; PT7 copy chain made: 11) |
| PT2 | 12 |
| PT6 | 4 |
| PT9, PT11 | 8 |
| PT10 | 6 (insertion order), 10 (replay) |
| PT12 | 6 |
| U1 | 5 |
| U2 | 1 (grammars), 2 (places, retiring a place), 11 (joint place, one place per agent, retiring a person) |
| U3 | 9 (selector sizes in 1) |
| U4 | 9 (pure table), 12 (through the ledger) |
| U5 | 11 (the self-claim in Andy's list: 15) |
| U6 | 4 (lanes), 17 (a failing first note) |
| U7 | 12 |
| U8 | 10 (log chain), 13 (home rules not exported), 14 (writing), 15 (views) |
| U9 | 10 (read-only bytes), 20 (enforce, shadow, frame `at`, refused items), 21 (cache), 22 (client), 23 (20,001st) |
| U10 | 22 (receipt short form also in 1) |
| U11 | 23 |
| U12 | 24 |
| U13 | 28 |
| U14 | 9 (words), 12 (proposals), 26A (`sign` prints the selector) |
| U15 | 8 (stewards, cap), 11 (rerun after a registry change), 27 (`check`) |
| U16 | 13 (ledger and houses), 16 (houses made later), 18 (config section), 19 (daemon over every served house, no-ledger suites), 23 (closed `share`, a config that fails to parse), 27 (only the yes moves the gate, no published house) |
| U17 | 25 |
| U18 | 12 (R26 registry proposals), 23 (MCP tools), 26 and 26A (terminal) |
| U19 | 6 |
| U20 | 4 (audiences), 11 (principal, second place) |
| U21 | 5 |
| U22 | 7 (decisions, the imprints agreement with two owners), 14 (receipts) |
| U23 | 9 (mapping), 18 (policy_gen, `share` argument), 19 (never served below `enforce`) |
| U24 | 31 |
| U25 | 4 (readings), 17 (a failed `UPDATE`, a crash) |
| U26 | 1 (prefixes), 26A (the CLI) |
| U27 | 14 |
| U28 | 5 |
| E1 | 29 (use 1's line also in 20, use 5 in 8, use 11 in 21) |
| F1 | 30 |
| Review Focus 1 to 5 | 20, 19, 21, 1, 10 |
| Carried YN6, XS2, XM1, XN3, AN4, AN5 | 15, 14 and 15, 5 and 7 (`outside`), 31, 32, 18 |
| Plan review MF1, MF2 | 22 (`_version` leaves out `permission`), 17 (`after_outcome`) |
| Plan review SF1 to SF14 | 5 and 7; 19; 19; 16, 20, 21, 27, 28 (R27); 12, 13, 23, 26A (R26); 23 (R28); 11; 23; 21; 7 and 31 (R23); 4, 15, 20, 22, 24, 25, 28 and the fixture builders of 11, 23, 25; 5A and 26A; 23; 20 and R10 |
| Re-check RM1 (the tool count) | 23 (R29), Global Constraints, Verification step 2 |
| Re-check RM2 (P 17's placeholders) | 2 (U2 depth and count), 4 (U6 work to personal), 14 (U8 receipts chain, U22 five roads), 15 (U8 pseudonyms, no filtered counts), 23 (U11 permit, U11 unshare, U9 20,001st), 24 (U12 last share row), 28 (U13 >256, bytes unchanged, registered at home) |
| Re-check RM3 (Amy) | 11 (`county_ledger` registers her), 5 (U28: `NO_ALLOW` registered, `NO_LAYER` not), 25 |
| Re-check RS1 to RS7 | 20 (R30); 13, 23, 26A, 27 (R26, `gate_plan`); 21 (R31); 16; 13 and 19 (R32); R10 and G11; 20, 25, 12, 12 |
| Re-check nits, and the two other sole tests | 17, 22, R1 and 13, R24 and G3, 13 and 19 (`busy_ms`), 25 (`keep_world`), 2 (`World`), 5A, R11 and 25, "What the other plans use"; 24 (startup fold), 27 (`explain`); R33 (place views) |
