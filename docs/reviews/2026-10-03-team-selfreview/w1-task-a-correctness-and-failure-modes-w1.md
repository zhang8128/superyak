# Task A — correctness and failure modes (w1)

# Task A: correctness and failure modes

Reviewed 2026-10-03 by w1 (Codex), read-only. Repository: `/var/home/adeptus/Projects/work/superyak`. All source references below are relative to that root. No code changed, real credentials accessed, agents launched, worktrees created, or heavy test suite run.

**Conclusion:** the current daemon has high-confidence lifecycle, concurrency and delivery defects, plus a fail-open Codex tool-discovery case. The passing mock suite does not cover the relevant interleavings. Fix the daemon's ownership and scheduling contracts before building a more capable channel layer.

Evidence labels: **probe** = lightweight in-memory reproduction against imported production methods, with processes/files/keyring mocked; **source** = verified control flow, runtime impact inferred; **live** = observed in this self-review. High means safety boundary bypass, persistent corruption/orphaning, or substantial resource-limit failure; Medium means lost/misleading coordination or recoverable operational failure; Low means limited packaging/contract friction. No Critical finding is claimed.

## Ranked findings

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| A1 | High | Valid Codex TOML can evade tool/provider disabling | probe + source |
| A2 | High | Threaded daemon mutations and fixed temporary save file race | probe + source |
| A3 | High | DONE precedes process exit: overlapping turns and stranded messages | probe |
| A4 | High | Resume bypasses worker cap; task state undercounts live processes | probe |
| A5 | High | Global team ID collides across repositories and concurrent starts | source |
| A6 | High | Daemon restart cannot recover ownership of persisted live workers | source |
| A7 | High | Stop/end do not ensure worker death before discarding tracking/worktrees | source |
| A8 | Medium | Delivery consumes truncated content without receipt ACK or dedup | probe + source |
| A9 | Medium | Offline plans/posts are unavailable through worker tools | live + source |
| A10 | Medium | Lead Slack input bypasses fencing; status/collect bypass redaction | source |
| A11 | Medium | Linux master creation can replace a key; client startup deadline is too short | source + local manual |
| A12 | Medium | Worker brief requires memory tools that were never provisioned | live + source |
| A15 | Medium | Partial spawn leaves an unregistered worktree and blocks retry | probe + source |
| A13 | Low | Peer escalation is permanent with no reset operation | source |
| A14 | Low | Installed wheel omits launcher used by daemon and worker MCPs | source |

### A1 — Codex discovery is fail-open for valid configuration

**References:** `team/superyak_team/workers.py:193`, `:206`, `:239`, `:243`, `:245`; security claim `docs/team-mode.md:95`.

**Failure scenario:** a configured provider has the valid header `[mcp_servers.egress] # normal comment`, or a plugin header `[plugins."egress@source"] # normal comment`. TOML accepts both, but the regex requires end-of-line after the closing bracket and discovers neither. No disabling flag is generated. An already enabled/approved provider remains exposed, defeating the egress isolation claim for Codex workers, which can read broadly. Inline tables, single-quoted keys and other valid TOML forms also merit coverage. The probe confirmed parseable headers yield empty discovery sets; no actual external provider was called.

**Fix:** use `tomllib` and fail closed on parse/read failure. Construct a minimal worker configuration containing fixed team/engram identities instead of inheriting arbitrary provider state where feasible. Verify the final effective tool inventory; configure only required tools. Effort S for parsing, M for isolated configurations.

**Related Claude boundary:** `workers.py:348` and `:356` supply a team MCP config but omit `--strict-mcp-config`; user/plugin servers can still load. The allowlist restricts calls, but `docs/team-mode.md:76` itself documents that an inherited lead server named `team` can expose lead-identity tools under the allowed names. This conditional weakness needs a fail-closed launcher, not only a naming warning. Not independently exploited here.

### A2 — Threaded requests race state mutation and persistence

**References:** `team/superyak_team/teamd.py:50`, `:419`, `:432`, `:463`, `:498`, `:543`, `:642`.

**Failure scenario:** `ThreadingUnixStreamServer` handles a worker question while the lead reads status or the polling loop updates state. Several paths mutate state/call `save()` outside `self.lock`. Both writes use `state.json.tmp`; one replace removes that path and the other replace fails. Serialization can also observe concurrent dictionary mutation, and concurrent writes to the same temporary inode can leave an inconsistent snapshot. The in-memory fake-filesystem probe forced two overlapping saves and reproduced a missing temporary path on the second replace (real filesystem equivalent: `FileNotFoundError`).

**Fix:** require the same RLock for every state mutation, snapshot and save, including polling and worker-to-lead paths; retain atomic replacement, with unique temporary filenames as extra protection. Serialize dispatch or split external network calls from a locked state/outbox transaction. A failed RPC must not leave an unreported half-committed operation. Effort S–M.

### A3 — DONE is conflated with process death

**References:** `team/superyak_team/teamd.py:260`, `:286`, `:309`, `:337`, `:445`.

**Failure scenario 1 (probe):** a running collaborator calls `team_done`, so its state becomes `done` while its process still waits for the MCP response or writes its final answer. A teammate immediately sends a message. `deliver()` resumes a done collaborator, and `_start_turn()` overwrites `self.procs[wid]`. The old process is alive but no longer monitored; two processes may use the same session concurrently. Its exit/answer is no longer separately attributable.

**Failure scenario 2 (probe):** a message arrives after the collaborator's last `team_read`, before `team_done`. It stays unread because the worker was running. The subsequent monitor sees `done`, skips the `state == running` resume block, removes the exited process, and leaves that message stranded. Another message may later wake it, but the original message alone will not.

**Builder consequence:** `worker_done` commits while the agent process is live; edits after the call are absent from the reported commit.

**Fix:** record `done_pending` and result metadata; finalize only after the current process exits. Guard startup with a tracked process/generation invariant, defer any wake while that generation exists, and check pending inbox on exit even when completion was requested. Commit only at the finalization boundary (or explicitly prohibit and detect post-DONE edits). Effort M.

### A4 — Resumes bypass the resource cap

**References:** `team/superyak_team/teamd.py:196`, `:199`, `:249`, `:292`, `:315`, `:343`.

**Failure scenario (probe):** with `max_workers=1`, w1 is running and w2 is idle. A lead message to w2 invokes `_resume_with_inbox` directly and produces two tracked live processes. Several idle collaborators can be woken at once; monitor-driven resumes also skip the initial queue scheduler. Additionally, workers marked `done` are excluded from `_running_count` even while their processes are alive. This materially violates the self-review's 6 GB memory constraint.

**Fix:** one scheduler for every initial and resumed turn; queue resumptions with their pending message IDs. Count actual live process generations, including `done_pending`, rather than only task states. Preserve fairness without draining an inbox before its slot is allocated. Effort M.

### A5 — Team names are global but duplicate checks are repository-local

**References:** `team/superyak_team/mcp.py:95`, `:97`, `:102`; `teamlib.py:181`, `:372`; `teamd.py:40`, `:627`, `:667`.

**Failure scenario:** repository A runs a team named `review`; repository B starts `review`. B's active-team list does not contain that name, so a second daemon starts in the same global team directory. It loads A's state while `self.repo` is B, overwrites the PID file and unlinks A's socket. The daemons share tokens, state/temp files and worker directories. Even one repo can race two starts because there is no daemon ownership lock. Default names use only goal slug and minute, making collisions plausible. Restarting an ended name also revives retained historical state without an explicit new/recover distinction.

**Fix:** internal ID includes repository identity plus a unique team-instance ID; display name remains human-readable. Acquire an owner lock before loading state or touching PID/socket; verify repository binding. Distinguish recovery from starting a fresh instance. Lock active/current registry updates too (`teamlib.py:226`, `mcp.py:113`). Effort M.

### A6 — Restart retains task states but loses process ownership

**References:** `team/superyak_team/teamd.py:34`, `:40`, `:318`, `:345`, `:648`, `:672`; narrow existing restart test `team/tests/test_team.py:271`.

**Failure scenario:** the daemon crashes or is killed while workers/prepares are running. Workers have their own sessions (`workers.py:87`, `:375`) and can outlive it. Restart loads their `running`/`preparing` state but initializes both process maps to empty. Monitor, timeout and stop consult those maps, so the persisted PID is not supervised or terminated. States can remain stuck indefinitely. Persisted queued workers are not initially scheduled either: monitor fills slots only if it observes a tracked process change. There is no signal/finally cleanup for abrupt daemon termination. The restart test verifies only an idle worker's session ID survives.

**Fix:** persist owned process-generation metadata and reconcile on startup. Verify process identity/start time before terminating anything (PID reuse matters); either reconnect safely or terminate/reap and move to a recoverable state. Resume preparation/queues deliberately. Add signal/finally cleanup and parent-death handling where available. Effort M–L.

### A7 — Stop/end discard handles before termination is assured

**References:** `team/superyak_team/teamd.py:185`, `:328`, `:591`, `:598`, `:603`, `:606`; `workers.py:131`, `:132`; worker auth `teamd.py:504`, `:556`.

**Failure scenario:** a worker ignores SIGTERM. `stop_worker` removes its handle then sends TERM without waiting/escalation; it can keep running untracked. Timeout sends TERM on every monitor pass forever instead of escalating. `end` then force-removes worktrees/rooms while a process may still use them. Calling stop during end runs `_fill_slots`, so queued workers can start during teardown. Dirty/untracked worker changes are discarded by `git worktree remove --force`, although only previously committed branch content survives. Removal failure is ignored. Stopped workers retain usable tokens and can still submit messages/DONE until team end.

**Fix:** set team/worker stopping state before cleanup; suppress scheduling; TERM, bounded wait, KILL and reap every group before removing its files. Revoke/disable stopped caller capabilities. Reuse a corrected kill-group helper (ensure final wait after KILL). Preserve dirty/failed worktrees by default unless discard is explicit; check removal results. Effort M.

### A8 — Delivery has silent truncation and no receipt contract

**References:** `team/superyak_team/teamlib.py:240`, `:521`, `:524`, `:529`; `teamd.py:282`, `:309`, `:547`, `:551`, `:564`, `:567`; `workers.py:403`.

**Failure scenarios:**
- **Probe:** a 2013-character message passes the 4096-byte send limit, but its `CRITICAL_TAIL` after character 2000 is missing from both Codex queue and `team_read`. Read is still set true. Lead notices truncate further at 1500. A missing final qualifier/constraint is treated as consumed, with no truncation notice or retrieval reference.
- **Probe:** resume marks messages read before process launch. A missing binary/launch failure leaves them read although no agent saw the prompt.
- **Source:** `team_read` and lead `team_status` persist consumption before the socket response arrives. Broken pipe, client crash or a second lead client consumes the only unread view. No message ID/ACK/independent cursor enables recovery via tools.
- **Source:** a running Codex message is queued while staying unread; read or explicit resume can also deliver it. A successful queue has no receipt/dedup linkage to either path, so repeated or stale instructions are possible.
- **Source:** RPC timeout is 30 seconds while queue subprocess timeout is 60. Requests can complete after the client sees failure; a retry has no idempotency key.
- **Source:** messages for queued/preparing workers are absent from the initial prompt and wait for a read or another turn. Broadcast excludes done collaborators (`teamd.py:427`), although targeted messages can wake them.

**Fix:** stable message IDs with delivery state and explicit receipt ACK; reads return complete content or explicit truncation plus an accessible full-content reference. Commit consumption after receipt, use idempotent retries, and choose one canonical dispatch mechanism per generation. Document a bounded at-least-once contract rather than implying exactly-once/live. Effort M. Start small: full-content read, visible truncation, and defer read marking until launch succeeds.

**Channel facts for w3:** `team_message` stores a JSONL transcript record plus an inbox item in `state.json`; peer messages to builders are pull-only. `team_post` records a post and best-effort Slack delivery, without recipient inboxes. Running Claude collaborators receive no live push branch; they read messages or get an exit-time resume. Codex queue lands at a turn boundary according to the code comment, not as guaranteed immediate steering. Lead messages/questions use lead_inbox plus global consuming status cursor. Team-end retains team state/transcript/plans while removing rooms/worktrees. A durable transcript alone does not provide delivery ACK, replay or user-readable artifact access.

### A9 — Offline artifacts are write-only for Claude peers

**References:** `team/superyak_team/teamd.py:381`, `:388`, `:403`, `:577`; `workers.py:339`; `mcp.py:196`; role `roles/collaborator.md:11`.

**Failure scenario (live):** w2/w3/w4 could not read the lead-plan path because it lies under the denied team home. Slack was off, so published plans had no canvas link. Worker tools offer no plan/document read API, and worker status omits plans. Posts go to messages.jsonl/Slack without the lead inbox; lead status lacks posts. Codex w1 could read the file, showing an asymmetric contract. Sending full plans as messages hits A8. The lead added a temporary 15-second repo relay at `.claude/team-relay/selfreview/`, which made artifacts readable; this is a session workaround, not an existing product feature.

**Fix:** daemon-backed `team_read_plan` (or list/read artifacts) scoped to the authenticated team, and a nonconsuming transcript/progress read. Include local artifact IDs/paths in status. Do not grant Claude read access to the entire token-bearing team home. Effort S–M.

### A10 — Lead input/output bypasses advertised fencing/redaction

**References:** `team/superyak_team/teamd.py:490`, `:491`, `:569`, `:575`, `:581`, `:584`, `:589`; `teamlib.py:513`; claim `docs/team-mode.md:101`.

**Failure scenario:** an allowlisted Slack reply to the kickoff thread is appended to the lead inbox raw, unlike worker-targeted replies and worker-to-lead text. It can pose as an instruction or forged team text without the advertised quoted-data wrapper. Every allowlisted user is mislabeled `kairos (slack)`, losing actual authorship. Separately, raw agent last_message and DONE summary/tests return through status/collect even though say() redacts the corresponding posts. A secret-shaped accidental final output can cross that boundary unmasked.

**Fix:** preserve authenticated Slack user IDs and reconcile the fencing contract with intended human steering. Fencing can coexist with genuine human authorization; an allowlist should not silently relabel any sender as Kairos. Human authorization policy must be explicit rather than inferred from that label. Redact every daemon/MCP output surface with the same renderer, including collect/status/error responses. Retain originals only where local retention policy allows. Effort S.

### A11 — Secret Service creation is not serialized, and startup can outlast its caller

**References:** `team/superyak_team/teamlib.py:441`, `:445`, `:452`, `:458`, `:463`; macOS contrast `:425`; `mcp.py:102`, `:107`, `:112`; `teamd.py:663`.

**Failure scenario:** Linux lookup conflates not-found with timeout/OSError/nonzero exit. It then runs store, even when a key already exists but lookup transiently failed. Two first-time callers can both lookup empty and then update the same key with different values; re-reading does not make the two stores atomic. The installed secret-tool manual explicitly says matching attributes update an existing item (`/usr/share/man/man1/secret-tool.1.gz`, decoded line 59). Tokens computed on opposite sides of replacement fail authentication. This is availability loss, not evidence of token forgery. macOS add does not use update mode, but also needs serialized initialization/error reporting.

Separately, Linux lookup/store each allow 60 seconds for unlock, while team_start waits only five seconds for daemon_alive. Even optional Slack-token lookup can take ten seconds. A normal unlock or slow store reports start failure while the daemon later starts without active-team registration; retry can cause A5.

**Fix:** lock master initialization across processes; distinguish absent key from store-unavailable and fail closed on uncertainty. Separate creation from normal auth reads, never rotate implicitly. Expose startup progress/readiness with a deadline matching unlock, track the spawned daemon, and prevent duplicate retries with the ownership lock. No live keyring operations were run. Effort M.

### A12 — Memory instructions exceed actual worker capabilities

**References:** `team/superyak_team/workers.py:239`, `:245`, `:268`; `roles/collaborator.md:35`; `roles/worker.md:32`; `engram/server.py:2082`; `docs/team-mode.md:81`.

**Failure scenario (live):** Codex w1 has no callable recall/remember/share/lighthouse tools. Config was parsed with tomllib, printing only installation metadata: no raw engram MCP table and no engram plugin entry. So plugin suppression does not explain this particular session. Generally every enabled Codex plugin is disabled, so a plugin-only Engram install would also be removed. Claude permits only four Engram tools yet the brief speaks of lighthouse shared retrieval without supplying an actual valid receiver context. w4 observed RECEIVER_CONFIG_INVALID; a group share audience is not automatically a lighthouse_context (the recall tool documents e.g. memory/technical).

**Fix:** preflight fixed required tools and render worker memory instructions from capabilities. Provision an explicit Engram server where intended; avoid broadly exempting plugins. Supply a real receiver/context and clearly distinguish share audience from retrieval scope, or omit shared recall until configured. Memory namespace design belongs to Task C. Effort S–M.

### A15 — Spawn has no rollback after creating a worktree

**References:** `team/superyak_team/teamd.py:109`, `:111`, `:121`, `:126`; `workers.py:125`.

**Failure scenario (probe + source):** create_worktree succeeds, then Engram seeding or token issuance fails (e.g. a key-store outage). The worktree and branch already exist but the worker is not yet registered. Team end cannot find it for cleanup; the next spawn reuses w1 and git rejects the existing branch/path. A probe with mocked creation and failing token issuance confirmed creation occurs, registry remains empty, and the next ID remains w1. The same partial-allocation issue can leave collaborator rooms/tokens behind.

**Fix:** reserve a worker ID in a preparing/allocating state, record each allocated resource, and rollback on failure or retain a failed record the lead can inspect/clean. Startup recovery should reconcile partial allocations. Effort S–M. IDs are retained from the first document version, so this late confirmed Medium finding is A15.

### A13 — Peer escalation cannot be cleared

**References:** `team/superyak_team/teamd.py:366`, `:370`; lead tools `mcp.py:155`.

**Failure scenario:** a legitimate pair reaches its 30-minute limit and is appended to escalated. Future messages are rejected even after all timestamps age out. No lead operation removes the escalation; the suggested lead message only bypasses it by changing the sender. Collaboration between that pair is permanently disabled for this team instance.

**Fix:** explicit lead reset with audit record, or documented expiry/cooldown. Keep the loop guard and per-pair budget. Effort S.

### A14 — Wheel installation lacks its internal launcher

**References:** `team/pyproject.toml:16`, `:24`; `team/superyak_team/teamlib.py:201`; `mcp.py:102`; `workers.py:223`, `:350`.

**Failure scenario:** the superyak-team console entrypoint is installed from a wheel, but its reviewed include list omits run_team.py. run_team_path points to package parent/run_team.py; team_start and worker MCPs invoke this missing file. Repository runtime works because scripts/runtime.py points to the source launcher; source-only tests do not verify wheel behavior. Wheel not built here due read-only scope.

**Fix:** put launcher inside the package and include it, or invoke an installed module with an isolated, reliable module path. Test the built wheel in a clean environment during release checks. Effort S.

## Verification and confidence

Read all of team/superyak_team/{teamd,workers,teamlib,mcp,slack}.py, all worker/lead briefs, the Codex team skill as reviewed source, team README, team pyproject, team/tests/test_team.py and mock agents, docs/team-mode.md, and relevant runtime/Engram tool definitions.

Executed **one tiny lifecycle probe** with `PYTHONPATH=team python3 -B - <<'PY'` in the repository. It used object.__new__(Team), fake Popen records, patched launch/commands/persistence/auth, and a fake in-memory filesystem; exit 0, all six groups passed:
1. resume at cap 1 resulted in two live tracked processes;
2. DONE-before-exit replaced an old still-live process handle;
3. deliver-before-DONE left one unread message with no process;
4. failed resume launch left the message marked read;
5. accepted 2013-character content lost its final tail in both queue and read;
6. overlapping saves collided on the one temporary path.

Executed a separate **synthetic TOML discovery probe** via the same Python command form: tomllib accepted commented MCP/plugin headers, discovery returned neither; exit 0. This also printed only boolean/Engram plugin installation metadata, never config values.

Live evidence: team_status/read/message/plan usage; peers' denied plan reads; absent Codex Engram tools; lead's temporary document relay. The lead reported 70 existing mock tests pass; I did not rerun them. Existing mocks log queue success without consuming real queues, and tests typically call DONE only after a worker becomes idle, so they do not establish the failure contracts above.

No real-agent queue, OS sandbox escape, real keyring concurrency, wheel build, daemon crash, cross-repo duplicate start or destructive teardown was exercised. Those are source-backed scenarios; runtime severity should be confirmed by isolated targeted tests before release.

## Smallest coordinated fix set

1. Parse effective worker configuration and launch with fixed tool identities; preflight required capabilities (A1/A12).
2. One state lock, daemon ownership lock and scheduler; separate result completion from process death (A2–A7).
3. Full-content inbox reads, message IDs, explicit receipt/retry semantics and one dispatch path (A8).
4. Authenticated artifact/transcript reads usable offline; use the relay only as a temporary workaround (A9).
5. Central fenced/redacted rendering and serialized key-store initialization/readiness (A10/A11).

Do not build a new messaging transport merely to fix these local state contracts. Task C can layer DMs/topics/broadcasts over a reliable envelope and leave lighthouse publication as deliberate durable sharing.

## Discussion status

Delivery findings sent directly to w3; w4 independently confirmed save, DONE and capacity defects and reproduced the regex discovery gap. w4's proposed done_pending plus process guard is accepted; it also needs pending-inbox checks and slot allocation at exit. Memory-plugin hypothesis was corrected: no Engram installation exists in this Codex config. A9 workaround is live. The integrator accepted the full receipt protocol as explicit follow-on work. A10's human-steering priority challenge was resolved by distinguishing actual human authority from an incorrectly assigned Kairos label. A15 was confirmed afterward with a separate tiny spawn-allocation probe. No unresolved factual disagreement; final team_read will check for new challenges.

## Runnable lightweight reproduction

Run from the repository root. This is a document snippet, not a repository code change. All writes, keyring access and agent launch are mocked; fake paths never touch disk.

```sh
PYTHONPATH=team python3 -B - <<'PY'
import threading
from pathlib import Path
from unittest.mock import patch
from superyak_team import teamd, teamlib, workers

class Proc:
    def __init__(self, pid=100, rc=None):
        self.pid, self.rc = pid, rc
    def poll(self):
        return self.rc

def make(states=('idle',), cap=1):
    t = object.__new__(teamd.Team)
    t.team_id = 'probe'
    t.repo = '/fake/repo'
    t.dir = Path('/fake/team')
    t.lock = threading.RLock()
    t.cfg = dict(teamlib.DEFAULT_CONFIG, max_workers=cap)
    t.procs = {}
    t.prepare_procs = {}
    t.stopping = threading.Event()
    t.state = {'workers': {}, 'lead_inbox': [], 'lead_cursor': 0,
               'kickoff_ts': None, 'goal': 'probe', 'slack_seen': {}}
    for n, s in enumerate(states, 1):
        t.state['workers'][f'w{n}'] = {
            'state': s, 'kind': 'claude', 'mode': 'collab',
            'ident': 'session', 'inbox': [], 'turns': 1,
            'pid': None, 'started_at': 1, 'path': f'/fake/w{n}',
            'thread_ts': None, 'branch': None, 'last_message': '',
            'task': 'probe', 'base': None, 'commit': None,
            'summary': None}
    t.save = lambda: None
    t.say = lambda *a: None
    t.log = lambda *a: None
    return t

with patch.object(teamlib, 'append_record'), \
     patch.object(workers, 'claude_command', return_value=['fake']), \
     patch.object(workers, 'parse_events', return_value=('session', '')):
    seq = iter(range(200, 220))
    with patch.object(workers, 'launch',
                      side_effect=lambda *a: Proc(next(seq))):
        t = make(('running', 'idle'), 1)
        t.procs['w1'] = Proc()
        t.deliver('w2', 'resume despite full capacity', 'lead')
        assert len(t.procs) == 2
        print('resume ignores cap:', len(t.procs), 'processes, cap=1')

        t = make(('running',))
        old = Proc(100)
        t.procs['w1'] = old
        t.worker_done('w1', 'done', 'probe')
        t.deliver('w1', 'new message before old caller exits', 'lead')
        assert t.procs['w1'] is not old and old.poll() is None
        print('DONE-before-exit: old live process handle replaced')

        t = make(('running',))
        t.procs['w1'] = Proc(100, 0)
        t.deliver('w1', 'arrives after final read', 'lead')
        t.worker_done('w1', 'done', 'probe')
        t.monitor_once()
        assert not t.state['workers']['w1']['inbox'][0]['read']
        assert not t.procs
        print('deliver-before-DONE: unread message stranded')

    t = make(('idle',))
    with patch.object(workers, 'launch',
                      side_effect=FileNotFoundError('fake agent')):
        try:
            t.deliver('w1', 'message lost on failed launch', 'lead')
        except FileNotFoundError:
            pass
    assert t.state['workers']['w1']['inbox'][0]['read']
    print('failed resume: message marked read without launch')

    t = make(('running',))
    t.state['workers']['w1'].update(kind='codex', ident='thread')
    queued = []
    with patch.object(workers, 'queue_message',
                      side_effect=lambda ident, text: queued.append(text) or True), \
         patch.object(teamlib, 'get_token', return_value='fake'):
        original = 'a' * 2000 + 'CRITICAL_TAIL'
        teamlib.sanitize(original)
        t.deliver('w1', original, 'lead')
        got = t.handle({'op': 'read', 'caller': 'w1', 'token': 'fake'})
    assert 'CRITICAL_TAIL' not in queued[0]
    assert 'CRITICAL_TAIL' not in got['messages'][0]['message']
    assert t.state['workers']['w1']['inbox'][0]['read']
    print('2013-char message: accepted, silently truncated, consumed')

barrier = threading.Barrier(2)
files, errors = {}, []
class MemoryPath:
    def __init__(self, name):
        self.name = name
    def __truediv__(self, name):
        return MemoryPath(self.name + '/' + name)
    def write_text(self, text):
        files[self.name] = text
        barrier.wait(timeout=3)

def replace(src, dst):
    files[dst.name] = files.pop(src.name)

t = make()
t.dir = MemoryPath('/fake/team')
def save():
    try:
        teamd.Team.save(t)
    except Exception as e:
        errors.append(type(e).__name__)

with patch.object(teamd.os, 'replace', side_effect=replace):
    a, b = threading.Thread(target=save), threading.Thread(target=save)
    a.start()
    b.start()
    a.join()
    b.join()
assert errors == ['KeyError']
print('overlapping save: second replace lost the shared temporary path')
print('Six probe groups passed; no files or real processes created.')
PY
```

The fake filesystem reports KeyError where an actual second os.replace would report FileNotFoundError. This deliberately demonstrates the algorithmic collision without writing files or exercising production state.

