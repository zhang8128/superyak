# Start a Stampede3 memory campaign

**Current model requirement:** [American models only](model-policy.md), with
Gemma 4 preferred. The launcher's original Qwen defaults are superseded and must
not be used for a new deployment. Eligible model/backend selection and validation
are required before running the launch commands below.

**Whole-cluster scope:** Kairos has confirmed access to the entire Stampede3
reservation. The [whole-cluster proposal](reports/2026-09-12-stampede3-whole-cluster-plan.md)
supersedes the four-node example as a capacity plan. This page describes the
existing bounded launcher; it has not yet been extended to execute that proposal.

**Current direction:** iterate on the real research architecture locally with
Atlas, while keeping Intel/Stampede3 bring-up separate until access arrives.
See [research rounds](stampede3-research-rounds.md). This page describes the
prepared synthetic test preset; the Atlas research workflow is not yet wired
into this launcher.

The launcher prepares and submits the Intel PVC campaign with one command. It
uses a bundled, explicitly fictional engineering evidence task. Patient or
participant details are not needed to start. The offline rehearsal uses real
Engram stores and checkpoints with scripted responses; Intel builds, host drivers,
and inference capacity remain unverified until the first compute allocation.

## Configure once, launch when access arrives

From this checkout, after the Python environment has been installed with
`make setup-engram`:

```sh
make stampede-plan
```

This creates `.engram/stampede/config.json` if absent and prints the planned
campaign without connecting. Edit its `login` and `account` fields when access
arrives. `login` can be an existing SSH config alias or `USER@HOST`; use the host
and allocation account supplied for your access. You can give `run_id` a name,
such as `first-pvc`. Otherwise it is derived from the configuration.

Start with either:

```sh
make stampede-deploy
```

or double-click [Start Stampede3.command](../scripts/Start%20Stampede3.command) on
macOS. SSH may present the site's normal authentication prompts in Terminal.
There is no separate submission step. The launcher resolves remote `$WORK`,
stages a source bundle, installs a run-local Python environment, and submits the
Slurm job. Queue waiting follows submission; model setup and GPU probes run on
allocated compute nodes.

The initial request is **four PVC nodes for up to twelve hours**. These are
editable limits in [config.example.json](../deploy/stampede/config.example.json);
this launcher accepts one to four nodes and at most twelve hours per job. Actual
availability and accounting depend on the allocation. The current operational
reference is the [TACC Stampede3 guide](https://docs.tacc.utexas.edu/hpc/stampede3/).

## What the first job does

1. Independently prepare/probe pinned vLLM XPU and llama.cpp SYCL profiles. A
   backend must complete a structured model response before being accepted.
   Source revisions, dependency locks, model revision/file hashes, and device
   probe logs are saved. The first accepted backend fixes the campaign's model,
   backend, and precision; incompatible nodes report failure without mixing
   configurations into the comparison.
2. Run 16 comparisons: individual memory off/on × shared memory off/on ×
   populations 32/128 × in-flight request caps 4/16. Add four one-member serial
   references, one for each memory condition. The serial agent receives both
   evidence cohorts; a one-member shared condition measures self-publication,
   not exchange between peers.
3. Reserve one node for a separate 64-member community. The other three nodes
   rotate comparison cells in a seeded order. With one node, bounded community
   epochs alternate with comparisons. Community identities and histories persist
   across epochs and allocation resumes.
4. Write audit records, per-cell results, and complete generations of SQLite
   snapshots under `$WORK/superyak/runs/RUN_ID`. Live databases remain in each
   compute node's `/tmp`; nodes do not open a shared live SQLite WAL.

Each comparison has a 90-minute cumulative limit, up to 12 turns per member and
2,048 reserved calls, with 512 output tokens and 32,000 prompt characters per
request. A bound or failure is recorded, not silently retried under a lower
concurrency. Missing token usage remains explicitly unknown. Those bounds do
**not** equalize consumed tokens or experience across populations; these first
results establish mechanisms and operating limits, not causal scientific claims.

The community has separate finite limits: 1,000 turns per member, one million
reserved calls, and 24 cumulative hours of cell execution, bounded further by
each allocation. It revisits the evidence task with its evolving memory. Its
allocation ending is recorded as a budget stop, not completed research.

The initial serving profile selects one exposed Intel Level Zero device per node.
Using the remaining devices for replicas or model distribution is subsequent
capacity work. Agent populations are logical identities, not simultaneous model
copies or demonstrated hardware capacity.

Each agent's private history is separate. Sharing requires a structured model
choice, retains source ancestry and authorship, and is limited to the cell's
audience. Withdrawal stops future retrieval of that publication. Audit logs are
retained even when a condition does not provide persistent memory to the agent.
Models receive evidence packets and have no shell or arbitrary network tools.

## Inspect, reconnect, resume, and export

Use the `run_id` printed by the plan/launch command:

```sh
make stampede STAMPEDE_ARGS='status --run-id RUN_ID'
make stampede STAMPEDE_ARGS='fetch --run-id RUN_ID --destination .engram/stampede/exports'
make stampede STAMPEDE_ARGS='resume --run-id RUN_ID'
```

Repeating `deploy` reconnects to the recorded submission; it does not submit a
duplicate job. `resume` explicitly requests another allocation for unfinished
work after Slurm confirms the previous job is terminal. It uses the saved source
and configuration, stable cell identities, and existing checkpoints. Active or
ambiguous jobs cannot be blindly resubmitted. An ambiguous submission remains
visible until its outcome can be established.

Local state and the original source bundle live at
`.engram/stampede/runs/RUN_ID`. Preserve this directory. Changing the source or
configuration under an existing run ID is rejected; use a different run ID for
a different campaign. `resume` uses the saved bundle even if the checkout changes.
The configurable `seed` (default `20260912`) sets scheduling and model sampling;
change it with a new run ID for a separate replication. A seed does not guarantee
identical GPU outputs across hardware or serving implementations.

`fetch` creates a local archive containing complete checkpoint generations,
results, configuration, source, logs, and small model/backend manifests. It takes
a short per-cell snapshot lock while copying the selected generation. Log files
are observations at export time; the export is not one synchronized instant
across every cell. Model weights, virtual environments, builds, and caches are
excluded. Keep an off-cluster export: `$WORK` is not a backup.

`status` distinguishes submission, actual inference verification, partial work,
and completion. A queued job or Slurm exit alone does not prove the campaign
worked. Independent probe failures and node/cell errors remain in the artifacts
for cross-comparison and diagnosis.

## Rehearse now

```sh
make stampede-simulate
make stampede-simulate
```

The first invocation runs the full 20-cell matrix at populations 2/4 and request
caps 1/2, using real Storage and sharing. The second restores completed cells and
makes zero new scripted model calls. Inspect
`.engram/stampede/simulation/simulation.json` and its `durable/` directory.
Use `STAMPEDE_ARGS='--output /absolute/path --workers 2'` for another rehearsal.
This command needs no SSH, model credentials, model download, or GPU.

The deployment bundle includes only the dedicated campaign code/corpus and
allowlisted Engram source/resources/lockfile. It excludes local memory homes,
session archives, keys, environment files, and unrelated documents. The accepted
data mode is currently `synthetic`; selecting a public aDNA corpus will require
an explicit ingestion addition. Live cross-node sharing, adaptive research tasks,
learned dispositions, scientific evaluation, and the larger diagnostic presets
are outside this initial bootstrap.
