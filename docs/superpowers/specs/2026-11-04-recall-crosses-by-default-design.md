# A recall crosses wherever a receiver is enabled

Serenity, 2026-11-04, revision 1. Board `spec:recall-crosses-by-default`. Law section 3: a fresh reviewer approves; Andy
can veto.

## Why

Andy, 2026-11-04: "make sure the lighthouses are being tested and used."

A recall reaches a lighthouse only when its caller passes `lighthouse_context` (server.py, the `if lighthouse_context is
not None` block). Nothing passes it by default: no hook, no skill. So on the Mac, the one machine with a working
lighthouse, a recall crossed 9 times in the two months before 2026-11-04. That is why a receiver rule could lapse on
2026-10-15 and nobody saw it for 20 days: nothing was using it.

Use shouldn't depend on a session remembering a parameter. When an owner has enabled a receiver, an ordinary recall should
cross, and a problem should show up in the next answer.

## What it costs, measured

On a throwaway copy of the Mac's stores, with its own daemon, main 4be306de, the Mac's `limit = 1`; 10 fixed questions,
twice each. Mac only: the Pi is untested, and its embedder is slower and busier.

| Case | Recall p50 | Notes |
|---|---|---|
| No context | 49 ms | |
| Context, daemon up | 80 ms | p90 82, max 359. Delivered 20 of 20, 8 distinct over 10 questions |
| Context, daemon stopped | 51 ms | Local results kept, `degraded: ["neighbors"]`, `UNAVAILABLE` |
| Context, daemon hung | 5,081 ms | Local results kept, `TIMEOUT`. This is the Mac's `timeout_s = 5.0` |

Delivered text: p50 584 characters, p90 3,090. Four real questions on 2026-11-04 delivered 4 different memories: 2 useful,
1 a repeat of a local result, 1 noise.

## Decisions

1. **A new optional key, `default_context`, in `lighthouse-receiver.toml`.** When it is set and the receiver is enabled, a
   recall that names no context crosses with it. Absent means today's behaviour exactly, so nothing changes on a machine
   until its owner sets it. It is validated by `context_ref` when the settings load: a bad value is `INVALID_CONFIG`.
2. **A default crossing reaches local publishers only. A query never leaves the machine by default.** On
   `tardis/crossing`, a remote publisher is asked whenever a recall's context is its own (`neighbor_arm`,
   `remote_publishers`), and the query text goes with it. So a default crossing passes no remote publishers and no `ask`,
   whatever the settings hold. Reaching another machine stays an explicit `lighthouse_context` on that call. Whichever of
   this and the crossing merges second carries this rule and its test.
3. **An explicit `lighthouse_context` wins,** with today's behaviour, deadline and purpose. There is no per-call opt-out:
   the toml is the owner's switch.
4. **A default crossing has a tighter deadline:** `min(timeout_s, 1.0)` seconds. A hung daemon must not add 5 s to every
   recall. It is still named: `TIMEOUT` in `neighbors.diagnostics`, and `neighbors` in `degraded`. 1.0 is provisional and
   labelled so in the code; the Pi's number should set it, and the test takes it as a constant.
5. **Everything else stays as it is for an explicit crossing:** the same `session-recall` purpose, both policies decided
   each time (an expired or denied rule is named, since 1c03a00f), a receipt, a disclosure on the publisher's side, and
   instinct-only recall staying local. The publisher's rule is still the grant. This changes who asks, never what may be
   answered. Delivered text stays in `neighbors.delivered`, apart from local results, as today.
6. **Hooks don't cross.** `wake` and `nudge` keep to the local store: they run on every session and prompt, with a hard
   time budget. Only the `recall` tool gets the default.
7. **The answer says it was a default:** `neighbors.context` holds the context used, and `neighbors.by_default` is true,
   so a reader and a test can tell the two apart.
8. **`superyak-runtime status` reports `default_context`** beside the receiver's state. Its absence is not an error.

## Rollout, and how it can come off

- The Mac sets `default_context = "memory/technical"` once this merges and that machine's Engram sessions have restarted.
  The Pi and Tardis set it when each has a local publisher, which they don't yet.
- Rollback: delete the line. Nothing else depends on it.
- **Measure:** crossings per session and the share logged used, read from `memory_log`, against the baseline of 9 in two
  months. After 50 default crossings with an outcome logged, a used share under 1 in 5 takes the line back off the Mac and
  reopens the question. Both numbers are provisional. A crossing with no logged outcome tells us nothing, so the count is
  of logged ones.

## What it doesn't do

- It doesn't set up a lighthouse on the Pi or Tardis, which is separate work.
- It doesn't change `limit`, or cap delivered text. p90 of 3,090 characters is watched, not fixed here.
- It doesn't touch crossings between machines: `tardis/crossing` governs those.

## Tests

- No `default_context`: a recall with no context has no `neighbors` key and makes no call, as today.
- Set: a recall with no context crosses, `neighbors.by_default` is true, and a receipt is written.
- Explicit context with the default set: explicit wins, `by_default` is false, and the deadline is `timeout_s`.
- A bad value is `INVALID_CONFIG`, as every other bad key is; a recall then says so in `neighbors`, with local results kept.
- **A default crossing never asks a remote publisher:** with `remote_publishers` configured and a recording `ask`, the
  recording stays empty, while the same recall with an explicit context asks. It lands with whichever branch merges second.
- A hung publisher on a default crossing returns within the deadline plus a small margin, with local results kept and
  `TIMEOUT` named; an explicit crossing still waits `timeout_s`.
- A stopped daemon: local results kept, `UNAVAILABLE` named.
- Instinct-only recall doesn't cross.
- `wake` and `nudge` make no neighbor call with the default set.
- `superyak-runtime status` reports the key when set and raises no error when absent.
