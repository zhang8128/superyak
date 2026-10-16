# Survey: spec A step 5 (directs) against main at 25ca91e and the charter plans

Date: 2026-10-16. Read-only survey, the input for the step 5 spec. Nothing in the repository was changed except this
file.

References:

- "spec A" is `docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md`; "A:n" is its line n.
- "step3:n" is the step 3 design, `2026-10-15-grants-step3-design.md`; "survey3:n" is its survey,
  `2026-10-15-grants-step3-survey.md`.
- "step4:n" is the charter spec, revision 3, `2026-10-15-charter-step4-design.md` at 9f9683e (branch charter-spec);
  "survey4:n" is the charter survey at 86d2919.
- "4a:n" is the 4a plan, `docs/superpowers/plans/2026-10-15-charter-4a-station.md` at 9cbe58f (branch charter-4a);
  "4c:n" is the 4c plan, `2026-10-15-charter-4c-acceptances.md` at e1dd55f (branch charter-4c). Neither is merged:
  main has no `charter.py` or `acceptances.py`.
- "fresh:n" is `2026-10-15-owner-mention-fresh-design.md`; "status:n" is `2026-10-10-ship-status-and-claims-design.md`;
  "breakouts:n" is `2026-10-11-breakout-rooms-design.md`; "law:n" is `docs/station-law.md`.
- Code paths are relative to the repository root, at main 25ca91e (grants step 3 complete, plus the grants
  follow-ups).

Tags used in section 2: **[S3]** marks a change to an invariant step 3 built or ruled (its G or S number);
**[S4]** marks a change to an interface the 4a or 4c plan builds.

---

## 1. What step 5 must deliver, by spec A's own words

Build order item 5 (A:487): "Directs. Acts from sessions and from runs (run tools), hops, confirmation, and the breaker
with its notice." Each step "gets its own plan, reviewed by a fresh reviewer agent before it is built" (A:489). Steps 3
and 4 moved more into it (1.9 to 1.13 below). The roadmap has no item for step 5 yet: it ends at 2.3, the charter
(`docs/superpowers/plans/2026-10-12-station-roadmap.md:95`).

**1.1 Directs.**
- Concept: "a structured request from a ship for another ship to do one task in one room" (A:54). Acts "are the only
  way authority moves. Text never carries it" (A:20; Q2 at A:29).
- Table `directs(id, issuer_id, target_id, room_id, message_id, grant_id, ticket_id, hops, status, created, expires,
  decided_by, decided)` (A:216-219).
- `POST /api/directs {target, room, task, grant_id?, ticket_id?}` (ship key), in order (A:222-240):
  1. both ships are room members; `task` is 1-20,000 characters (A:224);
  2. pick the grant: `grant_id` if given (held by the issuer, covering this target and room), else the oldest valid
     grant the issuer holds that covers them; the same owner still needs an owner-signed root (A:225-227); with
     `ticket_id`, the confused-deputy rule, and the ticket checked again: running, its chain valid, no breaker on its
     ship; "A revoked chain stops a running build's acts at once" (A:227-229);
  3. the breaker (A:233);
  4. post `Direct to <Target name>: <task>` as the issuer, recording no mentions (A:234-235);
  5. record it: `pending` if a link says `confirm: each`, else `ready` (A:236-238);
  6. once `ready`, insert a `mentions` row for the target; `GET /api/mentions` items gain `direct_id` (A:239-240).
- Response `{id, status, message_id, confirm_url?}`; no valid grant: 403, nothing posted (A:242-243).
- Plurality: direct ids are local UUIDs, exported as `<station peer id>:<id>` (A:366-367).

**1.2 Acts from sessions.**
- The station MCP server gains `station_direct(target, room, task, grant_id?)`, `station_grant(parent_id, grantee,
  targets, rooms, hours?, budget?, depth?, confirm?)` and `station_grants()` (A:273-275). (`station_draft_instructions`
  is there since step 2.)
- "Every act also records a session label the client declares, as provenance only, never authority" (D7, A:36;
  Concepts A:57-59: at most 100 characters, one line, shown for the audit).
- Sessions "issue directs and grants, so they must always load the law" (A:342-349; built in step 2).
- Hops 0 for a direct from a session (A:230).

**1.3 Acts from runs (run tools).**
- Builder runs get a second MCP server named `ticket`, so the `mcp__station` deny doesn't cover it; builder settings
  allow exactly `mcp__ticket__station_direct` and `mcp__ticket__station_grant`. It runs as `run_agent.py run-tools
  --config … --ticket <id>` and adds `ticket_id` to every call. Read-only runs get no station tools. MCP servers run
  outside the sandbox, so the key stays unreadable to the model (A:275-279; the watcher's "builder runs also get the
  run tools", A:325).
- Acts carrying `ticket_id` are accepted only while that ticket is `running`, is `build`, and belongs to the calling
  ship, and are checked again as in section 3 (A:316-318). The confused-deputy rule: the ticket's root person is the
  chain's root person (A:192-193). Security: "builder runs can spend only their own root's chains" (A:401-402).
- Step 3 left this to step 5: "Step 5 adds the refusal of acts that carry a revoked chain's `ticket_id`" (step3:310).

**1.4 Hops.** "A direct records `hops`. That is 0 when issued from a session, and the issuing ticket's `hops + 1` when
issued from a run. A direct whose `hops` would reach `max_depth` is refused. This bounds direct → run → direct relays,
which grant depth alone does not, because each hop can spend a different chain" (A:230-232). Tickets record `hops`,
"the direct's hops, or 0" (A:286, A:309).

**1.5 Confirmation (`confirm: each`).**
- `confirm` is `none` or `each` (A:171); a child keeps `each` if the parent has it, and `each` is allowed only on a
  grant to a ship (A:188).
- A direct under a chain with an `each` link waits as `pending` for "that link's issuer (a person)" to confirm in the
  browser within 600 s, or becomes `expired` (A:236-238; A:392).
- `GET /api/directs/pending` (person); the view `/#direct?id=` shows the full task (never cut), target, room, issuing
  ship and its machine, the whole chain with each link's scope, expiry and budget left, and whether a run started it;
  "Confirm this task" and "Decline", no batch action; `POST /api/directs/{id}/confirm` and `/decline` (person, CSRF)
  only for the issuer of the `each` link, while pending and unexpired; the chain is checked again before `ready`; no
  ship can post to the screen (A:245-251).
- Ticket basis 3 refuses chains with an `each` link (A:301-303): built in step 3 (`tickets.py:163`).

**1.6 The breaker and its notice** (A:253-271).
- Per-ship limit: `directs_per_ship_hour` (10) directs in the last hour, then 429; trips nothing, clears itself.
- `breakers(id, ship_ids, reason, created, reset_by, reset)`; a trip refuses the direct that tripped it when:
  the station issued more than `directs_per_hour` (30) in the last hour (covering only ships that issued more than a
  quarter of them); one issuer sent the same normalized task to `same_task_ships` (3) or more ships in an hour; a task
  holds a normalized run of `echo_chars` (200) or more that also appears in a message the issuer received in the last
  hour, text by the chain's root person exempt.
- Known limit: "The content checks catch copying, not paraphrase" (A:266-267).
- While a breaker covers a ship, it can issue neither directs nor grants, and tickets for directs it issued give
  `read`. Only an admin resets it (`POST /api/breakers/{id}/reset`, CSRF, or `superyak-peer station-breaker-reset`);
  every ship key gets 403. `station-notices` gains `breaker-<id>`, which Odo posts in Ops (A:269-271).
- Error handling: after a trip later directs are refused at once; directs already `ready` give `read` tickets
  (A:394-395). Policy section `breaker` (A:91); no-charter defaults 10, 30, 3, 200 (A:384-385).

**1.7 Ticket basis `direct`.** Rule 1, ahead of owner and grant: "a `ready` direct for this message and ship, with a
valid chain, no breaker on the issuer, and budget left. The direct becomes `used`" (A:297-298). It counts toward
`builds_per_ship_per_day` with grant builds (A:306-307), charges one `budget_uses` row per link (A:307-308), records
`chain`, `root_id`, `hops` (A:308-309), and gets the footer `Builder for Andy, via Serenity · grants #a1b2 > #c3d4 ·
charter r3` (A:310-311).

**1.8 Delegation (the `grant` act).** Moved here by step 3's S2 (step3:60, step3:72).
- `POST /api/grants/delegate {parent_id, grantee, targets, rooms, expires, budget, depth, confirm, ticket_id?}` (ship
  key), refused (403) unless: the parent's chain is valid; depth > 0 and every action in `delegable`; the child is a
  subset in every field (default expiry `agent_grant_default_hours`, lower depth, budget no larger, `each` kept); the
  grantee is in the grantee set; another owner's ship accepts first (`POST /api/grants/{id}/accept`); `ticket_id`, if
  given, names a running builder ticket of the caller with the same root person (A:181-193).
- Validity walks every link (A:195-203); a ship revokes grants it issued (`POST /api/ships/me/grants/{id}/revoke`,
  A:205-207); `GET /api/ships/me/grants` lists held and issued grants with validity and budget left (A:209-211).
- D1 "Agents grant agents" (A:30), carried into the law: "Ships holding a grant may pass narrower grants on to other
  ships" (law:26-27).
- Also moved by S2: ship grantees, acceptance, `confirm: each`, the `ticket_id` rule, the ship routes, both tools, the
  status line and the session label on grants (step3:72).

**1.9 Charter roots** (moved by C2, step4:44; amendment 14, step4:117-118). Root clauses `{owner, grantee, targets,
rooms, budget, depth, expires_hours}` (A:89-90), at most 50 (A:94), owner the signer or an accepter, targets the
owner's ships (A:95-96); a root added or widened is a widening (A:98-99), listed at an owner's first acceptance
(A:105-106), and applies only to owners who accepted (A:110); a pinned old revision's roots are superseded (A:116-118);
materialized as rows with `charter_layer_id` and `charter_revision` at activation or acceptance, revoked `superseded`
when replaced (A:176-179); valid only while the revision is active and accepted (A:197).

**1.10 `agent_grant_default_hours`** (A:86, A:187, A:384): the child's default expiry. Bounded and stored by 4a, read by
nothing until step 5 (C11, step4:53; Data, step4:191).

**1.11 `grantees.ships_of`** (A:88): the ships of the listed people may hold grants; checked at delegation (A:189) and
at every validity check (A:200-201). Stored by 4a, no reader (step4:196); under a restricted set 4a's validity refuses
every ship grantee, and "step 5 must change it" (C16, step4:58).

**1.12 `delegable`** (A:86, A:94-95, A:186, A:200): checked by 4a for links a ship issued, with no effect until a ship
issues one (C16, step4:58; R12; 4a P8 at 4a:121).

**1.13 Footers for chains and the display name.** `grants #a1b2 > #c3d4` for a chain (A:311; step3:296-297). The
display-name spoof in footers goes to step 5 (C10, step4:52), and "A block's 'signed by <name>' shares it, and step 5
should fix both" (step4:808-809).

**1.14 Status.** `superyak-agent status` prints "the grants the ship holds with their budget left, and any breaker on the
ship. The web app's Ships section shows the same" (A:360-362); step 4 left its grants and breaker parts here (C29,
step4:71; step4:810).

**1.15 Compatibility.** The ship-key allowlist grows by directs, grants delegate and `ships/me/grants` (A:379-380). "An
old watcher (without tickets) keeps today's local rule ... A direct to its ship arrives as an ordinary mention from a
ship, so it runs read-only. Nothing widens" (A:381-382).

**1.16 Security.** Known residual risk chosen by Andy: "a steered session or builder run can still issue directs and
grants within its chains", bounded by depth, budgets, expiry, the grantee set, the breaker and branch-only builds
(A:403-406). Step 3: "Step 5 must say how that limit applies to grants held by ships" (step3:359-360), the many-ships
rule that per-ship keys "separate provenance, not authority" (survey3:190-194).

**1.17 Tests that fall in step 5.** Testing 1's acts "ready direct, pending direct, declined direct" (A:417-420);
Testing 3's ship-key 403 on "confirm a direct" and "reset a breaker" (A:435-436); Testing 6's subset property, budget
across a chain, depth, "A run can't use a grant with a different root", "A running build's act is refused once its
chain is revoked", "A direct → run → direct relay is refused at `max_depth` hops", the grantee set and acceptance, "N
similar directs trip the breaker, and the next ticket for those ships gives `read`", the reset 403 and the noisy ship's
429 (A:451-467); the fake station "extended with tickets, directs and instructions" and the browser test of "the direct
confirmation view (full text and one task per tap)" (A:470-473).

---

## 2. Where each would go in today's code

### 2.1 What exists to build on

| Item | Evidence | Today |
| --- | --- | --- |
| Ticket columns | `peer/superyak_peer/tickets.py:20` | `direct_id TEXT` (no FK; there is no `directs` table) and `hops DEFAULT 0` exist; the insert (`:109`) sets neither. |
| Ticket decision | `tickets.py:125-142` | Owner, then grant. `:133` returns `read` for any author who is not a person, before any rule could look for a direct. Docstring `:1-3`: "Step 5 adds directs to the same decision." |
| Grant spending | `tickets.py:144-166` | Oldest valid grant by grantee = author; room cover by `_rooms_back` (`peer/superyak_peer/grants.py:155-163`); the root issuer must be in the room (`:163`, step 3's S5); `each` chains skipped (`:163`). |
| Re-send re-check | `tickets.py:91-99`, `:168-182` | `_grant_lapsed` re-checks a running `grant` ticket's chain (validity without budget, root issuer in room); 409 with `keep=True`. Only for basis `grant` (`:94`). |
| Budget per link | `tickets.py:112-113` | One `budget_uses` row per chain link, in the ticket's transaction (G16). |
| Per-ship cap | `grants.py:89-93`; `tickets.py:153` | Counts `basis='grant'` build tickets only. |
| Footer, source | `tickets.py:46-64`, `:255-270` | `_via_name` is the grantee of the chain's last link (for a direct, the issuing ship: right as is). `_footer` already writes `grants #a > #b` for several links (`:64`) but returns `''` unless the basis is `grant` (`:62`); `_sources` adds `via_name` only for `grant` (`:261`). |
| Chain walk, validity | `grants.py:72-82`, `:95-122` | Walks parents with a seen set; checks revoked, expired, lifetime, `len(chain) > max_depth`, grantee set, budget, root issuer owns every target. G9 was written "so step 5 only adds links" (step3:204), and step 3's tests already hand-make two-link chains (`peer/tests/test_grant_tickets.py:396-443`). |
| Grant columns, signed record | `grants.py:11`; `peer/superyak_peer/signatures.py:126-144`; `peer/superyak_peer/identity.py:79-81` | `parent_id`, `depth`, `confirm`, `charter_layer_id`, `charter_revision`, `follow` exist and are signed, so a child or a charter root signs with no new keys; later columns stay outside the record (S7 at step3:77; step3:180-184). |
| Making a root | `grants.py:249-282` | Person grantee only (`:249-256`), the caller's own ships (`:258-266`), `depth` 0, `confirm` 'none', `actions` `["direct"]` (`:60-70`). No `depth` or `confirm` in the body. |
| Visibility, revoke | `grants.py:124-134`, `:284-306` | Grantee, any issuer in the chain, or a target's owner. The grantee's owner (for a ship grantee) is none of these. |
| Policy | `grants.py:54-58` | No-charter defaults, read through one function; no breaker keys. 4a replaces it with `flat_policy(self._policy_in_force(db))` (4a:2242-2266). |
| Ship-key routes | `peer/superyak_peer/app.py:104-109`, `:232-313` | `ship_member` per route; `/api/ships/me/*` holds tickets, instructions, drafts, watch, breakouts, briefs. `peer/tests/test_ships.py:29-46` samples routes that must 403. |
| Person routes | `app.py:88-97`, `:489-510` | `current_user` refuses ship keys and checks CSRF on writes. |
| Session label source | `peer/superyak_peer/presence.py:15`, `:28-37`; `agent/superyak_agent/station.py:29-37`; `agent/superyak_agent/mcp.py:173-181` | `X-Superyak-Session`, `[A-Za-z0-9._:-]{1,100}`, sent by every MCP call; but each one also writes a presence row (`presence.py:41-59`), and "a run sends none" (`:78-79`). |
| Mentions | `peer/superyak_peer/ships.py:318-330`, `:339-356` | Recorded from `@username` in the body; the route returns `author.username` and no `direct_id`. |
| Posting | `peer/superyak_peer/chats.py:69-109` | Always records mentions (`:98`), applies the 30-a-minute ship budget (`:89`) and the 20,000-character cap (`:78`). `_post_as_system` (`peer/superyak_peer/system_author.py:33-38`) is the one in-transaction post with no mentions, for the system author only. |
| Message kinds | `system_author.py:11`, `:55-58` | `CHECK (kind IN ('claim','notice'))`; a kind row means never answered and never federated. |
| Station notices | `ships.py:380-393`; `agent/superyak_agent/watch.py:293-316` | Access, share and docking notices; Odo posts each once in the newest local room titled Ops. |
| Breakouts | `peer/superyak_peer/breakouts.py:1-3`, `:30-31`; breakouts:142-143, :175-176 | Ships-only rooms. S11 and R14: directs are refused in breakouts and `"*"` excludes them; step 3's `_grant_rooms` and `_spendable_grant` already refuse breakout ids. |
| Watcher | `watch.py:123-216` | Asks a ticket per mention, runs in its mode, never higher (`:195`), posts the ticket's footer (`:201`). A mention whose author is a ship spends the 5-an-hour ship budget per room first (`:15`, `:130-131`, `:269-274`); over it, a pause note that `@`-mentions the author (`:283-285`). |
| Runs | `agent/superyak_agent/runs.py:14-17`, `:69-75`, `:119-140` | One MCP config for both modes, passed once (`agent/superyak_agent/__main__.py:140-141`), from `install.run_mcp_config`, which keeps station tools "deliberately absent" (`agent/superyak_agent/install.py:40-47`). Both modes deny `mcp__station`. |
| Builder sandbox | `team/superyak_team/workers.py:311-320`, `:336-339` | Denies `mcp__station`, file reads of every key file under `~/.superyak`, and OS reads of `$HOME`; shared with team mode. |
| MCP server | `mcp.py:162-197`, `:511-574`, `:589-638` | A `TOOLS` table, one ship key, the D7 claim guard on every call (`:641-654`). No grant or direct tool. |
| Agent status | `__main__.py:217-225` | The ship line and its binding layers; no grants or breaker line. |
| Fake station | `agent/tests/conftest.py:415-449`, `:472` | Tickets (owner only), instructions, finish; every unknown route 403. |
| Grants page | `peer/superyak_peer/static/app.js:685-760` | Person grantees only; `given` is every grant the caller doesn't hold (`:758`), each with Revoke (`:746-750`). |
| Restore | `peer/superyak_peer/backups.py:380-387`, `:506-560` | Grants revoked or missing in the replaced file are revoked; budget uses added. Nothing about directs or breakers. |

**Nothing else exists.** A grep for `direct`, `directs`, `breaker`, `hops` and `run-tools` over the peer and agent
packages finds only grants' `direct` action (`grants.py:58`, `:67`, `tickets.py:159`), the ticket columns above (and
`hops` in the ticket's answer, `tickets.py:72`), and docstrings.

### 2.2 Requirement by requirement

**Directs (station)** — a new module (`directs.py`, a mixin on `Store` at `peer/superyak_peer/db.py:50`, its schema
joined at `db.py:64`, listed in `peer/pyproject.toml`'s two lists beside `grants.py` at `:69` and `:160`).

| Requirement | Build on | Missing | Change |
| --- | --- | --- | --- |
| `directs` table (1.1) | `tickets.py:20` (`direct_id`, `hops`) | The table; a session label column (gap 18) | Additive |
| Membership, task size | `issue_ticket`'s membership check (`tickets.py:84`) | Both ships members; room local, current, not a breakout (breakouts R14) | Task cap must leave room for the prefix (gap 6) |
| Choosing the grant | `_spendable_grant` (`tickets.py:144-166`), `_rooms_back`, `_grant_validity` | Lookup by holder (the issuer ship) and target, `grant_id` honoured, oldest valid otherwise | A shared "grant that covers (holder, target, room)" helper used by both tickets and directs; the root-person-in-room rule is open (gap 22) |
| Posting without mentions | `_post_as_system` (`system_author.py:33-38`); `_refuse_live_ship_keys`, `_ship_post_budget` | An in-transaction post under the issuer that records no mention | Not through `send_message` (`chats.py:98`); not a `message_kinds` row (`system_author.py:11`) (gap 7) |
| Mentions row when `ready`; `direct_id` | `mentions` (`ships.py:29`), `mentions()` (`ships.py:339-356`) | Insert at `ready`, `direct_id` in items | Additive; fake station too |
| Response, 403 | `Problem` | — | — |
| Exported ids | — | `<peer id>:<id>` form (A:366-367) | Display only |

**Tickets** (`tickets.py`)

| Requirement | Build on | Missing | Change |
| --- | --- | --- | --- |
| Basis `direct` first (1.7) | `_mode_for` (`:125-142`) | Rule 1 before `:133`'s person gate; `direct` → `used` | **[S3]** G15's order: a ship-authored message can now build (still only through a `ready` direct) |
| Per-ship cap counts directs | `_ship_grant_builds` (`grants.py:89-93`) | `basis IN ('grant','direct')` | **[S3]** G15 and G11's `ship_builds_left` change meaning (gap 21) |
| Budget per link, chain, root, hops | `:109-113` | Insert `direct_id` and `hops` | Additive |
| Footer and source for chains | `_footer` (`:53-64`), `_sources` (`:255-270`), agent `source_label` (`station.py:330-348`), web `sourceLabel` (`app.js:510-514`) | Basis `direct` in `:62` and `:261` | **[S3]** G17 extends to `direct`; names per Q1 |
| Re-send re-check | `_grant_lapsed` (`:168-182`) | Basis `direct`: chain and the issuer's breaker | **[S3]** G18 extends to `direct` |
| Breaker gives `read` | — | Rule 1 checks breakers on the issuer | Additive |
| Staleness of a `ready` direct | `_mention_stale` (`:191-201`) | A rule (gap 4) | Additive |
| Deferral | `issue_ticket` defers only `read` (`:101-104`) | — | None: a direct build is never deferred, as status:284-286 (S10) rules for grants; a direct that reads may be |

**Run tools and hops** (agent, and the ticket checks on the station)

| Requirement | Build on | Missing | Change |
| --- | --- | --- | --- |
| `ticket` MCP server (1.3) | `mcp.py`'s `Tools`, `handle`, `serve_with`; `run_agent.py` | A `run-tools` command serving two tools, adding `ticket_id` to each | New command |
| Per-run MCP config | `ClaudeRunner._command` (`runs.py:127-140`) | The ticket id must reach `run()` (`:166-170`) and a per-run config file with the `ticket` server | `run_mcp_config`'s "deliberately absent" (`install.py:40-47`) and the tests pinning it (`agent/tests/test_install.py:195-200`, `agent/tests/test_board_tools.py:174-181`, `agent/tests/test_runs.py:80`, `:113`) change meaning |
| Builder allow list | `builder_settings` (`runs.py:69-75`) | Allow exactly `mcp__ticket__station_direct`, `mcp__ticket__station_grant` | In `runs.py` only, never in `claude_sandbox_settings`, which team mode shares (`workers.py:311-320`) |
| Acts with `ticket_id` (A:316-318) | `_ticket_running` (`tickets.py:43-44`), `_grant_lapsed` | Running, `build`, own ship, chain valid, no breaker, same root person | New check, shared by directs and delegation |
| Hops | `tickets.hops` | `ticket.hops + 1`; refuse at `max_depth` | Enforceable for runs only (gap 1) |
| Which runs get tools | — | — | Q2 |

**Confirmation** (station and web)

| Requirement | Build on | Missing | Change |
| --- | --- | --- | --- |
| `pending`, 600 s, `expired` | — | Status lifecycle; expiry checked lazily on read | Additive |
| Who confirms | `current_user` | A rule for ship-issued `each` links (gap 2) | — |
| Pending list, view, confirm, decline | `app.js` router (`:142`), the grants page's ask-first pattern (`:746-750`) | Routes, `#direct` view, chain display, no batch | Additive; machine names via `presence.py:135-137`'s docking row, shown as data |
| Telling the person | — | Nothing tells anyone a direct waits (gap 3) | — |
| `confirm` on roots | `make_grant` (`grants.py:268-282`) | `confirm` in the body for ship grantees | **[S3]** G8 fixes `confirm` 'none' (step3:183); Q6 |

**The breaker** (station; a new module or part of `directs.py`)

| Requirement | Build on | Missing | Change |
| --- | --- | --- | --- |
| Per-ship 429 | — | Count the issuer's directs in the last hour | Additive |
| Three trips, `breakers` table | — | Station-wide count, same-task hashes, echo search | Gaps 9, 10, 13 |
| Effects | — | Refuse directs and delegation; `read` for its directs; re-send and run acts refused | Gaps 14, 26 (delegation unlimited; delegates of a tripped ship) |
| Reset | `_admin`, `_super_admin` (`peer/superyak_peer/auth.py:117-125`), the station CLI pattern (`peer/superyak_peer/__main__.py:232-241`) | Route, CLI, a way to list breakers (gap 12) | Q4 |
| Notice | `station_notices` (`ships.py:380-393`), Odo's `_announce` (`watch.py:293-316`) | `breaker-<id>` text through `safe_line` | Additive |
| Policy section | 4a's schema (`4a:324-338`) | `breaker` keys, bounds, widening direction | **[S4]** gaps 10, 11 |

**Delegation** (station and agent)

| Requirement | Build on | Missing | Change |
| --- | --- | --- | --- |
| Ship grantees on browser roots | `_grant_grantee` (`grants.py:249-256`) | Ship grantees with an owner (Q3), `depth`, `confirm` | **[S3]** G8 step 3 and S8 (root depth 0) |
| `POST /api/grants/delegate` | `_grant_chain`, `_grant_validity`, `_insert_grant` (`grants.py:60-70`), `_sign_grant` | Subset rules, default expiry, depth, budget, `each`, grantee set, acceptance, `ticket_id` | `_insert_grant` takes actions, depth, confirm, parent |
| Acceptance by another owner | `charter_acceptances` as a pattern (step4:220-242) | Storage (gap 16), route, browser control | New table and signed kind: `RECORD_KEYS` (`identity.py:76-83`) and `SIGNED_RECORDS` (`signatures.py:16-19`) gain one |
| Validity under chains | `grants.py:95-122` | Acceptance check; `ships_of` | **[S3]** G9 gains a check; **[S4]** 4a's grantee check (`4a:2279-2281`) |
| Ship routes list, revoke | `_grant_view` (`grants.py:179-212`), `revoke_grant` (`:289-306`) | `GET /api/ships/me/grants`, `POST /api/ships/me/grants/{id}/revoke` | Additive |
| Visibility | `_grant_visible` (`grants.py:130-134`) | The grantee ship's owner | **[S3]** G11 (gap 16) |
| Tools | `mcp.py` `TOOLS` (`:511`), `StationClient` | `station_grant`, `station_grants` | Additive |
| Grants page | `app.js:741-760` | Ship grantees, chains, depth, confirm; "Given by you" holds grants ships issued under the caller's roots | `given` (`:758`) needs a third list or a label |

**Policy readers** (through 4a's `_policy_in_force`, or step 3's `_grant_policy` if step 5 were built first)

| Requirement | Build on | Missing | Change |
| --- | --- | --- | --- |
| `agent_grant_default_hours` | `flat_policy` keeps it (`4a:2198-2205`) | The reader in delegation | Gap 17 (clipping) |
| `grantees.ships_of` | 4a stores it (step4:196) | A ship grantee allowed when its owner is listed | **[S4]** `flat_policy`'s `grantees` is "the `people` list or None" (`4a:2205`; C16) |
| `delegable` | 4a's `_issued_by_a_ship` (`4a:2265-2266`, `:2279-2281`) | Nothing: it starts biting | — |
| `breaker` | — | Section, bounds, defaults, widening paths | **[S4]** `RESERVED_KEYS` (`4a:337`), `SECTIONS`/`NUMBERS` (`4a:330-334`), `MAX_CONFIRMED = 105` (`4a:1518`) |
| `roots` | Grant columns (`grants.py:11`) | Everything in 1.9 | **[S4]** Q5 and gap 30 |

**Status, footers, names, restore, docs**

| Requirement | Build on | Missing | Change |
| --- | --- | --- | --- |
| Status grants and breaker lines | `__main__.py:217-225`; 4a's `charter_line` (`4a:4142-4154`) | Lines from `GET /api/ships/me/grants` and a breaker field | Additive; older station tolerated as 4a does |
| Web Ships section | `app.js:942`; 4b's `instructions` field (step4:360-361) | Grants and breaker per ship | Additive |
| Display names (C10) | `render_one` (`peer/superyak_peer/instructions.py:19-21`), `_footer`, `_via_name`, `safe_line` (`ships.py:33-38`) | Q1 | Block headers change bytes, not pairs (as 4a's brackets did, step4:67) |
| Restore | `backups.py:380-387`, `:506-560` | Breakers, directs, acceptances (gap 25) | **[S3]** G13 grows |
| Docs | `peer/API.md:310-375`, `:1005-1047`; `agent/README.md` | Directs, breakers, delegation, acceptance; API.md's known limit "later steps record which session acted" (`API.md:1044-1047`) | — |

### 2.3 What the charter plans fix that step 5 reopens

- `flat_policy` flattens `grantees` to the `people` list (`4a:2205`), so validity (`4a:2279-2281`) and `grant_people`
  refuse every ship grantee under a restricted set; C16 records the cost (step4:58). Step 5 changes the return shape
  or adds a `ships_of` key, and every reader of `policy['grantees']` with it.
- `RESERVED_KEYS = ('roots', 'breaker')` and the refusal "reserved for step 5" (`4a:337`, `4a:367`; step4:262). Adding
  `breaker` changes `DEFAULT_POLICY` (`4a:324-328`), `SECTIONS`, `NUMBERS`, the widened paths (step4:210-217) and
  `MAX_CONFIRMED` (105, "four numbers, one action and 100 ids", `4a:1518`) to 109. 4c's `require_confirmed` and its
  follow walk read the same paths (4c:85-86).
- Every charter revision signed before step 5 stores a full policy without `breaker` (C11, C12: "the signed record
  state[s] every limit in force"). After step 5 the stored policy no longer states every limit; readers must fill the
  breaker defaults, and `widened_paths` must compare an old revision with a new one without listing the breaker
  section as gained (gap 11).
- Charter roots (C2) need: rows materialized inside 4a's activation transaction (I12, `4a:148`) for the signer, who
  has no acceptance row (C17); materialized at 4c's acceptance, which no longer lists roots for confirmation (spec A
  amendment 7, step4:96-100); validity "still active and accepted" through 4c's `_accepted_pair` and follow walk
  (4c:11-16); supersession on each new revision; the reconcile (C27). Each touches a 4a or 4c seam.
- 4c's constraint "4c changes no step 3 grant code" (4c:147) holds for 4c; step 5 changes `grants.py` and
  `tickets.py` on top of whatever 4a merged there (`_grant_policy`, the validity line, the footer's ` · charter rN`
  in `_ticket_json`, `4a:3459`). The two must be rebased, not re-planned.
- 4c's known limit: display-name growth breaks the caps in silence, since every block prints "signed by <name>" and
  `rename_user` checks no binding (4c:189-192). Q1's B and C both lengthen the header; the caps check must count it.

---

## 3. Gaps and conflicts

Stated, not resolved. Items 1 to 15 are where spec A is silent or contradicts itself; 16 to 31 are where it meets what
steps 3 and 4 built or planned.

### 3.1 Inside spec A

1. **Hops bind runs, not sessions.** A session acts with `hops` 0 by omitting `ticket_id` (A:230), and a session and
   its ship's run tools hold the same key. A run cannot omit it (the `ticket` server adds it and the key is unreadable,
   `workers.py:316-320`, `:338`), but its reply is room text, and a writable session on watch reads that text and may
   act on it at hops 0. So direct → run → reply → session → direct passes any `max_depth`. Spec A's hops bound "direct →
   run → direct relays" (A:231-232) only; the echo check catches a copied task, not a paraphrased one (A:266-267).
2. **Who confirms an `each` link a ship issued.** A child keeps `each` from its parent (A:188), so with an `each` root
   every lower link has `each` and is issued by a ship. Spec A says the direct waits for "that link's issuer (a person)"
   (A:236-237), and ship keys get 403 on confirm (A:435). With several `each` links, which issuer confirms is not said.
   Plausible reading: the issuer of the topmost `each` link. That is a person only if ships may not set `each` under
   a `none` parent, and spec A doesn't forbid it (A:188 says only "`each` if the parent's is").
3. **Nobody is told a direct waits.** The confirm URL goes to the issuing ship (A:242); no notice, mention, hook line
   or page badge reaches the person, and the direct expires in 600 s (A:237-238).
4. **A `ready` direct has no lifetime.** `directs.expires` exists (A:219) but only `pending` gets one (600 s). A direct
   whose target's watcher is offline stays `ready` forever; the fresh owner mentions bound (24 hours, fresh:37-41) is
   stated for owner and grant builds only (`tickets.py:191-201`), and "answered" isn't stated for directs either.
5. **A direct whose ticket reads.** Rule 1 makes a direct `used` only on `build` (A:298). A `ready` direct whose ticket
   is `read` (breaker, revoked chain, budget, cap) keeps `ready`, and `UNIQUE(ship_id, message_id)` (`tickets.py:20`)
   means it can never build later. Its final status isn't defined.
6. **Task size against the message cap.** `task` may be 20,000 characters (A:224); the posted body adds `Direct to
   <Target name>: ` and `send_message` caps bodies at 20,000 (`chats.py:78`).
7. **"Records no mentions" has no path.** Every post records mentions (`chats.py:98`, `ships.py:318-330`), so a task
   holding `@serenity` would start Serenity's run from the direct's own message. The one post without mentions is the
   system author's (`system_author.py:33-38`), and a `message_kinds` row can't mark a direct (CHECK `claim`/`notice`,
   `system_author.py:11`; a kind row also means never answered and never federated, `:55-62`).
8. **The direct's own message has no source.** It reads as `{kind: "post"}`, "no run ticket" (`tickets.py:269`;
   `station.py:348`), so readers can't tell a direct (and its status) from any ship post. Spec A gives a source only to
   ticketed replies (A:334-340).
9. **The station-wide trip can cover no ship.** It covers ships that issued "more than a quarter" (A:258-259). With the
   per-ship limit of 10 and 31 directs, five ships at 6-7 each have none above a quarter: the trip covers nobody, yet
   refuses the direct that tripped it, and every later direct trips it again. Nor is it said whether the refused
   direct counts toward the next hour.
10. **Breaker bounds and direction.** Spec A gives defaults (A:91, A:384-385) but no bounds, which is why 4a reserves the
    key (C11, step4:53). `directs_per_ship_hour`, `directs_per_hour` and `same_task_ships` widen when they grow;
    `echo_chars` also widens when it grows (a longer copy is needed to trip). A value of 0 or 1 for `same_task_ships`
    trips on every direct.
11. **The breaker section in charter revisions signed before it existed.** See 2.3: either the stored policy is read
    with breaker defaults filled (and C12's "every limit in force" holds only for limits known at signing), or each old
    revision reads as having no breaker. The follow walk (C21) must not list `breaker.*` as widened between an old
    revision and a new one with default values.
12. **No way to see breakers.** Reset takes an id (A:270); no route or CLI lists breakers, and CLAUDE.md's "Approving on
    the station" has no breaker step. Status shows "any breaker on the ship" (A:361) but no API is named for it.
13. **The echo check's scope and cost.** "A message the issuer received in the last hour ... posted by someone else in a
    room the issuer is a member of" (A:262-263): it doesn't say whether remote rooms' `peer_messages`, Wormhole's
    relays of lattice text, system notices or the target's own replies count. A 200-character match over an hour of
    every room's messages needs rolling hashes (messages are up to 20,000 characters).
14. **Delegation has no rate limit.** The per-ship 429 and every trip count directs (A:253-264). A ship (or a steered
    session) can issue child grants without limit until a breaker trips on a direct, and a breaker on a ship doesn't
    touch grants it already issued (A:269-270): its delegates keep acting (gap 26).
15. **Tool arguments.** `station_direct(target, room, ...)` doesn't say whether `target` is an id or a username, or
    `room` an id or a title (`station_open_room` takes usernames, `resolve_room` takes either, `mcp.py:35-49`).
    `station_grant`'s defaults for `budget`, `depth` and `confirm` aren't given (A:274), and no route lets the issuer
    read a direct's status after the response.

### 3.2 Against steps 3 and 4

16. **Acceptance has no storage, and the grantee's owner can't see the grant.** Grant rows never change except
    revocation (step3:183-184), and the table has no acceptance column (survey3:252-254, Q9 at survey3:424). A root to
    another owner's ship isn't covered by spec A's acceptance rule (survey3:260-261, Q11), though step 3's grants are
    roots and step 5 opens them to ships. `_grant_visible` shows a grant to its grantee, its issuers and its targets'
    owners (`grants.py:130-134`), never to the owner of a grantee ship, who must accept it (A:190-191); and spec A lets
    that owner neither revoke it (A:205-207) nor leave it.
17. **Default expiry against the parent's.** "It expires no later (default `agent_grant_default_hours`)" (A:187): a
    parent expiring in 3 hours makes the 24-hour default invalid. Clip to the parent, or refuse?
18. **The session label has no column, and the header has side effects.** D7 says every act records one (A:36);
    neither `grants` (step3:170-175) nor `directs` (A:216-219) has a column (survey3:256-257, Q10). Step 3 kept it out
    of the signed record (step3:180-182). `X-Superyak-Session` also writes a presence row per name
    (`presence.py:41-59`); a run-tools label such as `watcher` (A:57) would show in the directory as a session, and runs
    send no session today (`presence.py:78-79`).
19. **Browser roots can't be delegated.** Step 3 makes every root at depth 0 (S8, step3:78; `grants.py:65-66`) with no
    depth in G8's body, and delegation needs depth > 0 (A:186). The bound "depth 0-5" (A:94) exceeds what validity
    accepts: C16 counts a chain's links, root included (step4:58), so under `max_depth` 3 a root of depth 3 lets ships
    issue great-grandchildren (four links) that are invalid from birth (survey3:262-263).
20. **Ship grantees under a restricted set.** See 2.3 (C16, `4a:2205`). Spec A also doesn't say whether `ships_of`
    admits residents (no owner) or the system author; step 3 refuses both as grantees only because it refuses ships.
21. **The per-ship cap counts grant builds only.** Spec A counts "every `direct` and `grant` build ticket"
    (A:306-307); `_ship_grant_builds` counts `basis='grant'` (`grants.py:89-93`), as G15 and G11's `ship_builds_left`
    (step3:232-233, step3:283-284) say.
22. **Where a direct may build.** Step 3 builds only where the root issuer is in the room when the ticket is issued
    ("the issuer keeps sight of every build he granted", S5 at step3:75; `tickets.py:163`). Spec A requires only both
    ships (A:224) and reads `"*"` as "any room the acting ship and the target share" (A:171); survey3:157-161 noted
    that this bites only once ships hold grants. Directs in Jenn's room, under Andy's root, would build out of Andy's
    sight unless S5 carries over.
23. **The watcher's ship budget swallows directs.** A direct's mention has a ship author, so the target's watcher spends
    its 5-an-hour ship budget per room first (`watch.py:15`, `:130-131`); the sixth direct in a room in an hour gets a
    pause note and is marked done without a ticket (`:131`, `:276-291`). That is below spec A's 10 an hour (A:254), and
    the pause note itself `@`-mentions the issuing ship (`:283`), which starts its read-only run. `direct_id` (A:240)
    lets the watcher tell; the station's limits must then be the loop bound.
24. **The person gate in the ticket decision.** `_mode_for` returns `read` for every non-person author at `:133`, before
    any rule; basis `direct` must come before it, which is the first build path whose message a ship wrote. Testing 1's
    "Text a ship posts never gives `build`" (A:421) then holds only because the `mentions` row comes from the station,
    not the text (gap 7).
25. **Restore.** The reconcile takes back what grants access (backups spec S16, `backups.py:506-560`). A breaker
    tripped after the copy is gone from a restored station (a widening); a `ready` direct in the copy can build again
    (until gap 4's bound); acceptances of child grants and session labels have no rule; `COMPARED` (`:380-387`) lists
    none of them.
26. **A breaker on a ship and the grants it issued.** "That ship cannot issue directs or grants" (A:269), and its
    directs' tickets read, but its children stay valid (validity has no breaker check, `grants.py:95-122`), so a worm
    that spread by delegation continues through the delegates.
27. **Run tools under a grant build.** A builder run's root is the ticket's `root_id`: the owner for basis `owner`, the
    grant's issuer for basis `grant` (`tickets.py:137`, `:142`). Under the confused-deputy rule (A:192-193) Jenn's
    mention of Rio Grande, under Andy's grant to her, starts a run that may spend every chain Rio Grande holds from Andy,
    over ships Andy never granted Jenn. Spec A's security text allows it ("their own root's chains", A:401-402). (Q2.)
28. **Many ships on one machine.** A grant to `serenity-bricks` is usable by every session on that Mac that can read
    `~/.superyak/ships/serenity-bricks/station.json`, `serenity`'s included (survey3:190-194); D7's "Grants, budgets and
    keys are per ship" (A:36) holds for accounting only. Step 3 asked step 5 to say so (step3:359-360).
29. **Names that collide.** Persons rename freely, with no uniqueness (`auth.py:53-64`; `PATCH /api/me`,
    `app.py:315-318`). Ship names are fixed at docking from the username (`ships.py:170`), but `SHIP_NAME` allows
    doubled dashes (`ships.py:11`) and `safe_line` collapses spaces (`:37-38`), so a ship docked as `rio--grande` reads
    "Rio Grande" in every footer. And usernames, which the room calls private, already reach co-members' clients and
    every run prompt through `GET /api/chats/{id}` members (`chats.py:59-60`) and `GET /api/mentions` authors
    (`ships.py:343-354`); the web app shows a person's username only on admin views (`app.js:930`, `:979`). Q1.
30. **Charter roots against 4a and 4c.** 2.3 lists the seams. Survey4's open items stay open: a root clause has no id,
    so "a root that is added or widened" (A:98-99) can't be matched across revisions (survey4:312-315); a follower moves
    without accepting, so when their roots materialize isn't said, nor what renews a root after `expires_hours`
    (survey4:316-319).
31. **Self-directs and self-grants.** Nothing refuses a direct whose target is its issuer, or a ship grant whose grantee
    is one of its own targets (G8 refuses only a person granting to themselves, `grants.py:255-256`): a ship would
    start its own builder runs, bounded only by hops and budget.

---

## 4. Questions only Andy can answer

One at a time. Six questions. Q1 and Q2 block the spec; Q3 to Q5 block the merges that need them; Q6 is a default on
a page.

**Q1. In footers, "signed by" lines and the confirm view, how should a person's name be told apart from a look-alike?**
*(Blocks the spec: C10 sent it here, step4:52, step4:808-809.)*
A person may rename to "Andy" or "Serenity" (`auth.py:53-64`), and a ship docked as `rio--grande` shows as "Rio Grande"
(gap 29). Step 5 puts more names in footers (`Builder for Andy, via Serenity · grants #a1b2 > #c3d4`, A:310-311) and the
confirm view lists every link's issuer (A:247).
- A. Mark a grantee's name when it collides with the root's or another member's. Cost: "collides" needs a definition
  (case, spaces, NFKC), and homoglyphs (a Cyrillic А) and near matches still pass; it reveals nothing.
- B. Show the short user id beside the name, for example `Andy (3f9a2c)`, written apart from grant ids (`#a1b2`).
  Cost: an opaque id people learn to read. Ids are random (`common.py:19-20`) and accounts come only by invitation or
  approval, so six characters don't collide in practice; the id can't be faked and reveals nothing new. Longer headers
  count toward the caps (4c:189-192).
- C. Show usernames, only if Andy decides login names may be shown. Cost: usernames may be email addresses, and they
  would go into every footer, block header and run prompt. The API already sends them to room co-members (gap 29); the
  web app doesn't show them.

Recommended: **B**, the narrower choice that can't be spoofed, for people and ships alike.

**Q2. Which builder runs get the run tools?** *(Blocks the spec.)*
Spec A gives every builder run the `ticket` server (A:275-279, A:325), and a run may spend any chain its ship holds from
the run's root person (A:192-193).
- A. Every builder run, as written. Cost: a person grantee's mention reaches every ship the mentioned ship holds grants
  over from the same root, beyond what the root granted that person (gap 27).
- B. Runs whose ticket basis is `owner` or `direct`; a `grant` run (another person's mention) gets none. Cost: a person
  grantee can't start relays; Andy's own mentions and ship directs can.
- C. No run tools in step 5: sessions only, hops always 0. Cost: no relays at all; spec A's hops have nothing to bound.

Recommended: **B**. A grant to a person over one ship then never lends that ship's own grants.

**Q3. May resident ships (Odo, Wormhole) hold grants?** *(Blocks the merge that opens grants to ships.)*
With no charter, spec A's grantee set is unrestricted (A:383); survey3's Q7 (survey3:418) was never answered, because
step 3 left ship grantees out. Wormhole relays text from Stanley's lattice; Odo answers anyone in a one-person room.
- A. Yes, as written. Cost: a resident that holds a grant can direct the root's ships, with no owner to accept, revoke
  or answer for it.
- B. Only ships with an owner may hold grants; residents and the system author are refused, at making, at delegation
  and at every validity check. Cost: no resident ever directs.

Recommended: **B**.

**Q4. Who may reset a breaker?** *(Blocks the breaker merge.)*
Spec A says "Only an admin" (A:270). Step 4 narrowed charter signing from "an admin" to a super admin (C3, step4:45).
- A. Any admin, as written. Cost: any admin can let a tripped ship act again.
- B. Super admins only (today, Andy). Cost: one check (`_super_admin`, as C3 uses); a trip at night waits for Andy.

Recommended: **B**.

**Q5. Should step 5 build charter roots, or keep the `roots` key reserved?** *(Blocks only a charter-roots merge.)*
C2 moved them here (step4:44): "The charter hands out no authority in step 4 ... Andy can widen this later."
- A. Build them. Cost: the largest single piece (1.9), and changes to 4a's activation and 4c's acceptance (2.3, gap
  30); each root is a standing grant his signature hands out, renewed only by a new revision.
- B. Keep `roots` reserved; Andy grants his ships to ships in the browser. Cost: none now; another owner's ships get no
  authority from the charter itself.

Recommended: **B**.

**Q6. Should a grant to a ship ask Andy to confirm each task by default?** *(Blocks only the confirmation merge's
page.)*
Spec A allows `confirm: each` on grants to ships (A:171, A:188) and gives no default. Each confirmed task waits up to
600 s for the issuer (A:237).
- A. `none` by default; tick "Confirm each task" to ask. Cost: ships direct each other with no person in the loop,
  which is the city's aim (A:12-13).
- B. `each` by default; untick to stop being asked. Cost: every direct under the grant waits for Andy, and expires
  if he doesn't answer in ten minutes (gap 3).

Recommended: **B** for a first grant to a ship, the narrower default; Andy unticks it once he trusts the chain.

Not asked, because spec A or a later spec settles them: hops and their bound (A:230-232); the 600-second window
(A:237); the breaker's default numbers (A:384-385); whether S5 carries over to directs (gap 22) and the acceptance rule
for roots (gap 16), which are spec rulings under D8.

---

## 5. Risks and Review Focus candidates

**Security and authority**

1. **Widening through run tools** (gap 27, Q2): a person grantee's text reaching ships it was never granted.
2. **Hops laundered through sessions** (gap 1): a writable session on watch that reads a run's reply and acts at hops 0.
   Spec A accepts a steered session as residual risk (A:403-405); the plan should say this path is that risk.
3. **A grant held by a ship is a grant to its machine** (gap 28), and to any process there with the user's rights.
4. **A direct built without its root person present** (gap 22): Andy's chain spent in a room he can't read.
5. **The key outside the sandbox.** The `ticket` server holds the ship key in the run's process tree. Builder runs
   can't read key files (`workers.py:316-320`) or `$HOME` (`:338`); the server must not echo the key in errors, as
   `status` already redacts it (`__main__.py:224`).
6. **Name spoofing in the confirm view** (Q1): Andy confirms a task because a link reads "Serenity".
7. **Confirmation as a lever.** A confirmed task is the request the target run builds (`watch.py:44-46`); a long task can
   bury an instruction below the fold. The view must show it whole (A:246), and the run's law still binds.

**The breaker failing open**

8. A station-wide trip that covers nobody (gap 9); paraphrase (A:266-267); a restore that drops a trip (gap 25); the
   delegates of a tripped ship (gap 26); delegation with no rate limit (gap 14).
9. An error inside a breaker check must refuse the direct, never pass it: the check runs in the issuing transaction,
   so a raise rolls back the post and the record together (`db.py:106-126`).
10. Every count reads the station's clock. A clock stepped forward makes the last hour's directs look old and empties
    the counts, so the limits fail open until the hour refills; stepped back, they hold longer (fresh:188-191 notes the
    same for mentions).

**Loops between ships and cost**

11. **Fan-out.** One session direct → a run issuing up to 10 directs at hops 1 → each run issuing 10 at hops 2: in
    principle 111 runs from one seed under the defaults. In practice the per-ship 429 caps each issuing ship at 10 an
    hour, the trip stops the station at 30, and each grant's daily budget and the 20 grant-or-direct builds per ship a
    day bound the builds (A:384); the bounds hold only if gap 9's trip covers someone.
12. **Model time.** Each build may run 1,200 s on the target owner's machine (`runs.py:19`); 20 builds a day is about
    6.7 hours of builder time per ship, and with acceptance another owner's ship can spend it on Andy's machines. The
    watcher runs one at a time (`watch.py:1`), so a burst queues behind the owner's own mentions.
13. **The ship budget as a silent loss** (gap 23): directs dropped by the watcher with a pause note that starts another
    read-only run.

**Mixed versions**

14. **Pre-ticket watchers** (Defiant, HANDOFF.md:23-24): a direct's mention reads as a ship's and runs read-only
    (A:381-382). Safe.
15. **Current watchers without step 5:** a direct builds with the ticket's footer and no run tools (narrower), but the
    ship budget applies (gap 23).
16. **Older MCP servers** have no `station_direct`; **an older station** answers the new tools with 403 or 404, which
    must reach the model as an error result (A:389-390).
17. **A station rolled back below step 5** ignores `directs` and breakers; a `ready` direct's mention row stays, and the
    old decision reads a ship author as `read` (`tickets.py:133`). Safe, but a breaker vanishes with the rollback.
18. **Charter revisions older than the breaker section** (gap 11): an old revision read without defaults would compare
    as a widening at the next follow step.

**Review Focus candidates**

1. A direct → run → direct chain at exactly `max_depth` hops, and the same relay through a session (gaps 1, Testing 6).
2. A chain revoked while its run is mid-act: the next act and the next re-send refused (A:229, step3:310).
3. 31 directs from five ships in an hour (gap 9).
4. A task of 20,000 characters holding `@serenity` (gaps 6, 7).
5. A grantee mention of a ship that holds grants from the same root (gap 27, Q2).

---

## 6. Suggested merge split

Each merge stands alone under section 2 of the law, with its own plan and tests. Steps 4a (and 4b, for the grants
form's limits) come first: step 5 reads the policy through 4a's `_policy_in_force`. No grant to a ship is made on the
live station before 5c (the breaker) is live, as no charter is activated before 4b (C31).

**5a. Names that can't be spoofed** (Q1; station and agent)
- The chosen form in `_footer`, `_via_name`, `render_one`'s "signed by", the grants page and the agent's `source_label`;
  the caps count the longer header.
- Touches: `tickets.py`, `instructions.py`, `grants.py`, `app.js`, `agent/superyak_agent/station.py`, `hook.py`,
  `API.md`, tests. About 6-8 files, 200-300 lines.
- Value alone: closes C10 for today's owner and grant footers and the law's blocks.

**5b. Directs from sessions** (station, MCP, watcher)
- Root grants whose grantee is one of the issuer's own ships (other owners' ships wait for 5f); `directs`; `POST
  /api/directs` with grant choice, room rules (breakouts and remote rooms refused; gap 22 decided), the post without
  mentions and its source (gaps 6-8); ticket basis `direct` before the person gate, the per-ship cap counting it, budget
  per link, footer and source, re-send re-check, the `ready` lifetime and final status (gaps 4, 5); `direct_id` on
  mentions; the per-ship 429; the session label column; `station_direct`; the watcher's ship-budget exemption for
  directs (gap 23); status grants line; the grants page for ship grantees.
- Touches: a new `directs.py`, `grants.py`, `tickets.py`, `ships.py`, `chats.py` or `system_author.py`, `db.py`, `app.py`,
  `pyproject.toml`, `mcp.py`, `station.py`, `watch.py`, `__main__.py`, `agent/tests/conftest.py`, `app.js`, `API.md`,
  tests. About 15 files, 1,200-1,500 lines.
- Value alone: Serenity's session on the Mac makes Rio Grande build on the Pi, under Andy's grant, within budget. The
  first ship-to-ship authority.

**5c. The breaker and its notice** (station, policy, Odo)
- `breakers`; the three trips (gaps 9, 13); refusals of directs and delegation; `read` for its directs and re-sends;
  reset by route and CLI (Q4), a list (gap 12) and the CLAUDE.md step; `breaker-<id>` through `station_notices`; the
  policy's `breaker` section in 4a's schema (bounds, widening direction, `MAX_CONFIRMED`, old revisions, gaps 10-11);
  the reconcile keeps trips (gap 25); status breaker line.
- Touches: `directs.py` or a new `breakers.py`, `charter.py`, `ships.py`, `backups.py`, `app.py`, `__main__.py` (peer and
  agent), `CLAUDE.md`, `API.md`, tests. About 10 files, 900-1,100 lines.
- Value alone: the gate for using 5b on the live station.

**5d. Run tools and hops** (agent and station)
- `run_agent.py run-tools --ticket`; a per-build MCP config; the builder allow list in `runs.py` only; the ticket check
  for acts (running, build, own ship, chain valid, no breaker, same root person); `hops + 1` and the refusal at
  `max_depth`; which runs get tools (Q2); the run-tools session label without a presence row (gap 18).
- Touches: `__main__.py`, `mcp.py`, `runs.py`, `install.py`, `watch.py`, `directs.py`, `tickets.py`, tests (and the four
  that pin "aDNA only"). About 9 files, 700-900 lines.
- Value alone: an owner's mention can start a relay; hops bound it.

**5e. Confirmation** (station and web)
- `confirm` on roots to ships (Q6); `pending`, 600 s, `expired`; who confirms (gap 2); telling the person (gap 3);
  `GET /api/directs/pending`, confirm and decline; the `#direct` view with the whole task and chain; browser tests.
- Touches: `directs.py`, `grants.py`, `app.py`, `app.js`, `app.css`, `API.md`, `test_browser.py`, tests. About 8 files,
  800-1,000 lines.
- Value alone: Andy can let a ship direct his ships and still see each task first.

**5f. Delegation and acceptance** (station, agent, web)
- `POST /api/grants/delegate` with the subset rules and defaults (gap 17); acceptance storage, its signed kind, route
  and control (gap 16), for children and for roots to another owner's ship; visibility for the grantee's owner;
  `ships_of` in 4a's `flat_policy` (gap 20) and residents per Q3; `delegable` live; `GET /api/ships/me/grants` and the
  ship revoke; `station_grant`, `station_grants`; chains on the grants page; the restore for acceptances; the subset
  property test.
- Touches: `grants.py`, `charter.py`, `signatures.py`, `identity.py`, `backups.py`, `app.py`, `mcp.py`, `station.py`,
  `app.js`, `API.md`, tests. About 12 files, 1,100-1,400 lines.
- Value alone: "agents grant agents" (D1): Serenity passes a narrower day of its grant to Defiant, and Jenn's ship can
  hold Andy's grant once she accepts it.

**5g. Charter roots** (only with Q5 A)
- Root clauses, their identity across revisions, materialization at activation (the signer) and acceptance, root
  widenings at acceptance, supersession, renewal, validity "still active and accepted", the reconcile (gap 30).
- Touches: `charter.py`, `acceptances.py`, `grants.py`, `layers.py`, `backups.py`, `app.js`, `API.md`, tests. About 8
  files, 800-1,000 lines.
- Value alone: the charter hands out authority without a browser grant per ship.

Totals: about 4,900-6,200 lines for 5a-5f, 5,700-7,200 with 5g. 5a, 5b and 5c are the minimum that makes step 5 useful
and safe on the live station. 5d needs 5b; 5e needs 5b; 5f needs 5b and is easier after 5d (the `ticket_id` rule on
delegation). 5a can merge any time, before or after the charter.
