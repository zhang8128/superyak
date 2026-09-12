# Stampede3 launch preparation

Prepare one command that stages and starts a resumable Intel PVC research deployment once SSH and allocation access exist. It must work before patient or participant details exist. Startup uses a bundled synthetic evidence task; explicitly selected public aDNA ingestion is follow-up work. No patient, participant, institutional review, or collaboration-account information is a prerequisite.

The first campaign cross-compares individual persistence off/on, shared persistence off/on, populations 32/128, and in-flight model-call caps 4/16. These are experimental settings, not demonstrated capacity. A separate 64-member community can continue while comparison cells rotate on other nodes. One-node deployments retain the same experiment queue. Memory stores are node-local; durable snapshots go to the run directory. A failed probe or cell records its reason and does not block unrelated cells.

The local launcher is Python standard library and SSH/SCP; the remote bootstrap installs isolated user-space dependencies, probes Intel inference on compute nodes, and runs bounded node workers through the site-supported launcher. Source staging uses an explicit allowlist, never a copy of the user's working directory or memory home. Do not transmit keys, environment files, local memory, session archives, or medical documents implicitly. No actual Stampede3 submission occurs while preparing this implementation.

The launcher offers `plan`, `deploy`, `status`, `fetch`, and `simulate`. Repeated `deploy` with the same run ID must reconcile prior submission rather than creating duplicate jobs. Preparation and cell completion have durable status. Failure and unverified deployment state must never be represented as healthy or complete. The initial Slurm budget is four PVC nodes for up to twelve hours; both are configurable and checked against explicit bounds. Deployment begins after one invocation; SSH authentication may require the site's normal interactive login.

Shared interface contract (JSON-serializable dictionaries):

```python
config = {
    "version": 1,
    "login": "", "account": "", "partition": "pvc",
    "nodes": 4, "walltime": "12:00:00", "run_id": "",
    "remote_subdir": "superyak",
    "model": "Qwen/Qwen3-8B", "model_revision": "main", "seed": 20260912,
    "backend": "auto", "cell_seconds": 5400,
    "populations": [32, 128], "concurrency": [4, 16],
    "community_population": 64, "max_turns": 12,
    "max_calls_per_cell": 2048, "max_prompt_chars": 32000,
    "max_output_tokens": 512, "request_timeout_s": 120,
    "data_mode": "synthetic",
}

# Model provider, implemented by controller:
class LocalModel:
    def __init__(self, base_url: str, model: str): ...
    def generate(self, messages: list[dict], *, max_tokens: int = 512,
                 timeout_s: float = 120) -> dict: ...
# Return {"text": str, "input_tokens": int|None, "output_tokens": int|None,
#         "model": str}; errors raise RuntimeError subclasses. No external credentials.

# Experiment API, implemented by experiment worker:
def build_cells(config: dict) -> list[dict]: ...
# cell keys: id, population, individual, shared, concurrency, seed, kind
def run_cell(cell: dict, config: dict, local_dir: Path,
             durable_dir: Path, provider, *, stop_event=None) -> dict: ...
# Result includes id, status, completed_turns, errors, usage; persisted atomically.

# Remote orchestration entry point, implemented by cluster worker:
# bash deploy/stampede/bootstrap.sh ABS_RUN_DIR
# bootstrap creates run-local Python environment then submits no jobs itself.
# python -m deploy.stampede.cluster batch --run-dir ABS_RUN_DIR
# called by generated Slurm script; fans out node-bound worker processes via ibrun.
```

The `main` model revision in the interface is a request to resolve a concrete hub revision before model use; persist the resolved revision and files manifest. Prefer a pinned known revision in shipped defaults if verified. Inference package versions and build revisions must be explicit in the selected profile and recorded. A compatible backend cannot be guaranteed without access to the host driver; parallel probes, independent failure status, and a tested local simulation must make that uncertainty actionable.

Use real Engram Storage and sharing/provenance mechanisms for experimental memory. Keep private history separate for every agent and shared publications audience-scoped. Imported shared statements retain authorship; publishing must be an explicit structured model choice. A deterministic provider is permitted only in clearly labeled simulation and mechanism checks. No arbitrary model-generated shell execution is needed for this bootstrap.

Every turn records source exposure, usage, and completion. Resume skips completed turns and cells and preserves individual identifiers. Ensure no two processes own the same cell concurrently. Snapshot live SQLite databases consistently, including changes in WAL, and restore only from complete generations. Synthetic tasks should test evidence revision and source ancestry without inserting invented biomedical facts into public research sources.

Tests must exercise actual local bundle creation, command execution boundaries, HTTP parsing, memory changes, sharing and withdrawal, status transitions, and resume behavior. Use fakes only at SSH/Slurm/GPU/model boundaries. Run the relevant existing repository checks and a full offline synthetic campaign before calling the launcher ready for use. Actual Intel and TACC compatibility remains explicitly unverified until the first deployment.
