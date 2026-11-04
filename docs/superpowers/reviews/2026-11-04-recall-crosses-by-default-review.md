# Review: a recall crosses wherever a receiver is enabled

A fresh reviewer, 2026-11-04, on Serenity's spec (law section 3). Saved whole. Verdict on revision 1: APPROVE WITH
CHANGES. Verdict on revision 2: APPROVE.

## Revision 1 (5fc414fb): APPROVE WITH CHANGES

**What I ran, with results.** I read the spec, the current `engram/` code it describes (`server.py`'s `recall`,
`neighbors.py`, `lighthouse_receiver_config.py`, `lighthouse_client.py`, `hooks/wake.py`, `hooks/nudge.py`,
`hooks/sleep.py`, `scripts/runtime.py`, `docs/lighthouse-receiver.md`, `engram/CLAUDE.md`), and the unmerged
`origin/tardis/crossing` versions of `neighbors.py` and `lighthouse_receiver_config.py` plus `scripts/rail_e1_prime.py`
from `origin/rail-mathematics`.

I then ran a scratch probe that: (a) fed `default_context = "memory/technical"` into today's `load_settings`, which
raises `ValueError("INVALID_CONFIG")`, confirming the key doesn't exist yet; (b) started a Unix-socket "publisher" that
accepts and never replies, then called `neighbor_arm` directly with `timeout_s=5.0` and `timeout_s=1.0`. Results: 5.008 s
and 1.006 s, both returning `degraded=True`, `diagnostics=[{"code": "TIMEOUT"}]`. This confirms the `min(timeout_s, 1.0)`
deadline mechanism will work mechanically once wired in.

**Findings.**

1. Must-fix. `scripts/runtime.py:308-318` duplicates the receiver-settings key allow-list independently of
   `engram/lighthouse_receiver_config.py:40`. The moment the Mac's rollout step sets `default_context` in the toml,
   `runtime.py`'s own validation will reject the unknown key and report `"state": "invalid", "error": "invalid receiver
   configuration"`, even though `server.py`'s recall path works correctly. Fix: add it to `runtime.py`'s allow-list in
   the same change, and ideally stop the two drifting.
2. Must-fix. The rollout's stop rule cannot be populated the way the dominant "used" mechanism works.
   `hooks/sleep.py:86-139` (`auto_capture_outcomes`) updates `memory_log` by the recall event's own row id and only checks
   whether the recall's own local `target_ids` later appear in episode content or context, or in `CITING_OPERATIONS`.
   Neighbor-delivered content is never persisted as a local episode and never becomes a `target_id`, so this path
   structurally cannot mark a crossing as used. The only other path, explicit `log_outcome`, is the kind of deliberate
   step the spec's own "Why" says sessions don't reliably take. So the rollback trigger can't distinguish a useful default
   crossing from an ignored one. Fix: extend the citation check, or rewrite the measure to name a mechanism that can
   produce signal.
3. Should-fix. Volume: moving from 9 crossings in two months to effectively every recall multiplies `lighthouse_receipt`
   rows, each carrying a full receipt. The spec names no retention plan, nor its effect on the Lighthouse export.
4. Should-fix. The test list covers remote publishers generically, but the risky case is narrower: a default crossing
   where `default_context` equals the `context` of a configured `[[remote_publishers]]` entry. Name that overlap.
5. Nit. `neighbors.py:202-205`'s docstring ("A recall that names no context is inert") becomes false; update it.

**Checked and found sound.** No query leaves the machine by default, today or under the stated design: local publishers go
over a Unix socket, and on `tardis/crossing` a remote publisher is reached only through `ask`, so suppressing `ask` and
`remote_publishers` for a default crossing is a sufficient control, contingent on being implemented as promised.
Instinct-only recall cannot cross. Hooks don't call the `recall` tool. The deadline mechanism works as described. E1-prime
filters `event_type = 'recall'`, so receipts don't pollute that measure. The publisher never learns whether a query was a
default or explicit crossing. The permissions gate and a busy or unreadable ledger are handled identically for both.

**What I didn't check.** The "9 crossings" baseline or the Mac timing table, which need the real store. The full test
suite. Every skill or MCP server for an undiscovered internal caller of `recall()` beyond those I found
(`context_cli.py`, `context_lighthouse.py`, `lighthouse_pilot.py`, all explicit-context-only). `lighthouse_daemon.py`
beyond the error codes.

## Revision 2: APPROVE

1. Addressed. `scripts/runtime.py`'s imports are all standard library, confirmed via `sys.stdlib_module_names`, and
   `lighthouse_receiver_config.py` imports Engram-internal modules, so the stated reason for not sharing an import is
   true and an equality test is the right substitute.
2. Addressed. "The check" replaces the broken trigger: a report at 50 logged outcomes or 2026-12-04, and below 50 it says
   use is unknown. Every quantity named is readable from `memory_log`. On not building an automatic mark: not wrong. A
   text-match detector would conflate echoing with use in both directions, and learning whether the plain count moves is
   a reasonable first question.
3. Addressed, with an explicit non-rollout condition for a cluster ship. I can't verify the byte figures, but
   `log_retention_days` is defined in `engram/config.py` and referenced only in a test and an example toml: "read
   nowhere" is accurate.
4. Addressed. The exact overlap case is named.
5. Addressed.

Nothing new is blocking. The likely practical outcome of "The check" is that it lands on the date and reports "unknown"
rather than reaching 50 logged outcomes, at the current hand-logging rate. The spec anticipates that honestly, so it's an
observation, not a defect.
