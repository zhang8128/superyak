# Porting a store from another machine

Opening a store normally changes it. `Storage.__init__` runs pending
migrations (004 discards vectors; 015 and 026 rewrite rows). The server's
start also syncs genome and inbox episodes into a named instance and runs
sleep maintenance. Decay counts hours since last access, so a long-idle store
can be pruned into `cold.db` on its first open. Survey and read a ported store
before any of that happens.

## What to copy

- The store directory: `$ENGRAM_HOME/.engram/` (the server defaults
  `ENGRAM_HOME` to the engram checkout, not `~`), including
  `instances/<name>/` when named instances were used. Keep each `graph.db`
  together with its `-wal`/`-shm` files, and `cold.db`.
- `~/.reader/reader.db` (or `$READER_DB`), which holds the passage and
  reaction pairs read by `deep_pass.py`.
- The Engram commit the store ran under, and `.engram/config.toml`.

## Procedure

1. Copy into a new directory outside any `ENGRAM_HOME`. Keep one pristine
   copy that is never opened. Record hashes:

   ```sh
   engram-read-store survey pristine/graph.db pristine/cold.db pristine/reader.db
   ```

   `survey` reports file and side-file hashes, applied/pending/unknown
   migration versions, row counts, and episode date and session ranges.
   Pass `--immutable` for an archive with an empty or absent `-wal`; it then
   creates no side files. With a non-empty `-wal`, survey without it so the
   uncheckpointed pages are included.

2. Read in order, one entry at a time:

   ```sh
   engram-read-store sessions pristine/graph.db
   engram-read-store read pristine/graph.db --session <id> --start 0
   engram-read-store passages pristine/reader.db --start 0
   ```

   `read` pages episodes by `(created_at, id)` using whichever columns the
   store's schema has. `passages` follows each reading session's start, then
   passage position. `--json` gives machine-readable output.

3. Calibrate before anything else opens it:

   ```sh
   engram-calibrate pristine/graph.db --out calibration-1
   ```

   This snapshots the store through a read-only connection (immutable when
   no WAL pages are pending, so nothing is created beside it), migrates only
   `calibration-1/working.db`, and writes `report.md`/`report.json`: how many
   episodes decay would move to `cold.db` if the store were opened now, sheaf
   cohesion energies, persistence distributions and hub classes. It refuses
   to report success if the source's bytes changed. `--no-migrate` analyses
   the copy at its own schema.

4. Upgrade only a separate working copy, as a new instance directory with no
   `genome/graph.db` or `signals.db` beside it, and keep maintenance off
   until decay and pruning are deliberately chosen.

## Known gaps

Stores carry no instance ID; the directory name is the identity. Genome sync
assigns copied episodes new IDs and does not keep the original ID or
timestamp. Both matter for provenance across ported and shared stores.
