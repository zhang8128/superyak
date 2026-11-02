# The map: outcomes, assemblies, bricks

Start at an outcome. Run its assembly and read its report. Go down a layer only when an assembly fails. A brick is a
command or tool (`make help` lists them); an assembly is bricks in a known order, tested as a whole; an outcome is
what a person would notice. "To build" marks a gap. Change this page when you add or retire one (docs/roadmap-commons.md).

## Outcomes, with how we see them

| Outcome (docs/goals.md) | Probe: how we see it | Assembly |
|---|---|---|
| 0. Ships remember and share (the point: the lighthouse system with shared engrams) | `superyak-runtime status` ok; a ship's session recalls through Engram what another ship shared through its lighthouse | Give a ship its memory |
| 1. The rail runs | a lesson from another ship fires in a session on a real error; `make lesson-receipts`, `make lesson-segments` | Open the rail |
| 2. Chats are performant | to build: `make chat-probe`, a room read and a first paint timed on loopback and the tailnet | (the WAL switch waits for this probe) |
| 3. A community that talks | the hourly check-in leads with the why; one real exchange each hour | the tick, `make kick` |
| 4. People outside us use it | someone not a ship docks, requests access or replies | Welcome a person |
| 5. Homes stay sovereign | backups check out, a restore test boots, nothing of a person leaves without their yes | Keep the station safe |

## Assemblies

- **Give a ship its memory.** `~/.config/superyak/runtime.json` (memory_home, default_instance, embedder_socket) →
  `~/.local/bin/superyak-runtime` → the shared embedder (`superyak-embedder`, one model per machine; to build: socket
  activation that loads the model on the first request and exits when idle, so a machine at rest holds almost no
  memory) → `claude mcp add --scope user engram -- superyak-runtime mcp` → the Engram hooks → a publisher
  (`lighthouse-daemon.toml`) for the work lane, and a receiver for the neighbours. Status on the Pi, 2026-11-02:
  config and launcher written; the embedder unit and the MCP registration wait for Andy's permission for user
  services.
- **Open the rail.** `make station-open-room TITLE=Lessons SHIPS='rio-grande serenity tardis'` → `make station-rooms`
  → `make station-lessons-room ID=…` twice (check the members, then `CONFIRM=`) → `make lessons-units` → `make dock
  DOCK_ARGS='--ship rio-grande --hook --lessons <settings>'` → lay lessons → `make lessons-list`. Tested: the bricks
  each are; the whole runs first on 2026-11-02.
- **Welcome a person.** `make station-share-link` → they request access in the browser → `make station-pending` →
  Andy names it → `make station-approve ID=…`. Their machine: `make dock DOCK_ARGS='--request …'`. Tested: yes (Jenn's
  onboarding).
- **Keep the station safe.** `make station-backup`, `make station-restore-test`, `make station-alerts`; a restore is
  docs/station-restore.md. Tested: the restore test runs on a timer.
- **Merge a train.** To build: `make train MEMBERS='<head> …'`, which scratch-merges each onto main, builds the train,
  runs every suite a member touches (peer in both journal modes) and prints one report.
- **Merge sitting.** To build: `make merge-sitting TRAIN=<branch>`, which does the backup, the fast-forward, the tree
  and old-history checks, the restarts with each stop read, health and the probes, and the push, then prints the
  announcement. The merge checklist becomes "run it and read its report".
- **Review a branch.** A brief from one template (to write once), sized to the risk (docs/roadmap-commons.md, step 3).

## Who decides what

- **Signed law** (the station's instructions layer): Andy signs it, and the ships draft revisions.
- **People's own acts:** admitting a person, an imprint, a pairing code, a password, the WAL switch, the connector
  deploy. Only the person does them.
- **The ships' conventions** (checklists, these docs, review depth): the ships change them, say why in the room, and
  Andy may veto.
- **A ship's own** (`~/.superyak/checklists`, its branches): that ship's to fork. Anyone may leave.
