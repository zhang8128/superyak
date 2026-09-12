# Stampede launcher report

## Scope and interfaces

The local launcher is implemented in `deploy.stampede` with Python's standard
library. It does not make a remote call unless `deploy`, `resume`, `status`, or
`fetch` is selected.

- `default_config()`, `load_config(path)`, and `validate_config(config)` expose
  the version-one JSON contract and enforce a four-node, twelve-hour maximum.
- `prepare_bundle(source, destination)` creates a byte-deterministic tar.gz with
  normalized metadata and a SHA-256 manifest. The allowlist names the Stampede
  implementation files, the dedicated corpus subtree, Engram root Python
  modules, its lock/project files, migrations, prompts, and Lighthouse schemas.
  Hidden directories, `.engram`, environment files, keys, session archives, and
  arbitrary documents are outside the allowlist.
- `generate_batch_script(config, ABS_RUN_DIR)` emits one task per node and calls
  `ABS_RUN_DIR/.venv/bin/python -m deploy.stampede.cluster batch --run-dir
  ABS_RUN_DIR`. It requests the configured account, PVC partition, node count,
  walltime, and a four-minute Slurm warning signal.
- `Launcher.plan`, `deploy`, `resume`, `status`, and `fetch` implement the local workflow.
  `CommandBoundary` is the only SSH/SCP process boundary and always receives an
  argv list; no local shell evaluates configuration data.
- `create_export(run_dir, output)` takes the same short per-cell `snapshot.lock`
  used by checkpoint writers, copies `CURRENT` and its named complete generation
  into a private freeze directory, verifies source and copied-file digests, and
  publishes an immutable archive plus a digest sidecar.

The experiment-requested `max_calls_per_cell` (default 2048),
`max_prompt_chars` (default 32000), and `seed` (default 20260912) are included in
validation and the example config. A zero `community_population` explicitly
disables the continuing community; the default plan reports 20
comparison/reference runs and one community run.

## Commands

```sh
python -m deploy.stampede plan --config deploy/stampede/config.example.json
python -m deploy.stampede deploy --config /path/to/stampede.json
python -m deploy.stampede status --run-id RUN_ID
python -m deploy.stampede resume --run-id RUN_ID
python -m deploy.stampede fetch --run-id RUN_ID --destination /path/to/results
python -m deploy.stampede simulate --output /path/to/offline-run --workers 2
```

Local durable state defaults to `.engram/stampede/runs/RUN_ID`. An empty run ID
is derived deterministically from the validated config. Supplying an explicit
run ID permits named campaigns, but changed config or source content is rejected
without overwriting the original local evidence.

Deployment requires TACC's `$WORK`, resolves it over SSH with no home-directory
fallback, and stages `source.tar.gz`, `config.json`, and `batch.sh` under
`$WORK/REMOTE_SUBDIR/runs/RUN_ID`. It then runs the remote bootstrap and submits.
Before every submission it checks the generation marker and Slurm by the unique
generation job name. The remote submit step uses an atomic directory lock and
writes `submissions/000001.json` plus the latest `submission.json`. Local state
records `submission_attempted=true` before the SSH call. If that call disconnects
and neither the marker nor Slurm can prove the outcome, the run becomes
`uncertain`; later deploy calls refuse to submit again.

`resume` is the explicit way to request another allocation for incomplete cells.
It first proves the current numeric job ID is terminal using both `squeue` and
`sacct`, rejects an active or unknown job, verifies the saved local config and
source bundle, and refuses a remotely verified complete campaign. It then records
the prior job in `submission_history` and uses the next generation (`g2`, `g3`,
and so on) for both the job name and atomic marker. An ambiguous resume is subject
to the same no-resubmit reconciliation rule.

Submission and queue activity are not reported as healthy. `status` reports
healthy or complete only from remote campaign status with
`hardware_verified=true`. A completed Slurm job without campaign evidence is
`job_finished`, unhealthy, and incomplete. A status file whose job ID belongs to
an earlier submission generation is retained as `previous_job_status` and cannot
complete or mark the current job healthy. A current-job `running` status is also
checked against Slurm; terminal failure overrides a stale heartbeat, terminal
Slurm completion remains `job_finished` until campaign completion is recorded,
and unknown scheduler evidence is unverified. `fetch` runs the remote export helper
and retrieves its unexpanded archive and digest sidecar. The archive contains
status, config, source bundle/manifest, backend selection, node logs/probes, cell
results and restorable complete checkpoint generations, and small model/profile
manifests. Model weights, profile environments, build trees, and caches are
excluded. Local SHA-256 verification must match both remote metadata and the
sidecar before temporary downloads replace a prior fetch.

## Verification

Tests were written and observed failing before each launcher behavior was added
or repaired. The focused command is:

```sh
PYTHONPATH="$PWD:$PWD/engram" /Users/kairos/Projects/superyak/engram/.venv/bin/python \
  -m pytest engram/tests/test_stampede_launcher.py -q -ra --tb=short
```

Latest focused result at report creation: `24 passed`. Tests create and inspect
real archives, execute a generated batch script, persist real local state, check
input-preserving resume behavior, race `CURRENT` replacement/deletion against a
real locked export, reject corrupt checkpoint generations, exercise CLI
simulation forwarding, and use a recording fake only at SSH/SCP/Slurm
boundaries. `py_compile`, `bash -n` for the bootstrap, an actual offline `plan`,
and whitespace checks also passed.

The combined offline Stampede component and integration suite also passed:
`101 passed in 32.58s` across launcher, cluster, experiment, provider, and
integration tests.

## Limitations

No SSH login, remote bootstrap, Slurm submission, model download, or Intel GPU
probe was performed. TACC allocation/account validity, host drivers, backend
compatibility, and achievable population/concurrency remain unverified until a
real deployment. The shipped launcher accepts the synthetic data mode only;
public aDNA sources require a separately reviewed explicit source-selection
interface and are never inferred from a workstation. Interactive site login may
still be required by SSH during the single deploy invocation.
