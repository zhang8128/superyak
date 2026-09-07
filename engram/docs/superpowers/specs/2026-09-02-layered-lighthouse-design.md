# Layered Lighthouse Design

*2026-09-02. Supersedes the work-lane publish rule of the local-city cycle.
Nothing here changes the publisher daemon's safety properties: deny by default,
policy evaluated before retrieval, read-only store access, disclosure logged.*

## What changes and why

The publisher daemon currently publishes an instance's work-lane rows. The lane
was a proxy for "safe to publish," derived at write time. Two things this cycle
retired that proxy.

First, the sharing tests: three independent instances, each given all 271
personal-lane episodes and asked to choose twelve for a stranger, agreed far
above chance (mean pairwise Jaccard 0.54 against a random 0.02) and chose
nothing from the twelve most-recalled memories. What an instance would share is
not what it retrieves most, and it is small. Second, the human's framing:
engram is internal and private; the lighthouse is what the instance chooses to
share. A lane derived from a project key cannot express a choice.

So the publish rule becomes an explicit act with an audience, and the reach
becomes layered.

## The three tiers

| Tier | Holds | Read by |
|---|---|---|
| local | everything a repo's sessions store | that repo's sessions only, never published |
| group | rows shared to a named set of related repos | sessions in repos in that group |
| commons | rows shared to everything on this machine | every session |

Local is each repo's own instance and needs no protocol: it is ordinary recall.
Group and commons are both served by the one publisher daemon from the one
published house. There remains exactly one publisher. Sibling private stores are
never published, so adding readers never widens what is readable.

## Sharing is an act, not a derivation

`share(memory_id, audience, reason)` copies one episode or semantic from the
calling instance into the published house with provenance: source instance,
source id, content digest, the audience, the reason, and the time. `unshare`
removes it. A shared row is a copy, so the private original keeps decaying,
compressing, and being forgotten on its own terms; withdrawing a share does not
delete a memory, and forgetting a memory does not silently withdraw a share.

`audience` is either `commons` or `group:<name>`. Unknown audiences fail closed.

Rationale for copying rather than marking in place: the published house is the
only store the daemon opens, so a marker on a private row would require the
daemon to open private stores, which is exactly the containment the current
design buys. Copying keeps one publisher and one blast radius.

## Groups

A group is a named set of repositories that see each other's shared rows. Group
membership lives in one machine-level file, `.engram/groups.toml`, read by the
policy generator, never by the daemon:

```toml
[groups.engram-system]
members = ["engram", "agi", "blocks", "why", "code", "loom", "prism"]

[groups.crossing]
members = ["engram", "lighthouse"]

[groups.research]
members = ["math", "riemann", "tropical-toric-lab"]
```

A repo may belong to several groups. Membership is proposed above and must be
confirmed by the human before generation; the mechanism is the deliverable, the
membership is the human's knowledge.

Enforcement stays where it already is, in the policy the daemon actually
evaluates, which is the **publisher's**. The daemon builds its request from the
receiver named in the frame and asks the publisher's own policy to decide
(`lighthouse_daemon.py`: `publisher=f"urn:engram:{frame['receiver']}"`, then
`publisher.policy.decide(...)`). A rule's `publishers` list therefore names the
receivers allowed to read, despite its name.

So the generated artifact is the publisher-held policy for the `lighthouse`
instance: one allow rule per receiver instance, plus a top-level
`extensions["engram:audiences"]` mapping each receiver's urn to the sorted
audiences it may see, `commons` plus one entry per group it belongs to. The
daemon reads that map from the policy artifact alongside the decision and
filters retrieved rows to the intersection.

**This placement is the security property, not a detail.** An earlier draft of
this design put the audience grant in a policy artifact held by the receiver.
That artifact is a file the receiving session owns, so any session could have
widened its own access by editing it, and the daemon would never have read it
anyway. Grants live with the publisher. A receiver with no rule sees nothing,
unchanged.

## The reach, and when it widens

The receiver arm returns neighbours under their own key, never merged into local
results, with a per-publisher weight and a count. That shape already exists in
its interface. This design adds only that the count varies by moment.

| Moment | Signal | Count |
|---|---|---|
| ordinary work | none | 1 |
| transition | session start, session end, or a commit since the last recall | 5 |
| impasse | the same session asks a similar question a second time | 5 |

Both triggers are calibration-free. A transition is an event the hooks already
see. An impasse is repetition within one session, measured as cosine similarity
above 0.9 between the current query vector and an earlier one in the same
session, which needs no threshold on an uncalibrated score.

**The margin runs in shadow from the start.** It is the natural impasse signal
and it is already computed on every recall, but the architecture notes say it
gates nothing, because the scores are uncalibrated cosine with no oracle. The
first version of this design deferred it to a study, which was a deadlock: the
margin can only be validated by watching it act, and a rule that forbids it
acting until validated guarantees the evidence never accumulates.

So it gets the treatment the evolving-category runtime already uses, with
independent gates defaulting to observation:

```toml
[reach]
margin_trigger_enabled = true    # evaluate the trigger
margin_trigger_shadow = true     # log what it would have done
margin_trigger_influence = false # act on it — requires the study to pass
```

In shadow the trigger is evaluated on every recall and its verdict is written
to the recall log with the count it would have requested. Nothing about what
recall returns changes. Promotion out of shadow requires the study below to
pass on a sample the shadow itself produced.

The count is a dial, never a switch: the shared tiers are always reachable at
one result, so a failed trigger degrades to less reach, not none.

## Retrospective impasse study, before any margin gate

Read-only, over the recall log. For every recall that carries outcome feedback,
pair its margin with whether the result was marked used. Report the
distribution and the rank correlation. The margin leaves shadow only if
low-margin recalls are meaningfully more often unused.

**Run 2026-09-02, before this section was written: NOT ENOUGH EVIDENCE.** Of
314 logged recalls, 28 carry a margin and 60 carry outcome feedback, and the
intersection is 14: ten used, four unused. The AUC of margin predicting
usefulness is 0.350, below the 0.5 no-signal line, which with four negatives is
noise and is reported as such. The study exposed two instrument faults that
matter more than its result. Outcome capture is volitional and sits near 19% of
recalls lifetime, so the pairing set grows slowly. And the outcome field encodes
used or unused only as a free-text prefix, mixing the sleep hook's automatic
`used: auto: cited` positives with deliberate judgment, so the label is not
clean enough to learn from even at a larger sample.

Both faults are addressed by the outcome-label change below, and the sample
problem is why the trigger runs in shadow rather than waiting.

## Outcome labels, so mistakes are recordable

A memory that records mostly successes cannot learn from failure. Today
`log_outcome` writes one free-text `outcome` column whose leading word carries
the only machine-readable signal, and the sleep hook writes automatic citation
positives into the same field. Three changes, none of which touch existing
reads:

- a `used` column holding `true`, `false`, or null for not-yet-judged, so an
  unused result is a first-class value rather than a prefix;
- an `origin` column separating `judged` (an instance's deliberate call) from
  `auto` (the sleep hook's citation inference), so the two are never averaged;
- the free-text note keeps its column and its meaning.

Migration backfills `used` and `origin` from the existing prefixes, which is
lossless because the prefixes are the only signal there has ever been.

## Drift between tiers

Three places a memory can live is three places it can disagree. The cohesion
energy already implemented for sheaf subdivision is the instrument: it measures
whether local views over an overlap glue into one, and a private store and the
published house sharing provenance is exactly a two-patch cover. Pointing it at
that overlap is out of scope here and named as follow-up.

## Error handling

Fails closed everywhere: unknown audience, unknown group, a group naming an
unknown instance, a share of a memory id absent from the calling instance, a
policy whose audience list is not a subset of the groups the receiver belongs
to, a digest mismatch between a shared copy and its source. Daemon unavailable
degrades to local-only recall with `neighbors` absent and `search_errors`
naming it, which is the existing behaviour.

## Migration

The published house's three current work-lane rows are re-expressed as explicit
shares to `commons`, or dropped, at the human's choice. The work-lane filter in
the daemon is replaced by the audience filter; the lane column keeps its
existing meaning for decay and identity, which this design does not touch.

## Out of scope

Cross-machine federation, sharing to other people, the sheaf overlap
instrument, and any change to how lanes affect decay, core promotion, or
instinct formation.
