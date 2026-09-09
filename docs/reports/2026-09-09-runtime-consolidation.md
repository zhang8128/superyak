# Runtime consolidation — 2026-09-09

Superyak is the canonical source checkout. PR #4 merged as `431d474`, preserving
both the capture repair (#3) and session messaging (#2) histories; GitHub marked
all three PRs merged. The canonical Python environment was synced from the lockfile
and its code origins verified. Lighthouse was built in the canonical checkout.

## Installed layout

| Component | Active location |
| --- | --- |
| Source | `/Users/kairos/Projects/superyak` |
| Shared launcher | `~/.local/bin/superyak-runtime` |
| Runtime binding | `~/.config/superyak/runtime.json` |
| Existing memory home | `/Users/kairos/Projects/engram` |
| Publisher supervision | `gui/501/com.kairos.superyak-lighthouse` |
| Old Lighthouse path | Symlink to `superyak/lighthouse` |
| Standalone Lighthouse history | `Projects/Archive/lighthouse-standalone-20260909` |

Codex MCP/hooks, Claude plugin bindings and marketplace settings, and the Loom
and Smart project MCP entries use the shared launcher. Project-root overrides
are retained. Loom and Smart name instances whose databases do not exist; their
existing fallback to the central legacy database is unchanged.

Standalone Engram retains its `.engram` data and Git history. Its MCP and three
hook entry points are compatibility delegates, recorded in local installation
commit `79eba4c`. Its README and AGENTS.md direct development to Superyak. The
Loom binding is recorded in local commit `c8a7ca9`. These host installation
commits were not pushed to their standalone repositories.

Only receiver `engram` is enabled, with publisher `lighthouse`, context
`memory/technical`, purpose `session-recall`, and limit 1. Both policy files and
all 15 existing shared items match their pre-cutover fingerprints. No sharing
audience or expiry was expanded. The receiver's existing expiry is October 15,
2026; the publisher's existing expiry is January 1, 2027.

## Verification

- Final code CI: 2,254 Python tests passed, 5 platform/opt-in skips; Lighthouse,
  interoperability, and Codex session-delivery jobs passed.
- Independent standards/spec review and scoped fix verification passed.
- Focused runtime/hook/packaging checks: 75 passed, 2 opt-in skips.
- Integration: 2 schemas, 7 real-socket checks, and 4 validated receipts passed,
  including denied/withdrawn sharing controls on disposable data.
- Installed Codex configuration and automatic-capture checks: 11 passed.
- All four compatibility entry points forwarded to the installed runtime.
- Installed status reports the canonical source, original named receiver store,
  enabled receiver, available publisher, and connected socket.
- Supervised publisher restart passed, becoming ready in 7.631 seconds. Its
  first startup exceeded the initial 25-second readiness probe, then became
  healthy without a source/configuration change.
- Existing shares and policies delivered one item and persisted a receipt in a
  disposable snapshot preflight before deployment.

**Live recall verification remains pending.** The fresh installed MCP attempt
failed while writing its session-start log because a separate, already-running
legacy MCP process owns the receiver database's write lock. Lock ownership was
confirmed without modifying the database. That process is still doing embedding
work. It has not been interrupted; permission to restart only that older MCP
process is pending. No successful live crossing or live receipt is claimed.

Already-running MCP hosts retain their loaded code until they reconnect. Future
launches through the old compatibility paths select the canonical runtime.

## Recovery evidence

The private backup and verification directory is:

`/Users/kairos/.local/state/superyak/backups/20260909T201052Z`

It contains 26 online SQLite snapshots, original configuration bytes and modes,
Git provenance, the reviewed 20-entry installation manifest with 35 frozen
artifact hashes, independent reviews, test logs, and verification metadata.

Run `superyak-rollback-install-20260909.py` there without arguments to check
rollback preconditions, or with `--apply` to stop the supervised publisher and
restore unchanged installation bindings. Ordinary rollback deliberately retains
all current SQLite state, including memories written after the backup. Do not
restore database snapshots indiscriminately.

`superyak-restore-lighthouse-path-20260909.py` separately checks/restores the
archived standalone Lighthouse path; use `--apply` only when restoring that
layout. Both rollback preflights passed after installation. Installation commits
remain in Git history if files are restored; original refs are recorded in
`git-before-cutover.json`.
