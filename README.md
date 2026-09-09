# Superyak

Engram and Lighthouse in one repository. Engram provides persistent memory and
the dynamic context runtime; Lighthouse defines the interchange protocol and
its TypeScript conformance kit. Their package boundaries and lockfiles remain
independent, with shared commands and CI at the root.

| Path | Contents |
| --- | --- |
| [`engram/`](engram/README.md) | Python memory system, MCP server, dynamic chat, and Lighthouse publisher/receiver |
| [`lighthouse/`](lighthouse/README.md) | Protocol schemas, TypeScript packages, adapters, bridges, and proofs |
| [`scripts/check_integration.py`](scripts/check_integration.py) | Schema agreement and Python-to-TypeScript receipt validation |

## Setup and checks

Use Python 3.13, uv, Node.js 24 or newer, pnpm 11.20.0, and Make on Linux or
macOS. CI uses Python 3.13, uv 0.8.3, Node.js 24, and pnpm 11.20.0.
Engram's package supports Python 3.12 or newer; the shared setup defaults to 3.13.

```sh
git clone git@github.com:zhang8128/superyak.git
cd superyak
make setup
make check
```

`make setup` installs `engram/uv.lock` into `engram/.venv` and
`lighthouse/pnpm-lock.yaml` into the Lighthouse workspace, then builds its
packages. `make check` runs the Engram suite, Lighthouse build/lint/typecheck/tests
and proofs, and the interoperability check. Each check is also available
separately through `make check-engram`, `make check-lighthouse`, and
`make check-integration`. Run `make help` for the command list.

The interoperability check uses disposable synthetic stores and a real local
Unix socket. It checks both shared schemas and validates four Engram receipts
with Lighthouse's CLI, including denial and withdrawal scenarios. It also
checks Unicode artifact digests and scoped receipt exports across both languages.
These cross-language regression tests require the built Lighthouse packages in
`make check-integration`; Python-only test runs skip them when that setup is absent.
The interoperability check requires no model credentials or configured live
publishers.

Two Engram tests inspect a developer's live Codex configuration and are skipped
by default. To run those tests, explicitly supply both
`ENGRAM_LIVE_CODEX_CONFIG=/absolute/path/to/config.toml` and
`ENGRAM_LIVE_CODEX_PROJECT=/absolute/path/to/the/bound/engram` when running
`make check-engram`. An explicitly supplied invalid configuration fails the tests.

## Run Engram

To ask another local Codex session a question, see
[Codex session messaging](docs/codex-sessions.md). `make sessions` lists session
metadata; the separate MCP server adds discovery, question, and reply tools.
It uses Codex's native queue alongside Engram and Lighthouse.

After setup, with the Codex CLI installed and authenticated:

```sh
make chat ENGRAM_ARGS='--no-engram --thread first-chat'
make serve ENGRAM_ARGS='--no-engram --thread browser-chat' SERVE_ARGS='--port 7434'
```

The web interface in this example opens at `http://127.0.0.1:7434`.
`ENGRAM_ARGS` holds options before the subcommand; `CHAT_ARGS` and `SERVE_ARGS`
hold options after it. The default provider is Codex, using the existing login.
The examples archive conversations locally under `engram/.engram/context-runtime`.

To use an existing memory installation, explicitly set `ENGRAM_HOME` to its
parent directory and pass `--instance` for the intended named instance. See the
[dynamic context guide](engram/docs/dynamic-context.md), especially
[Lighthouse sources for chat](engram/docs/dynamic-context.md#opt-into-lighthouse-sources-for-chat),
and the [receiver guide](engram/docs/lighthouse-receiver.md) for opt-in policies.

The imported Engram plugin's MCP and hook files retain their original
machine-specific bindings. Cloning this repository does not install those
bindings, move memory databases, or change a running service. The former
Lighthouse project binding is available as an optional
[`engram-project.toml` example](lighthouse/examples/engram-project.toml);
actual `.engram/` state is ignored.

For a shared installation, use the repository's canonical
[`scripts/runtime.py`](scripts/runtime.py) launcher to keep source code separate
from the existing memory home. The launcher requires an explicit runtime JSON
file and provides MCP, hook, publisher, and read-only status commands. See
[Runtime installation](docs/runtime-installation.md) for the configuration,
stable wrapper, supervision, health, restart, and rollback procedures.

Both source histories are retained. See the
[migration record](docs/monorepo-migration.md) for exact source revisions and
the relationship to the original checkouts.
