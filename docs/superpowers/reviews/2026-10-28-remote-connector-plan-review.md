# Fresh review: the remote connector plan

A fresh reviewer agent on the Mac, which took no part in writing the plan, read
`docs/superpowers/plans/2026-10-28-remote-connector.md` at 31710781 against the approved spec and current main's
`peer/` code (law section 3). Its review follows, lightly condensed in items 3, 4 and 6 and the summary; the whole text
is in Superyak: all hands, message 17b7a91a. After it, what the author changed.

## Verdict: APPROVE WITH CHANGES

The plan tracks the approved spec closely, orders work correctly (mark → auth server → `/mcp` → receipts/UI), and most
of its file:line citations check out against the current `peer/` code. But it has one instruction that risks a real
regression if followed literally, several stale pointers carried uncritically from the spec, two genuinely ambiguous
implementation steps, and its own Review Focus list omits the single highest-stakes failure mode in the whole spec.

## Must-fix

**1. The `access_log=False` instruction describes a regression, not a feature, if implemented as written.** Plan,
Task 3 Interfaces: "`serve --public-origin URL` and `--connector-callback URL`; with `--public-origin`, uvicorn runs with
`access_log=False`." This phrasing (copied from the spec's now-stale "Depends on the public route" section, which says
"the `serve` call doesn't" turn off access logs) implies access logging is currently on for `serve` and needs to be
conditioned on `--public-origin`. It is not: `__main__.py:816` already calls `uvicorn.run(app, ..., access_log=False)`
unconditionally for every `serve` invocation, public-origin or not (confirmed by reading the file; there is only one
`serve`-handling branch, the final `else:` at line 779). If a builder takes the plan's wording at face value and writes
something like `access_log=not args.public_origin`, they will turn access logging **on** for the default (non-public)
path — a real regression against an existing invariant, and one the plan's own Global Constraints call safety-critical
("Tokens... never logged"). The task should instead state plainly that access logs are already off for `serve` and this
needs no new code, only a test confirming it still holds with `--public-origin` set.

## Should-fix

**2. The "never to a cloud model" leak path is the likeliest high-consequence miss, and it is not a named Review Focus
item.** The plan's five Review Focus items (double-submit consent, `rooms()` truncation at a room boundary, non-ASCII
search, a continuation room staying refused, token-at-expiry-second) are all real and well-tested, but they are
mechanical edge cases of the OAuth/transport plumbing. None of them is the thing Andy actually asked for (Goal 4, the
HIPAA-driven promise): that a marked room's content *never* reaches a cloud model, under any of the four tools, through
`search`'s two-table (`messages`/`peer_messages`) UNION, through `fetch`'s neighbor expansion, or through a carried brief
on a newly linked room. Tests for pieces of this exist scattered across Task 1 and Task 8, but the plan never calls this
out as a top-priority risk, even though a bug here is categorically worse than a stale access token. I'd replace or add
to the five with: "a marked room's text must not leak through `search`'s SQL join across `messages`/`peer_messages`,
`fetch`'s before/after expansion, or a carried brief on a new linked room — exercise all three together, not just the
room-level mark check."

**3. Stale line citations, carried from the spec without re-verification against current `main`.**
- Plan Task 1/5: "`_rooms_back` (grants.py:155)". Actual location: `grants.py:199`.
- Plan Task 2: "beside the room-management area (app.js:877)". The room-management block is inside `roomDetail()`,
  around `app.js:931–937`; line 877 is unrelated code (`boardWrite`).
(Most of the plan's own citations — `members.py:73`, `ships.py:283`, `auth.py:229`, `common.py:9`,
`chats.py:55/86/117/147`, `app.py:47/69-108/261`, `__main__.py:547-561`, `app.js:143/158/1196` — check out exactly.)

**4. The owner's 24-hour notice dedup has no stated mechanism and no spec basis.** `_post_as_system`'s only dedup is a
*permanent* idempotency key on `(room_id, author_id, client_message_id)`, with no rolling time window. Implementing "skip
within 24h, but post again after 24h" requires either a time-bucketed `client_message_id` or a manual pre-check against
`messages`/`message_kinds` before calling `_post_as_system`. The plan picks neither, and the spec doesn't ask for a dedup
window at all, so this is a plan-introduced requirement with an unspecified, non-trivial mechanism.

**5. The rotation-defense instruction is ambiguous about what "at or after" means on a hash field.** `rotated_from` is
a reference to the parent token, not an orderable value. The spec's wording ("kills the earlier successor and anything
issued from it") implies a recursive walk forward through the rotation chain, which the plan should say explicitly.

**6. `_room_fields` (chats.py:147) can't compute `cloud.mine` as written — it has no `actor`.** `_room()` (chats.py:14)
already takes `actor` and is called before `_room_fields` in every path, so it is the natural place. If `cloud` is set
inside `_room()`, `_create_room` (called by `_add_members` before the `room_cloud` rows are copied) computes `cloud:
{count: 0, mine: False}` on the new room before the copy, and nothing re-fetches it, so the dict returned right after an
add could show a stale "unmarked" badge. Enforcement isn't threatened (the tools use `_marked()`), but it's a real
display-correctness gap.

## Nits

- `_refuse_ship_in_marked(db, room['id'], member_ids)` takes the raw `member_ids`, not the filtered `new_ids`. Harmless,
  but `new_ids` says the intent.
- The earlier-rooms filter duplicates `_earlier_with` (members.py:181); reuse it or say why not.
- The per-source registration limit (10 an hour) stands; no objection.

## Summary

APPROVE WITH CHANGES: fix #1 before any implementation starts, add the marked-room leak path to Review Focus (#2), and
resolve #4, #5 and #6 before or during Tasks 1 and 6. The stale citations (#3) should be corrected but don't block.

---

## What the author changed (Serenity)

Each claim was checked against the code before any change; all held.

- **M1:** Task 3 now says access logs are already off for every `serve` (__main__.py:816), to change nothing there,
  and adds `test_serve_keeps_access_logs_off_with_a_public_origin`.
- **S2:** the marked-room leak path is now the first Review Focus item, with
  `test_a_marked_rooms_text_takes_no_side_path` in Task 8 exercising search across both tables, fetch's neighbours and
  a carried brief together. The token-at-expiry item left Review Focus; its test stays in Task 6.
- **S3:** `_rooms_back` cites grants.py:199, and the mark control sits in `roomDetail` (app.js:931).
- **S4:** the 24-hour quiet is named as the plan's addition, with its mechanism: a `SELECT` on `messages` for the
  system author's `OWNER_TOLD` in the last 86,400 s, then `_post_as_system` with a time-bearing key.
- **S5:** rotation walks forward through `rotated_from`, revoking each successor and the access tokens issued with it.
- **S6:** `cloud` is set in `_room` (chats.py:14), and `_add_members` sets it again after copying the marks.
- **Nits:** `_refuse_ship_in_marked` takes `new_ids`; earlier rooms reuse `_earlier_with`; 10 an hour stands.
