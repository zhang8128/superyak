# Contributing: setup and checks

This is the full setup, check and interoperability guide for working on Superyak.

Use Python 3.13, uv, Node.js 24 or newer, pnpm 11.20.0, and Make on Linux or
macOS. CI uses Python 3.13, uv 0.8.3, Node.js 24, and pnpm 11.20.0.
Engram's package supports Python 3.12 or newer; the shared setup defaults to 3.13.

```sh
git clone https://github.com/zhang8128/superyak.git
cd superyak
make setup
make check
```

`make setup` installs `engram/uv.lock` into `engram/.venv`,
`atlas/uv.lock` into `atlas/.venv`, and
`lighthouse/pnpm-lock.yaml` into the Lighthouse workspace, then builds its
packages. It also installs `peer/uv.lock` independently and installs the
`tuning/uv.lock` CPU training and development environment. For browser checks, run
`uv run --locked --project peer playwright install chromium` (Linux CI adds
`--with-deps`). `make check` runs the Engram, Atlas, peer, and clinical/biotech
tuning suites in separate processes, Lighthouse build/lint/typecheck/tests and
proofs, and the interoperability checks. Each check is also available separately
through `make check-peer`, `make check-team`, `make check-agent`,
`make check-tuning`, `make check-engram`,
`make check-atlas`, `make check-lighthouse`, and `make check-integration`. Run
`make help` for the command list.

The interoperability check uses disposable synthetic stores and a real local
Unix socket. It checks both shared schemas and validates four Engram receipts
with Lighthouse's CLI, including denial and withdrawal scenarios. It also
checks Unicode artifact digests and scoped receipt exports across both languages.
Atlas's public pilot publications are also validated by the Python and
TypeScript implementations, including their policy decisions.
These cross-language regression tests require the built Lighthouse packages in
`make check-integration`; Python-only test runs skip them when that setup is absent.
The interoperability check requires no model credentials or configured live
publishers.

Two Engram tests inspect a developer's live Codex configuration and are skipped
by default. To run those tests, explicitly supply both
`ENGRAM_LIVE_CODEX_CONFIG=/absolute/path/to/config.toml` and
`ENGRAM_LIVE_CODEX_PROJECT=/absolute/path/to/the/bound/engram` when running
`make check-engram`. An explicitly supplied invalid configuration fails the tests.
