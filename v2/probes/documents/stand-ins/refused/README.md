# Two stand-ins for a refused hand-in (spec 2026-11-19, "On the real room")

Run by a person on the real room, one row each, with no model. Neither is a guard: they describe what the room does.

- `codex`: put this directory first on the clock's search path and run the row with the worker `codex:<any model>`,
  so that the room commits for it. It changes a source file, commits nothing and leaves `scratch-repository/.git`.
  Expected: the room refuses; the row's record says outcome `refused` and `no_commit` `refused: single repository`.
- `worker.sh`: run the row with the worker `script:<path to worker.sh>`. It commits the same change itself, then
  leaves the same directory. Expected: outcome `handed-in`, `no_commit` null, since the room does not commit for it.
