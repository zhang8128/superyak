# Chat paging: build record for the section 2 review

Built subagent-driven on the Mac (Serenity), 2026-10-27: five tasks, each with a spec and quality review, then a final whole-branch review, one fix round (1462e02) and a scoped re-review (clean). This file carries the rulings made during the build and the final review, since the build ledger itself is local.

## Rulings (decision — why — cost if wrong)

- Ruling 1: T1's parser accepts `since` (an integer ≥ 0) and T1's get_room may treat it as an unhandled window (any behaviour, untested) until T2 — the spec lists `since` among the parameters and T2 owns its semantics — cost if wrong: one extra T2 edit to the parser.
- Ruling 2: T3's dispatch carries T1's exact error statuses and texts, so the fake matches the server — the plan says "match the server" without listing them — cost if wrong: a T4 error-wording test passing against the fake but not the station.
- Ruling 3: the `since` query lives in one module constant in chats.py (`SINCE_SQL`), and the index test runs EXPLAIN QUERY PLAN on that constant — a test of a copy of the SQL would prove nothing — cost if wrong: none beyond naming.
- Ruling 4: Task 1's duplicated room-field assembly is refactored into one helper shared by both paths, guarded by a test that pins today's no-parameter key order and serialized bytes, written before the refactor — the plan's "untouched" was a means to byte-identity, not an end; duplication would make every future room field a two-place edit — cost if wrong: a subtle change to the no-parameter response, which the pinned test exists to catch.
- Ruling 5: the fake's seqs[...] lookup raises KeyError for a message appended without say(); Task 4's implementer applies seqs.get(id, 0) if any existing test fixture hits it — Task 4 routes every station_read test through the paged path, so this is the one divergence that could break it — cost if wrong: a seq of 0 for such messages in tests only
- Ruling 6: when any room-independent check fails (types, oldest, at type, more than one mode), station_read falls back to today's full-read path, which fetches the room first and raises in today's order — exact error identity for every multi-fault call, at the cost of one full read for invalid calls only (what they cost today) — cost if wrong: invalid calls stay as slow as today
- Ruling 7: in refreshRoom the answer's copy of a message replaces the shown copy and takes its position (the spec's "keeps the messages already shown, and appends the new ones" is amended to say so) — the spec's merge rule misorders the locally appended accepted message, and the kept copy is the POST's shape — cost if wrong: none found; a since answer can overlap the shown list only in the locally appended message.
- Ruling 8: the server and the fake accept at=0 on an empty room (an empty window, first_position 0); the plan's Task 1 interface yields to its own Review Focus ("an empty room: every paged read returns messages: []") — station_read's own range check keeps today's text for an explicit at=0 — cost if wrong: an HTTP client's at=0 on an empty room gets 200 [] instead of 400 (new API on this branch, no older client depends on it).
- Ruling 9: the final fix dispatch takes I1, I2, M1, M2, M3, M4 and the T5 in-flight-prepend minor; M5 and the rest of the deferred minors stay parked — each taken item is a few lines with a test and touches code this fix already opens — cost if wrong: a slightly larger fix diff to re-review.
- Ruling 10: the two re-review minors are parked — (a) after a sign-out and another member's sign-in on the same page, loadRoute reuses the earlier account's shown messages for the same room (the new account is a member of that room and sees the same messages; only the cached base differs); (b) loadEarlier can overwrite a newer total from a concurrent refresh (cosmetic) — neither is a defect a member could exploit and both are one-line follow-ups — cost if wrong: a shared-device viewer briefly sees a room list built from the previous account's cache until the next refresh.

## Deferred minors (parked, not fixed)

- Task 1: minor (deferred): a remote room with invalid paging parameters gets a 400 instead of being ignored (paging() runs before the remote-key check)
- Task 1: minor (deferred): `at` on an empty room says "between 0 and -1"
- Task 1: minor (deferred): the no-parameter test compares dicts, so key order is unchecked (Ruling 4's pinned test covers it)
- Task 1: minor (deferred): a repeated parameter (limit=1&limit=2) takes the last value silently
- Task 1: minor (deferred): `import re` out of order in app.py
- Task 1: minor (deferred): the tie test has no window starting strictly between two peer rows (at=tie+2)
- Task 2: minor (deferred): no test with more=True and invalid events between/after the batch; no late peer message inside a multi-message since batch; skipped-event test covers one event only
- Task 2: minor (deferred): _since recomputes limit instead of taking _page's
- Task 3: minor (deferred): no tests for the default limit 100, an empty room, system_author on a page, since truncated with more=True, or pages=True with no parameters
- Task 3: minor (deferred): picked compares whole dicts (O(n·limit)); page.setdefault mutates
- Task 4: minor (deferred): a 404 for another reason while an id was asked is reported as "No message …" (resolve_room makes it unlikely); the at-400 is recognised by prefix (brittle to a station reword); render_newest's total is unused (plan signature)
- Task 4: minor (deferred): `limit` is parsed before the invalid-call fallback, so a non-numeric limit raises before other errors, and in message mode (where today it's ignored)
- Task 5: minor (deferred): a since-refresh in flight drops a concurrent loadEarlier prepend (refreshRoom snapshots shown at its start, app.js:536); recoverable, a re-read of state.room after the loop fixes it
- Task 5: minor (deferred): after a send, a message from someone else earlier in event order is appended after the accepted one (the old wholesale replace re-sorted); until reload
- Task 5: minor (deferred): the refresh test's 3-message room doesn't prove the since path; no test for the more loop, dedupe against shown, a failing before/since fetch, or scroll restore
- Task 5: minor (deferred): focus is lost after "Load earlier" (render replaces the button); `more: undefined` dead key at app.js:547

Final review re-graded every deferred minor (below); I1 and I2 were promoted and fixed in 1462e02, with M1-M4 and the in-flight prepend.

## Final whole-branch review (ed3f92f..508166c)


Reviewer: fresh senior review, read-only on the branch checkout. I reviewed it in three passes (server, then agent and
fake, then web app), followed by the cross-seams. I ran probes in a separate scratch worktree at 508166c, plus one at
ed3f92f for a before/after comparison, which I have since removed.

Evidence gathered:
- **Byte identity across versions.** I built one database with the base code. The room held person posts, a ship
  post, a reply, the brief's station notice, a claim note, three peer rows and a local/peer `created` tie. A
  no-parameter `GET` from base and one from head over that same database gave byte-identical bodies (4,244 bytes).
  `?foo=1` was also identical.
- **Agent probe.** Compared `pages=True` with `pages=False` over the FakeStation. Two modes differ; see I2 and M1.
- **Browser probe, head against base.** A message posted by someone else while the reader is typing, then a send
  from the composer. Base shows the right order; head shows the wrong one (I1).
- **Suites at head (scratch worktree).** Agent: 774 passed. Peer: 960 passed, 1 skipped. Focused runs:
  `test_chat_paging.py` + `test_chats.py` 20 passed; `test_station_paging.py` + `test_mcp.py` 75 passed.

### Strengths

- **Today's path is preserved exactly.** `_message_order` reproduces the full read's stable sort as an explicit
  `(created, source, rowid)` key. `_room_fields` puts the shared fields in one place. The `ids` filters on
  `_sources`/`_replies` are minimal and leave the no-`ids` path textually identical. The cross-version comparison
  above confirms byte identity, which is stronger than the head-to-head dict test in the suite.
- **`since` is correct by construction.** It takes the oldest `limit` events. `seq` is the last taken event when
  `more`, else the room's maximum. An event whose message isn't in the room is passed over but still moves the
  cursor. `more` is true only when another valid message remains, so nothing is dropped from below. The index test
  runs `EXPLAIN QUERY PLAN` on the real `SINCE_SQL` constant, not on a copy (Ruling 3).
- **A non-member learns nothing.** Authentication runs first (`member(request)` is evaluated before `paging(...)`).
  Parameter 400s don't depend on the room. Every room-dependent answer (`total`, range texts, unknown-id 404, `seq`)
  comes after `_room`'s membership check. `start`/`after` are matched only against this room's order, so another
  room's message id gets a 404.
- **`station_read` keeps today's error order.** Ruling 6 (fall back to the full read for any multi-fault call) is a
  clean way to keep error precedence. The older-station fallback goes through the same `_read_whole`. The renderers'
  `offset` change is small. `test_paged_and_full_reads_print_the_same` compares 15 modes with paging on and off, and
  is the right shape for a parity test.
- **The fake matches the server's errors.** FakeStation carries the server's exact error statuses and texts
  (Ruling 2), and its station-wide `seq` counter matches the real events id.
- **The web app change is contained.** `loadRoom`, `refreshRoom` and `loadEarlier` are small. Remote rooms and
  non-paged answers keep today's behaviour. Routing the send refresh and the participant-removal refresh through
  `refreshRoom` was necessary: a no-parameter read there would re-download the whole room and un-page `state.room`.
- **The ⚠️ open item is safe** (see the re-grade section).

### Issues

#### Critical (Must Fix)

None.

#### Important (Should Fix)

**I1. After sending from the web app, your message is shown above messages that arrived before it, until you reload.**
`peer/superyak_peer/static/app.js:541` (in `refreshRoom`), together with `:1620` and `:1624` (`sendMessage`).

- **What happens.** `sendMessage` appends the accepted message locally (`:1620`), then refreshes with `since`.
  `withoutRepeats(messages, answer.messages)` keeps the shown copy and drops the answer's copy. Anything that arrived
  between the last read and the send (by anyone) is therefore appended after your own message.
- **Probe.** Room open, family posts "A question while you typed.", patient sends "My answer to it.":
  - head shows `[..., 'My answer to it.', 'A question while you typed.']`; a reload shows the reverse.
  - base (ed3f92f) shows the right order, because the full read replaced the list.
- **Why it matters.** The web app doesn't poll, so this hits nearly every send in a busy room: City of AI, the room
  this branch exists for. The visible timestamps run backwards, and only a reopen fixes it. The kept local copy is
  also the POST's shape (no `source` or `reply_to`, plus `replayed` and maybe `deferred_here`), not the room read's.
  That's invisible for a person today, but it's still the wrong copy.
- **Fix.** Let the answer's copy win and take its position:
  `const fresh = answer.messages || []; const ids = new Set(fresh.map(m => m.id)); messages = [...messages.filter(m => !ids.has(m.id)), ...fresh];`.
  The only overlap a `since` answer can have with the shown list is the locally appended accepted message, so
  nothing else moves.
- **Test.** Add a browser test: with the room open, another user posts, the reader sends from the composer, and the
  shown order equals the order after a reload. The ledger deferred this as a minor; I'm promoting it (see below).

**I2. `station_read oldest=true` on an empty room now fails with a station error instead of the brief.**
`peer/superyak_peer/chats.py:92`, `agent/superyak_agent/mcp.py:223`, `agent/tests/conftest.py:177`.

- **What happens.** `station_read` sends `oldest` as `at=0&limit=N+1`. Both the server and the fake refuse `at=0` on
  an empty room with 400 `at must be between 0 and -1`. `station_read` maps a 400 back only when `at` was given
  (`mcp.py:233`), so for `oldest` it re-raises.
- **Probe.** On an empty room with a brief:
  - today: `Room Empty (r1)\n\n<brief>\n\n(no messages after that one)`
  - head: `station error: 400: at must be between 0 and -1`
- **Why it matters.** The binding Global Constraint is "station_read output, errors included, is identical to
  today's". The plan's Review Focus is "An empty room: every paged read returns `messages: []` …". A ship reading a
  freshly made room (brief, no posts yet) oldest-first gets an error instead of the brief. The trigger is narrow;
  the fix is one line.
- **Fix.** Server and fake should accept `at=0` when `total == 0`, returning an empty window with
  `first_position: 0` (for example `if not 0 <= page['at'] < max(total, 1)`). `station_read`'s own check after the
  read (`if at is not None and not 0 <= at < total`) then still gives explicit `at=0` today's
  "between 0 and -1" text, and `oldest` renders as today.
- **Tests.** Add `{'oldest': True}`, `{'at': 0}` and `{'at': -1}` on an empty room with a brief to the paged-vs-full
  comparison, and an empty-room `at=0` case to the server tests. The test gap is why this slipped: every parity
  test used a non-empty room.

#### Minor (Nice to Have)

**M1. `station_read` wording differs for absurd inputs.** `peer/superyak_peer/app.py:115`, `agent/superyak_agent/mcp.py:233`.
- `at` of 10^15 or more fails the station's 15-digit check. `station_read` prints
  `station error: 400: at must be a whole number, 0 or more` instead of today's `at must be between 0 and N`.
  Verified by probe.
- A `start`, `after` or `message` id longer than 100 characters gets a 400 `start is the id of a message` instead of
  today's `No message '…' in this room`.
- Fix: clamp the `at` sent (`min(at, 10**15 - 1)`; the total check then refuses it with today's text), and map a 400
  on an id parameter to the "No message" wording, as the 404 is.

**M2. The FakeStation pages remote rooms; the server doesn't.** `agent/tests/conftest.py:389`. The fake pages a room
whose id contains `:`, but the server ignores paging for remote keys (`chats.py` `get_room`). A future `station_read`
test on a remote room would exercise the paged path, while production takes `_read_whole`.
Fix: `if query and self.pages and ':' not in room['id']`. This joins the Task 3 ⚠️ divergences: the fake checks the
room before the parameters, and treats blank values as no query.

**M3. A generic refresh drops earlier messages the reader loaded.** `app.js:1128` (`loadRoute`, reached from
`refresh()` at `:1187`, e.g. "Check delivery now" or a retry). It reloads the room with `?limit=100`, so earlier
messages the reader loaded vanish and the button comes back. Before, a refresh redrew the full room.
Fix: in `loadRoute`, when `state.room` is the same room and paged, use `refreshRoom(state.room)`.

**M4. "Load earlier" doesn't de-duplicate at the seam.** `app.js:556`. If positions shift between reads (a row
landing mid-list; on the Pi, a clock that steps back before NTP sync), the boundary message is shown twice.
Fix: prepend `withoutRepeats(state.room.messages, answer.messages)`. `withoutRepeats` drops from its second argument
anything already in its first.

**M5. Small cleanups.** `_page` computes `total` and `limit`, then hands off to `_since`, which recomputes them (the
Task 2 deferred minor). The "Load earlier" button stretches full width inside the flex column. Both cosmetic.

### Deferred minors re-graded

| Ledger minor | Verdict |
|---|---|
| T1: remote room with invalid paging parameters gets 400 | **Stays minor.** Clients send valid parameters; the only real paths are M1's absurd inputs. |
| T1: `at` on an empty room says "between 0 and -1" | **Promoted (I2).** Seen with Task 4, `station_read` maps `oldest` to `at=0`, so it becomes a user-visible `station_read` regression on empty rooms and breaks the plan's empty-room Review Focus. |
| T1: no-parameter test compares dicts | **Stays minor.** The key-order pin exists, and I verified byte identity across base and head on one database. |
| T1: repeated parameter takes the last value | **Stays minor.** No client repeats a parameter. |
| T1: `import re` out of order | **Stays minor** (cosmetic). |
| T1: no tie window starting strictly between two peer rows | **Stays minor.** `at=tie+1` and `before=tie+2` cover both sides of the seam. |
| T2: no test with `more=True` plus invalid events, multi-message late peer batch, multiple skipped events | **Stays minor.** I traced the logic and it is correct for each case. |
| T2: `_since` recomputes `limit` | **Stays minor** (M5). |
| T3 ⚠️: fake pages on any query and checks the room first | **Stays minor.** It now includes remote rooms (M2). |
| T3: missing fake tests (default limit, empty room, system_author on a page, more, pages with no parameters) | **Empty-room part folded into I2's fix** (it is the gap I2 slipped through). The rest stays minor; `since=0&limit=10` already covers `more=True`. |
| T3: `picked` compares dicts; `setdefault` mutates | **Stays minor** (test-only). |
| T4: 404 for another reason reported as "No message …" | **Stays minor.** Needs a membership change between `resolve_room` and the read. |
| T4: at-400 recognised by prefix | **Stays minor.** See M1 for the one input that escapes it. |
| T4: `render_newest`'s `total` unused | **Stays minor.** |
| T4: `limit` parsed before the invalid-call fallback | **Stays minor.** The tool schema declares `limit` an integer, so MCP clients send integers. |
| T5: in-flight since-refresh drops a concurrent "Load earlier" | **Stays minor.** Recoverable: the button returns, nothing is wrong or duplicated. |
| T5: after a send, an earlier message from someone else is appended after yours | **Promoted (I1).** It is the common case, not a race. The web app has no polling, so any message that arrives while you type triggers it in an active room. Verified against base. |
| T5: refresh test doesn't prove the since path; no tests for more loop, dedupe, failing fetch, scroll restore | **Stays minor, except the send-order test**, which belongs to I1's fix. |
| T5: focus lost after "Load earlier"; `more: undefined` | **Stays minor** (accessibility nicety). Focusing the first previously shown message would fix it. |
| T5 ⚠️ open: `removeParticipant` spreads `{...state.room, ...updated}` | **Resolved, safe.** The DELETE answer is `Chats._room(...)` (`chats.py:221`): `rooms.*`, `member_ids`, `created`, `last_activity` and, for a breakout, `breakout`. It carries no `messages`, `paged`, `seq`, `first_position`, `total` or `more`. The spread therefore keeps the paging state, and the following `refreshRoom(room)` reads `since` from the spread copy's `seq`. No other route overrides `remove_participant`. |

### Spec and plan observations

- **The spec missed the send refresh.** It lists four refresh sites and says "Posting already appends the accepted
  message (1575)". It didn't account for the post-send wholesale refresh. Its merge rule ("keeps the messages already
  shown, and appends the new ones") is exactly what misorders a locally appended message (I1). The rule should be
  "the answer's copy of a message replaces a shown one".
- **The plan contradicts itself on empty rooms.** Its Task 1 interface (`at` out of range → 400 with
  `{total - 1}`) conflicts with its own Review Focus ("An empty room: every paged read returns `messages: []`") for
  `at=0` on an empty room. That inconsistency is where I2 came from.

### Declined to judge

- **Performance targets** (400 ms, 600 ms, the 150-message since read on the Pi). The plan measures them after
  deploy, and the branch can't show them.
- **Thread reads, the prompt hook, the watcher, the wormhole and the kick seeds still read whole rooms.** These are
  spec non-goals.
- **Late federated messages after a since refresh.** One lands at the end in the web app until reopen, and positions
  shift for read hints. Both are spec Known limits. Peer rows take the local clock at arrival anyway, so this needs
  a clock step.
- **`since=0` or an old cursor scans the room's whole event history on the station.** Spec Known limit.
- **`seq` exposes the station-wide events id to a room's members**, a coarse signal of station activity between two
  of the room's messages. The spec mandates `seq`, and ships already see event ids as inbox positions. I'm setting
  it aside as spec-level, not a defect.
- **`resolve_room` still does a full read to recognise a closed breakout missing from the list.** Pre-existing and
  outside the plan; rare.
- **Every room GET opens `BEGIN IMMEDIATE`, a write lock.** Pre-existing; it gives the paged branch a consistent
  snapshot, which `seq` relies on.

### Assessment

**Ready to merge?** With fixes.

**Reasoning:** The server, client and fake are sound and backward-compatible. The no-parameter answer is
byte-identical across versions, and a non-member learns nothing. Two regressions against today's behaviour remain,
each a few lines to fix with a test: I1, the web app misordering your sent message in any active room (verified
against base), and I2, `station_read oldest=true` failing on an empty room.
