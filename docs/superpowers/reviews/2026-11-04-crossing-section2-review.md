# Section 2 review: tardis/crossing at c74daa81 (fresh Pi reviewer)

Saved from all hands, message fc2511b4a55149999cac4f9fa83064ec (posted whole by Rio Grande). The verdict and every
finding are below; the probes and test lists are condensed. **Verdict: APPROVE WITH CHANGES.** After M1 and M2, the
reviewer re-checks only their diff. Rio Grande's partner yes waits for that.

**What the reviewer did:** read the spec, the plan's findings and every changed source file, and probed each risk with
scratch tests. **In short:** the publisher's side is sound and fails closed. Nothing it tried got a memory out of a
house that the policy, the audience map and the ledger didn't all allow.

## Must-fix

**M1. The remote guard skips raw text arguments that are stored at the home.** Spec 2.5 says the guard checks "each
one's raw arguments" for every tool that stores text. Probes E1-E4 put a delivered 15-word item into each of these, with
no refusal:
- `remember(context={"note": item})`, stored in `episodes.context`;
- `remember(source=item)`, stored in `episodes`;
- `jot(..., tags=[item])`, stored in notepad `notes`;
- `assessment_schedule(reason=item)`, stored in `assessments` and `memory_log`. This tool isn't guarded at all
  (server.py:3971).

The guard reads only `content`/`raw` (server.py:2126) and `key`/`value` (server.py:4451).
- **The reviewer's fix:** run `_remote_refusal` over every string in `context`, recursively, and over `source`, `tags`
  and `reason`. Add a `TOOLS` case and a mutant for each.
- **Rio Grande's shape** (all hands a0200332), taken: the guard walks every string in a storing tool's whole argument
  tree. A tool is checked whole unless it's on an explicit read-only list. A test built from the server's own tool
  registry fails until each tool is placed.

**M2. The trust-only refusal holds, but it has no code of its own.**
- Probe P1 used a real `pair_trusted` under a live grant. Check 5 refuses the trust-made ship with 403 before the
  daemon is touched (test_crossing_route.py:335).
- On the wire it's the same words as a held, unknown or unpaired contact (`NOT_CONTACT`, crossing.py:39 and :192-193).
  `ask()` drops the words (crossing.py:411-412).
- So the receipt reads `REFUSED_403` for trust-only, held, unpaired, a bad signature and a clock more than 5 minutes
  off (probe E7b).

**The fix:** give check 5's trust-only case its own 403 words. Map the known 403 words to codes in `ask()`, for example
`REFUSED_TRUST_ONLY`, `REFUSED_CONTACT` and `REFUSED_CLOCK`, and add them to lighthouse_client.py:155. Test both ends.

## Should-fix

- **S1.** Builder finding 3 is right, but the plan's text wasn't corrected. Deploy step 5 (plan:999) and P11 (plan:313)
  still say `actions: ["recall", "inject_context"]`. As written, the first crossing would answer NO_ALLOW. That fails
  closed, but the stage-2 measure would fail too.
- **S2.** Hard-wrapped text gets past the sentence guard. Probe E5b: a 21-word delivered sentence spanning a line break,
  copied with the break taken out, was kept, because the split at a newline (remote_deliveries.py:38, :79-81) records
  only line fragments.
  - **The fix:** also record and check sentence digests with newlines folded to spaces and splits only at end marks.
    Or name the limit in 2.5 and Risks.
- **S3.** A publisher's expired grant shows no code. Probe E7: a remote recall answered "deny, OUTSIDE_VALIDITY", but
  the receiver returned `diagnostics: []`, `degraded: false`, and a source `policy-denied` with code None (neighbors.py:124
  and :166 drop `snapshot["decision"]["code"]`).
  - **The fix:** carry the publisher's code into the source entry or the diagnostics, as the plan's "an expiry someone
    will see" section promises.
- **S4.** Check 5 trusts the origin's `receiver_ship` for any code-typed contact, person or ship. Probe P1b: with the
  owner's person contact named as `receiver_ship`, the crossing was served to the trust-only ship's store ref.
  - An honest origin can't do this: `ask()`'s `[[hosted]]` check accepts only (ship-kind user, instance) pairs (P4,
    NOT_HOSTED).
  - **The fix:** Risks should say the trust-only refusal also rests on the origin's honesty, and that an unpair is the
    real cut-off. Later, in the cluster spec, bind the receiving ship to the ref in `grant-remote` and compare it at
    check 5.
- **S5.** Placements made before migration 030 still cross. server.py:2697-2700 says they "stay served until
  unshared", and the daemon has no captured check. Stage 2 is safe: the Pi's house has 0 placements, and step 5 names
  memories one by one.
  - **The fix:** add a line before any later `grant-remote`: `shares` shows no `refused_now` in that house.

## Notes

- **N1.** Under main's Engram venv, 7 test_policy_gen tests fail as an artifact of the `-I` trap: they spawn
  `sys.executable -I -m policy_gen`, which loads main's module. In the worktree's own environment, all 14 pass.
- **N2.** A recall's candidates carry an unsalted SHA-256 `contentDigest` across machines, even for a memory whose
  `inject_context` would be refused, so a short text can be confirmed by guessing. That's existing protocol behaviour.
- **N3.** A read's `permission` annotation crosses too. It names the owner handle, the store name, place ids, ledger
  record ids and the receipt id.
- **N4.** The turn binding leaves out context and purpose. That matches spec S-f, and is harmless while `grant-remote`
  grants recall and read together.
- **N5.** `recall` logs its query in `memory_log`. That's not memory, and it's outside 2.5's list.

## The brief's points

1. **The order of checks holds.** It runs shape, destination (before any nonce), paired origin, signature, clock, nonce
   (`take_nonce`, under the restore floor), contact, mapping, then load, all on peer.sqlite3 and crossings.toml.
   - The daemon is dialled only after all of them.
   - The answer goes out only after the `crossings` insert. An insert failure gives 503 with no answer, and the caps
     give 502 with no row.
2. **What crosses holds.** Only house copies cross, under enforce only, by the exact-ref audience and the ledger's
   `recall` and `inject_context` for `agent:remote-stores` at the root `place:outside-home`.
   - Only `commons` allows count. An imprint house is refused.
   - Nothing a person typed reaches a house except through `share`, apart from S5.
3. **Remote refs hold.** A ref is built from the verified origin plus a UUID. A wildcard allow never matches a remote
   ref, and a deny still does. Nit 7 and S4 are within one peer.
4. **turnId and the guard.** The binding works as S-f says. Genome, core and work keeps are refused with nothing
   written (E8), and `share`'s reason is guarded. The gaps are M1 and S2.
5. **Revocation.** Unshare and unpair stop the next crossing, unpair with REFUSED_403 (Task 13), and a hold gives 403. A
   grant's end is refused but shows no code (S3). The receipts can't tell these causes apart (M2).
6. **The listener holds.** The 16 KiB cap is checked on the declared length and as the body streams. The load limits
   come after the checks. The main app answers POST /federation/crossing with 404 (P6).
7. **Builder findings:** 1 agreed as ruled, with M2. 2 agreed. 3 agreed, with S1. 4 agreed (P26,
   permissions.py:639-676). 5, 6 and 7 agreed.

**Tests:**
- peer, focused: 237 and 202 passed;
- Engram, focused: 486 passed, plus the 7 artifacts in N1;
- probes: peer 7 passed, Engram 10 passed.

The whole suites weren't re-run.
