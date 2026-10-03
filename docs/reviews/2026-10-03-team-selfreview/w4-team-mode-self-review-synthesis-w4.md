# Team mode self-review: synthesis (w4)

Status: **v5, final.** All four documents are integrated and cited by path.

## Sources
- **Lead plan:** `.claude/team-relay/selfreview/lead-team-mode-self-review-plan.md`
- **[A]** w1, "Task A — correctness and failure modes (w1)": `.claude/team-relay/selfreview/w1-task-a-correctness-and-failure-modes-w1.md`. 14 findings, A1–A14; IDs below follow that document.
- **[B]** w2, "Task B: team-mode dogfooding friction log": `.claude/team-relay/selfreview/w2-w2-task-b-team-mode-dogfooding-friction.md`
- **[C]** w3, "Task C: layered channels for Superyak engram (fast lanes + lighthouses)": `.claude/team-relay/selfreview/w3-task-c-layered-channels-for-superyak-eng.md`

The relay is the lead's manual workaround, and the files sit untracked in the repo. Originals are under `~/.superyak/team/teams/selfreview/plans/`.

Evidence key:
- **V**: I re-checked it myself (file:line or command).
- **T**: a teammate's report I haven't re-checked.
- **I**: my inference.

## 1. What this run showed
- **Content worked; paths didn't.** Coordination worked wherever the daemon carried *content*: team_message, fenced delivery, and loop guards that never got in the way. It broke wherever team mode handed out a *path* or assumed Slack.
- **The lead had to route around it.** The lead mirrored plans into the repo every 15 s by hand (`.claude/team-relay/`). That is the strongest evidence for #1. It must not become the fix: it writes transcripts into the repo, and `git status` shows `?? .claude/` ([B] F20).
- **The daemon itself has problems.** Its process lifecycle and state persistence aren't safe under the concurrency a busy team produces, and the Codex worker lockdown can fail open ([A]).
- **The mock suite misses all of this.** The suite passes, but it doesn't exercise these interleavings ([A] conclusion).

## 2. Top 5 changes, ranked by impact over effort

| # | Change | Fixes | Evidence | Effort |
|---|---|---|---|---|
| 1 | **Serve team artefacts through the daemon, not paths.** Add worker tools `team_plans(title?)` and `team_log(n)` (over `tail_records`, teamlib.py:276). Inline the lead plan, capped, in the brief. team_post returns `{recorded:true, slack:false}` instead of `ts:null`. The brief gets a visibility line (Slack on/off, readable paths, engram yes/no) and a live roster. Keep the sandbox unchanged. | [A] A9; [B] F1–F3, F5, F6, F9–F11, F15; [C] F4 | V: workers.py:339 denies $HOME. publish_plan writes only to the team home (teamd.py:376-406). say() writes only to messages.jsonl (teamd.py:65-78). 3 of 4 workers hit this independently. | S |
| 2 | **One lock, one scheduler, and owned processes for the daemon.** (A2) Every state mutation and save() runs under `self.lock`, with a unique tmp name. (A3) `done_pending` until the process exits; never start a turn while a process generation is live; commit at exit; check the inbox on exit. (A4) Every initial and resumed turn goes through one max_workers scheduler that counts live processes. (A7) TERM, then a bounded wait, then KILL and reap before removing files; no `_fill_slots` during end; revoke stopped workers' tokens. | [A] A2, A3, A4, A7 | V: fixed `state.json.tmp` (teamd.py:50-53), saved unlocked from worker_message (:415-434) and ask_lead (:543-546) on ThreadingUnixStreamServer threads. worker_done sets done mid-turn (:445-460). :286-288 resumes a done collab, and :260 overwrites `procs[wid]`. `_resume_with_inbox` ignores max_workers (:292-317 vs :199-204). stop_worker pops the handle and sends TERM without waiting (:591-603), then end() removes worktrees (:605-616). T: [A] probes reproduced the save race, the overlap, and 2 live processes at max_workers=1. | A2 S; A3, A4, A7 M |
| 3 | **Fail-closed worker tool surface for both kinds.** Codex: parse with tomllib, fail closed on read or parse errors, and ideally build a minimal worker config instead of disabling the user's config entry by entry. Claude: load only the team and engram servers (`--strict-mcp-config` if supported, with engram listed explicitly), and add Read/Grep/Glob allow rules for both the realpath and the `$HOME` spelling. | [A] A1; [B] F12, F18 | V: the regex at workers.py:193 misses a valid header with a trailing comment (`[mcp_servers.slack] # hi` doesn't match, tested). The disable loop is opt-out (:243-244), so that server stays on for Codex workers, which is egress. claude_command omits strict MCP (workers.py:345-358), so the lead's `superyak-team` server loads in workers (it's in my own tool list), and only the dontAsk allowlist (:314-315) contains it. I didn't invoke it, by design. | S (parse); M (minimal config) |
| 4 | **Scope worker memory and make the memory path honest.** (a) Worker recall defaults to `lane="work"`, or whatever Kairos picks in Q1. This **must land before** Codex gets engram. (b) Fix docs/team-mode.md:84, roles/collaborator.md:38 and lead.md:41: `group:*` is an *audience*, `lighthouse_context` is a *path*, workers can't read neighbors, and share needs a published house. (c) neighbors.py:192 reports the real error code. (d) Check which tools the worker actually has, and include the memory section of the brief only if engram is present. | [A] A12; [B] F7, F8, F17, F19; [C] F1–F3 | V: SEGMENT at lighthouse_receiver_config.py:14 rejects ':'. The repo's `.engram/config.toml` has no `instance`, and teamd.py:111/120 copies it, so it falls back to ENGRAM_DEFAULT_INSTANCE (config.py:359). My recall in this room returned personal-lane memories. T: share fails with "no published house" (w2). Engram isn't configured for Codex at all (w1, tomllib). | S–M |
| 5 | **Honest delivery.** Replace `pushed` with `delivery: next_read / turn_boundary / resumed`. Reject at the *delivered* cap, or return `truncated:true`. Don't mark messages read until the launch succeeds. Fix "live" in docs/team-mode.md:30 and collaborator.md. List the lead in to=all results. Full message IDs, ACKs and idempotent retries come later. | [A] A8 (small start); [B] F4, F14, F16 | V: deliver() has no branch for a running Claude worker (teamd.py:267-290). MAX_BYTES is 4096 (teamlib.py:26), but fence_external delivers `text[:2000]` (:521) and the lead sees only 1500. T: [A] probe shows a 2013-character message losing its tail while still marked read. | S |

**Why this order.**
- #1 hit every Claude worker and forced the lead to build a workaround.
- #2 can corrupt `state.json`, orphan processes, or break the memory budget under normal team traffic.
- #3 is a security property that fails open after a harmless config edit.
- #4 is cheap; the current docs send agents into three dead ends, and it carries an ordering constraint.
- #5 is a few lines and removes ambiguity.

By raw severity, #2 and #3 rank above #1. #1 leads only on impact over effort (see Q6).

### Next tier (real and verified, but needs more design or matters less often)
- **A5: team IDs are global, but the duplicate check is per repo.**
  - Evidence: mcp.py:97, teamlib.py:181/372, teamd.py:627. (V)
  - A second daemon loads the first one's state and unlinks its socket.
  - Fix: a repo-scoped instance ID plus an owner lock. M.
- **A6: restart doesn't reconcile running workers.**
  - Evidence: process maps start empty at teamd.py:34-35. (V code; T consequence)
  - Fix: persist process generations, verify identity before killing, then requeue. M–L.
- **A10: allowlisted Slack replies to the lead aren't fenced.** (V)
  - Evidence: teamd.py:490-491. Every allowlisted user is labelled "kairos (slack)". Status and collect skip redaction.
  - Only relevant with Slack on. Fix: fence everything, keep real Slack user IDs, and redact every output. S.
- **A11: Linux master-key creation isn't serialized.**
  - Lookup failure is treated the same as "absent", and the 5 s start deadline is shorter than the 60 s keyring unlock. (T)
  - This is an availability problem, not a forgery problem. M.
- **A13: peer escalation never clears.**
  - Fix: a lead reset with an audit record. S. (T)
- **A14: the wheel install lacks its launcher.**
  - Low, packaging. (T)

## 3. Not now (and why)
- **Topic channels (L2)** ([C] §5.2): with 4 workers we saw no interleaving, and [B] has no entry for it. Revisit at 6 or more. w3 agreed.
- **Beacon harvest at team_end** ([C] §5.3): depends on Q1. If workers keep the shared instance, `remember` already *is* the bridge. w3 agreed and sequenced it after Kairos's decision.
- **The 7-layer channel model as a roadmap** ([C] §2): keep it as vocabulary only. The useful part is the distinction between audience and context.
- **Full message receipt protocol** ([A] A8 full fix: IDs, ACK, idempotency): ship the small start in #5 first, and build the protocol only if messages are still lost.
- **SignalBus as a channel** ([C] §1.5, F5): it ingests messages without consent, doesn't authenticate senders, and loses broadcasts. teamd already does the fast lane. Fixing SignalBus is engram hygiene, outside team mode.
- **Cross-machine lighthouse, signatures, community curators:** required before anything crosses a community boundary, but no team-mode need for them today.
- **Widening sandboxes** to the team home or the lighthouse socket: #1 removes the need, and the isolation is the product. [A] A9 agrees.
- **Unread-count hooks and push to the lead:** see whether #5 plus `team_log` are enough first.
- **Exempting the engram plugin from the Codex disable loop:** I proposed this, and w1's check refuted it for this session. Use the preflight in #4d instead.

## 4. Lens check
- **Wing-flapping (observe first).** Every top-5 item is a failure observed in this run, or a code path re-read by at least two of us. Topics and beacons came from prior art, not observation, so they're not-now.
- **Platform, not rule-maker.** #1, #3 and #5 give agents truthful, bounded mechanisms and don't prescribe how a team must talk. A channel taxonomy would have been a rule.
- **Copy the principle, not the mechanism.** [C]'s principle, "nothing moves down a layer except by an explicit act with a reason", stays. Today's shared instance violates it, and #4 addresses that. Zulip, Matrix and SSB mechanisms aren't copied.
- **Step back.** The lead's manual relay shows the team will route around a missing primitive. Fix the primitive rather than formalising the workaround.
- **Diversity.** The Codex reviewer (w1) found every lifecycle, concurrency and keyring bug. The three Claude reviewers converged on ergonomics and memory. Model diversity paid off here, so keep a different-model correctness reviewer in future self-reviews.

## 5. Risks
- **#2 touches the daemon's core under concurrency.** It needs mock-agent tests in `make check-team`:
  - a concurrent message plus a monitor save;
  - a message arriving between team_done and process exit;
  - max_workers=1 with a resume;
  - a stop where the process ignores TERM.

  Don't hold the lock across Slack network I/O in say().
- **#3 fail-closed** will refuse to start on machines whose Codex config doesn't parse. That's intended, but the error must say why, as the Linux keyring refusal does today.
- **#3 strict MCP** could silently drop engram for Claude workers. Needs one live check per platform.
- **#4 lane=work** could hide useful work history that's mislabelled personal. A per-team instance would also cut workers off from project lessons that helped this run (e.g. the lighthouse-pub "relay full ruling text" episode). Hence Q1.
- **#4 ordering:** giving Codex engram before the lane decision would send personal-lane memories to a second vendor. Today that doesn't happen, because Codex has no engram (corrected after w3's pushback).
- **The relay** (`.claude/team-relay/`, untracked in the repo) could be committed by accident. Remove it after #1, or gitignore it.
- **Reviewer bias:** 3 of 4 reviewers were Claude, so Codex-side ergonomics are under-sampled.

## 6. Open questions for Kairos
1. **Worker memory scope.** Should team workers recall your *personal* lane, or the whole main instance at all? Options:
   - (a) as now;
   - (b) a lane=work default;
   - (c) a per-team instance plus a lead-curated injection.

   This decides whether Codex should get engram.
2. **What is `group:agent-team` for?** Cross-team learning that the *lead* reads at team start, or something teammates read mid-run? Today it can't be written (no published house) or read (no socket). The answer decides whether beacons are ever needed.
3. **Is Slack-off the normal mode?** #1 holds either way, because Claude workers can't open canvases, but it's most urgent with Slack off.
4. **SignalBus:** retire its auto-ingestion, or leave it outside team mode as it is?
5. **Who may curate lighthouse content** that leaves the machine, especially for community partners? You only, the lead with your approval, or a curator from the publishing community?
6. **Fix order:** take #2 and #3 (correctness and security) before #1 (ergonomics), even though #1 has the best impact over effort? My recommendation: A2 (S) and A1 (S) first, then #1, then the M-sized lifecycle work.

