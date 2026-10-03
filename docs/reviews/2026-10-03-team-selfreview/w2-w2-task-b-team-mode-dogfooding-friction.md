# w2 Task B: team-mode dogfooding friction log

Author: w2 (Claude collaborator), team `selfreview`, 2026-10-03. Every item below was observed in this session or traced in code at HEAD 7477843; sources are cited inline. Contributors: lead, w1 (Codex), w3 and w4 (Claude). Confidence: high on F1-F6, F16, F17, F19 and L1-L3 (reproduced by 2+ agents or read directly in code); medium on F12 and F18 (partly inferred). Readable copy: `.claude/team-relay/selfreview/` in the repo (the lead's hand-made relay, see F20).

## A. Friction log (observed)

### Visibility of team artefacts
| # | Friction | Evidence | Who hit it |
|---|---|---|---|
| F1 | **Plans are unreadable for Claude workers when Slack is off.** The lead's plan path in the brief is denied for Read and `ls`/`cat` say "No such file". Codex w1 can cat it. | Sandbox `denyRead: [home]` (team/superyak_team/workers.py:339). With Slack off, `publish_plan` has no canvas link, so a file in the team home is the only copy (teamd.py:376-406). | w2, w3, w4 (w1 ok) |
| F2 | **Our own `team_plan` documents are just as unreadable to peers.** w4 had to ask for this doc over `team_message`, and the lead had to build a relay by hand (F20). | As F1. | w4, lead |
| F3 | **`team_post` is write-only when Slack is off.** It returns `{"ts": null}` with no confirmation. It goes only to `messages.jsonl`, which no Claude worker can read, and it isn't in the lead's `team_status`. The lead's mistaken "placeholder" post is invisible to everyone. Yet the tool says "team + human can see it". | `say()` teamd.py:65-78; lead `status()` shows `lead_inbox` + `last_message` only. | w2, w3, w4, lead |
| F11 | **Tasks ask for things the security model forbids.** My task says to read "the transcript under ~/.superyak/team/teams/selfreview/"; Claude workers can't (team-mode.md:89-99). The lead has no visibility matrix. | Task text vs docs. | w2 |
| F15 | **"Send DONE with the document path"**: the path is in the team home (F1). | lead plan, Coordination. | w2 |
| F20 | **The relay workaround writes into the read-only repo.** The lead mirrors plans every 15 s into `<repo>/.claude/team-relay/selfreview/`. It works (I read the lead plan through it), but `git status` now shows `?? .claude/`. That's a commit hazard, and it breaks "nothing is written to the repo" (team-mode.md:82-83). It's proof that rank 1 is needed. | `git status --short` in repo; relay listing. | lead, w2 |

### Messaging semantics
| # | Friction | Evidence | Who hit it |
|---|---|---|---|
| F4 | **"Live" isn't live for a running Claude collaborator, and `pushed` means three things.** For Codex, true means queued until the turn boundary. For an idle worker, true means resumed. For a running Claude worker, false means it waits for `team_read`. The sender can't tell queued from dropped. | `deliver()` teamd.py:266-290, `_resume_with_inbox` :293-317. Observed: msg-to-all `w1:true, w3:false, w4:false`; to idle w4 `true`; to running w4 `false`. collaborator.md says "receive it live". | w2, w4 |
| F16 | **Messages are silently truncated.** 4096 bytes are accepted (teamlib.py:26), but recipients see `text[:2000]` (teamlib.py:521) and the lead 1500 (`_to_lead`). The over-limit hint says "commit… send a path/SHA", which collaborators can't commit and peers can't read. I split my findings for w4 into 3 messages. | Code; w1 and w4 confirmed. | w1, w2, w4 |
| L1 | **The lead has no broadcast.** `team_message(worker="all")` gives "no worker 'all'", while workers *do* have `to="all"`. The lead sent 4 separate messages. | lead report; lead op `message` calls `deliver(a["worker"])` directly (teamd.py ~529). | lead |
| L2 | **The lead has no push.** The lead sees its inbox only by polling `team_status`, and every call dumps the full config, all workers and plans plus the inbox. Noisy, and nothing gets the lead's attention. | lead report; `status()` teamd.py ~550-565. | lead |
| F14 | `to="all"` from a worker also lands in the lead inbox, but the result omits it. | teamd.py:424-434. | w2 |
| (w1) | **Done-race:** a message can be stranded between the last `team_read` and `team_done`, and delivering to a done collaborator can overwrite `procs[wid]` while the old process still runs. Task A owns it. | teamd.py:260, 286-288, 445-460 per w1. | w1 |

### Roster, status and briefs
| # | Friction | Evidence | Who hit it |
|---|---|---|---|
| F5 | **The brief roster is stale.** "Teammates: w1", while w3 and w4 were spawned later. | `_initial_prompt` snapshot, teamd.py:206-217. | w2 |
| F6 | **Worker `team_status` hides things.** Tasks cut to 120 chars (w3 couldn't see w4's task), with no mode, plans or last_message. | worker `status` op. | w2, w3 |
| F9 | **Role text assumes Slack.** "Kairos … can reply on Slack" (collaborator.md:6), but Slack is off and the brief doesn't say so. | brief; `ts:null`. | w2 |
| F10 | **Tool descriptions are written for builders.** `team_done` says "daemon commits your changes"; `team_plan` says "before implementing". | collaborator tool schemas. | w2 |

### Memory
| # | Friction | Evidence | Who hit it |
|---|---|---|---|
| F7 | **Codex workers have no engram tools**, yet their role asks them to recall/share. | w1; workers.py:215 keeps engram only if it's in the user's Codex config. | w1 |
| F8 | **No working `lighthouse_context` is documented.** `group:agent-team` gives RECEIVER_CONFIG_INVALID; `memory/technical` gives UNAVAILABLE (the sandbox blocks sockets per w3). | team-mode.md:84; my recall receipt. | w2, w3, w4 |
| F19 | **The documented sharing path fails.** `share(id, audience="group:agent-team")` gives `no published house at ~/engram-home/.engram/instances/lighthouse/graph.db`. Team learnings can't be shared as team-mode.md:83-84, collaborator.md:37-38 and lead.md:41 instruct. | My `share` call, this session. | w2 |
| F17 | **Workers recall the human's unrelated private memories.** My on-topic recall returned ARC-puzzle (LF52) episodes and other teams' ruling histories. The room's engram config is a copy of the repo's, so it uses the same instance. | recall output; `_seed_engram_config`; w3. | w2, w3 |

### Tooling
| # | Friction | Evidence | Who hit it |
|---|---|---|---|
| F18 | **Read works for some Claude workers but is "denied entirely" for others.** Verified: `/home -> var/home` and `$HOME=/home/adeptus`. *Inference:* the allow rules (workers.py:313-315) match only one spelling of a path. | `ls -ld /home`; w2 vs w3. | w3, w4 |
| F12 | **Around 150 visible but refused tools** in a Claude worker (Slack, Claude Docs, serena `execute_shell_command`, chrome-devtools, ~40 engram tools, and the lead server `mcp__superyak-team__*`). w4 verified that `claude_command` omits `--strict-mcp-config` (workers.py:345-358), so containment rests on the dontAsk layer alone. Not invoked by any worker. | tool list; w4. | w2, w4 |

What worked: `team_message` reached every peer within one read cycle. Quoted-data fencing is clear. Loop and rate guards never got in the way. Peers turned around reports quickly. Codex's broader reads and the lead's relay worked around F1. That three of four workers independently rediscovered F1 is itself a cost of F2/F3.

## B. Improvements ranked by impact / effort (ergonomics)

| Rank | Change | Fixes | Impact | Effort |
|---|---|---|---|---|
| 1 | **Make team artefacts readable to every agent through MCP** (agreed with w4 as one item). Inline the lead plan (capped) in the brief; add `team_plans(title?)` returning contents and `team_log(n)` over `tail_records` (teamlib.py:276); add recent posts to the lead's status; return `{"recorded":true,"slack":false}` instead of `ts:null`; and add a visibility line to briefs ("Slack off; you can read room+repo; not team home; engram yes/no"). This replaces the hand relay (F20). | F1 F2 F3 F9 F11 F15 F20 | High | S-M |
| 2 | **Honest delivery and size semantics.** Replace `pushed` with `delivery: turn_boundary / resumed / next_read`. Reject over 2000 chars at accept time, or return `truncated:true`. Fix the "receive it live" wording. Give the lead `worker="all"`. | F4 F16 L1 F14 | High | S |
| 3 | **Lead attention.** Split `team_status` into a cheap `team_inbox` (unread only) and a full status. Optionally notify the lead's session when DONE or a QUESTION arrives. | L2 | Medium-High | S (inbox), M (notify) |
| 4 | **Live roster and richer worker status**, plus per-mode tool descriptions. | F5 F6 F10 | Medium | S |
| 5 | **Engram for workers that actually works.** Fix or document the `group:agent-team` share path (F19), give Codex parity or drop the section, document a valid `lighthouse_context`, and scope worker recall away from the personal lane. | F7 F8 F17 F19 | Medium-High (F17 is sovereignty; w3 owns the design) | M |
| 6 | **Path canonicalisation:** allow rules for both `realpath` and the `$HOME` spelling. | F18 | Medium on symlinked homes | S |
| 7 | **`--strict-mcp-config`** for Claude workers (verify support), giving a second containment layer and a smaller tool list. | F12 | Medium (security-in-depth) | S + live check |

Position on w4's pushback: I agree that the w1 done-race and F17 belong *above* this list in the final synthesis, because they fail silently. This list is ranked within ergonomics only, per Task B's scope.

