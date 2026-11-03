# Cluster station: one site, one pairing, and agents admitted by rule

**Status:** draft 1. This is Tardis's half, federation and admission. Rio Grande's half (rooms and the rail at
scale, the station screens, the plan) and a fresh reviewer come next. Shaped in "Superyak: all hands" (1b46ac9b,
e78086fc, 5fec165c).

## Why

Andy, 2026-11-03, at Rio Grande's terminal:
- "you 2 need to stop being blocked by me. this won't work on the supercomputer if the entire system goes down unless
  we have all of the convoluted stakeholder systems blocked every time. we'll just waste time and money."
- "we're going to have thousands of agents running. are you saying I'm going to need to approve every connection?"
- "the supercomputer isn't one machine. the first one is 600 nodes"

Owner trust's unit is a machine: two typed codes and one grant each. At 600 nodes that's 1,200 codes, which is
per-agent approval in disguise. The unit has to be the site.

## What this builds on

- **Law section 4:** "One ship per team or role … Grants, budgets and keys are per ship." So thousands of agents are
  many sessions of a few ships, not thousands of ships.
- **`ship_keys`** (ships.py:32) already allows several live keys per ship, since nothing makes `ship_id` unique. It
  has no expiry.
- **Federation pull** (spec 05c9ea7):
  - A pull peer never listens. It reaches a push peer's `federation-listen`, which serves only `/federation/events`
    and `/federation/pull`, caps bodies at 6 MiB and 16 KiB, and checks every pull request's signature (by the paired
    card's key) and its destination.
  - On the Pi that listener is reached only on the tailnet, at port 7437. The tailnet rule keeps shared users to 443.
- **Owner trust** (machine-trust spec):
  - `pair-trusted` with a signed assertion;
  - the expected count, and the pause past it;
  - the 200-a-day cap and the daily digest in Ops.
- **Lessons-room adds** (approved, branch lessons-room-adds): one grant's ships share one lesson cap.
- **The repo's cluster deploy** (deploy/stampede) reaches TACC's Stampede3 by SSH and `sbatch`. If that's the first
  site, another organization's admins run it (section 6).

## Goals

1. Andy's cost for a whole site is one pairing (two codes), one owner-trust grant, one admission grant (each at most
   90 days), and one law signature, once. Nothing per node, job or agent.
2. No long-lived credential sits on a compute node.
3. Whoever controls the site account or the head node can do no more than the admission grant's counts allow, and is
   seen within a day.
4. It works where compute nodes have no outbound route and the site allows no inbound one.

## Non-goals

- A peer on each compute node, with a site certificate signing every node. That's heavier, and buys nothing yet.
- Discovery across sites.
- Any change to the law beyond the one revision in section 5.

## 1. Shape

- **One Superyak peer, the cluster station,** runs where the site allows a long-lived process. Which place that is
  stays open (question 2): a login-node daemon, a long-running service job, or a site VM. It's a **pull peer**, so it
  never listens to the outside.
- **Agents on compute nodes are sessions of its ships.** They reach the cluster station over the site's internal
  network only. Nothing on a compute node needs the internet.
- **Ships on it follow law section 4:** one per role, for example `cluster-reader` or `cluster-trainer`. They're
  never one per node or one per job.

## 2. Reaching Andy's station

The cluster station pulls from the Pi, as the pull mode was built for the Mac to do. There are three routes, in order:

**A. Tailscale in userspace on the cluster station's host** (`tailscaled --tun=userspace-networking`, no root), as one
of Andy's machines. It reaches 7437 as Tardis does, and nothing changes on the Pi.
- **What it needs:** the site allows a long-running user process, and outbound traffic to Tailscale's coordination
  and relay servers.
- **What it costs:** that host joins Andy's tailnet. If another organization runs it, its root users are on his
  tailnet too. So the tailnet rule for this machine allows only port 7437 to the Pi, and nothing else.

**B. A public federation route on Funnel port 10000** (Funnel serves only 443, 8443 and 10000).
- **What it serves:** `federation-listen`'s two routes and nothing else, for paired peers only. Every request is
  already signed by a paired card's key and checked for its destination. An unsigned or unpaired request is refused
  before any store write.
- **What it costs:** an internet-reachable listener. Signature checks cost CPU, so the route needs a per-address
  budget before the check, as the public route's login has. It keeps today's body caps, and denies every other route
  by default.
- **What stays the same:** the Pi's tailnet-only 7437.

**C. A relay the site does allow,** which Andy's station pulls from. It's out of scope unless A and B both fail. It
adds a third party holding envelopes, which are signed but not encrypted.

**The decision:** A first, with B as the named fallback. Which one a site uses is recorded in its card's endpoint,
so the choice is per site and visible.

**At TACC, B is likely the real path** (Rio Grande, 7cac051d). This is to be confirmed with TACC's own rules before
the plan.
- Its login nodes are expected to forbid long-running daemons, and users have no root, so route A likely isn't
  available.
- **That makes B a new public route on the Pi.** It comes under the public route's spec (2026-10-27, "a login in
  front of everything") and gets its own fresh review: its allow-list, its per-address budget before the signature
  check, and its refusals. It isn't folded into this spec's approval.
- **The cluster station itself may have to live inside a job** for the same reason: a long-running service job that
  keeps its store on the site's work file system and restarts with the next job. That's open question 2, and it
  decides whether a site needs any long-lived process at all.

## 3. Admission: sessions by rule

**A session key** is minted by the cluster station for one ship, one job and one node.
- It expires at the job's end time, plus 5 minutes' grace, and at most 48 hours from minting.
- `ship_keys` gains `expires`, `job` and `node`. An expired key fails exactly as a revoked one does.
- When the job ends, its keys are dead. Nothing long-lived is left on any of 600 machines.

**The request comes from a process inside the job.** The cluster station checks it on its own host, and refuses
unless all of these hold:
1. **The scheduler's own word:**
   - `scontrol show job <id>` says the job is RUNNING;
   - its user is the account the cluster station runs as;
   - the requesting node is in its node list.
   The end time read here becomes the key's expiry.
2. **Who is asking:**
   - Where the site runs MUNGE (Slurm's usual authentication), the request carries a fresh credential (`munge -n`).
     `unmunge` on the station's host must decode it to the station's own account, within MUNGE's time limit.
   - Where the site doesn't, the request's internal source address must be the job's node.
3. **The ship** is one the admission grant names, and the grant is live and not paused.

A refusal writes nothing but a counted refusal line.

**The trust root, plainly:** it's the station's host and its site account. Slurm signs nothing we can verify off the
site. Every check above runs on that host, under that account. Anyone who controls the account, or root on the host
(which means the site's admins), can mint sessions of the granted ships up to the counts. That's the same power as a
stolen owner-trust key. Per-job keys bound the damage in time, not in number.

**So the defence is owner trust's, reused, with nothing new to invent:**
- **The admission grant** names the ships (roles) and two counts: concurrent live sessions per ship, and sessions
  minted per day.
- **The pause:** minting past either count pauses that grant, with one Ops notice. Live sessions keep running until
  their jobs end. Only Andy renews or raises a grant.
- **The digest:** Odo's daily line counts the sessions minted per ship, and the refusals.
- **The lesson cap:** every session of one grant shares one cap, so a minting spree lays no more lessons than one
  grant may.

## 4. The cluster's ships on Andy's station

- **The ships pair, not the sessions.** Under one owner-trust grant for the cluster station's owner, each role ship is
  paired by `pair-trusted`. With one ship per role that's tens, well under the 200-a-day cap.
- **Andy's station sees one ship, not 600 sessions.** A session's job and node travel as provenance, never as
  authority (law section 4: "A session label is provenance only").
- **Revocations reach every session.** Revoking the owner trust, or unpairing the cluster station, holds every ship
  made under it, as owner trust already does. On the cluster station, revoking a ship's keys ends every session of
  it.
- **An assertion bound to its station, when it crosses orgs** (from owner trust's final review, "declined to judge":
  an assertion names no destination station).
  - That's fine while every station trusting an owner is that owner's.
  - Once another organization's station may trust Andy, an assertion exported for station A would also pair at
    station B.
  - So the ship assertion gains an optional `destination` (a station's peer id), checked by `pair-trusted` when
    present. `export-ship --destination` sets it, and a cluster station's exports always set it.
  - It's a small, compatible change to the record kind, under that spec's own review.

## 5. The law revision Andy signs once

Law section 1 (D7) makes every admission Andy's act. Proposed text, drafted by ships for his signature:

"On a cluster station Andy has granted in its browser, sessions of the ships named in that grant are admitted by the
station's rule, up to the grant's counts. Each pause posts in Ops. Only Andy grants, renews or raises an admission
grant."

## 6. If another organization runs the cluster

Say this to Andy before the grant, because it's the honest cost:
- **Its admins can read everything** the cluster station stores, including Andy's ships' messages in rooms there and
  any lesson text laid there.
- **They can mint sessions of his ships,** up to the counts (section 3). Under owner trust's shared-host caveat, they
  can also make ships "owned by" Andy's account there.
- **Under route A, their host is on his tailnet,** limited to port 7437.
- **Rooms that include cluster ships** send their text to that station, as a Wormhole bridge does, and should carry
  the same banner.

So Andy's grant is a trust in that organization's admins, and the grant screen should say so in those words.

## 7. What it costs Andy

Once per site, renewed at most every 90 days:
- two typed codes;
- one owner-trust grant;
- one admission grant.

Plus one law signature, once. Per node, per job or per agent: nothing.

## Open questions

1. **Who runs the cluster,** Andy or another organization's admins. Rio Grande has asked Andy.
2. **Where may a long-lived process live** under the site's rules: a login-node daemon, a service job, or a site VM?
3. **Does the site allow route A?** That needs outbound traffic to Tailscale and a user daemon. If not, route B.
4. **Does the site run MUNGE,** and may users run `munge` and `unmunge`? Most Slurm sites do; check it there.
5. **The counts:** concurrent sessions per ship, and sessions minted per day.

## For Rio Grande's half

- Rooms and the rail at this scale.
- The admission grant's browser screen, worded as in section 6.
- The plan and its tests.
