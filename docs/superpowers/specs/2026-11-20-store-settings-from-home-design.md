# Settings that act on a store come from the config beside that store: design

2026-11-20, by Serenity. Branch `serenity/store-settings-from-home`. Found while measuring the sheaf for
`2026-11-20-sheaf-kernel-design.md`. Draft 2: a fresh reader rejected draft 1, rightly (see "The reader's finding").

## The fault

An Engram server keeps its memories under `ENGRAM_HOME` and reads its config from the folder the session starts in
(`load_config(PROJECT_ROOT)`). `load_config` writes a default config into any folder that has none. The defaults
switch off the three gates that act on a store during maintenance:

| Section | What it does to the store |
| --- | --- |
| `[cohesion]` | the sheaf's sleep pass: splits a summary whose source episodes do not glue |
| `[persistence]` | guarded forgetting |
| `[category_evolution]` | the evolving-category runtime |

So a store that had one of these switched on ran with it off from every other folder, and nothing said so. On one
live store, read on 2026-11-20: the config in its home has `[cohesion] enabled = true` at a calibrated cost and
`[category_evolution] enabled = true` in shadow; the sheaf pass ran 107 times from 2026-07-01 to 2026-09-07 and never
since; every maintenance report since then lists the sheaf step as `ok` with nothing done; the evolving-category
store was last written on 2026-09-18. The sessions since then started in other folders.

## The rule

A setting that changes a store is that store's. `config.with_store_settings` takes those three sections from the
`config.toml` in the folder that holds the store's `graph.db`:

| Store | Its file |
| --- | --- |
| the default store, `<home>/.engram/graph.db` | `<home>/.engram/config.toml` |
| an instance, `<home>/.engram/instances/<name>/graph.db` | `<home>/.engram/instances/<name>/config.toml` |

The server applies it after it has chosen the store, so a binding to an instance whose store is missing, which
falls back to the default store, reads the default store's file. Every other section still comes from the
project's file, the instance binding included.

- A section the store's file leaves out, a store with no such file, and a file that can't be parsed all give that
  section's defaults, which are off. A gate never comes on because a file was missing or broken.
- The project's value for these three is never used. A project that asks for one the store has off gets a warning
  naming both files, so the reverse of this fault can't happen quietly. Only `enabled` is compared: a project file
  made from defaults always differs from a calibrated store in its other values, and a warning in every folder at
  every start would teach people to ignore it.
- Reading a store's config writes nothing beside the store.

## The reader's finding (draft 1 was rejected)

Draft 1 read the three sections from `<home>/.engram/config.toml` for every store under that home. One home holds
several stores, and a gate is calibrated against one of them. So a session bound to any sibling instance would have
run the sheaf pass, or forgetting, against a store it was never calibrated for, with no warning, since nothing
disagreed. The reader showed it with two instances under one home. Draft 2 keys the file on the store opened, and a
test holds that a gate on for one store is off for its sibling.

## What changes when this is deployed

- **Nothing comes on by itself.** A gate is on only where a `config.toml` beside that store says so.
- **The default store of a home whose config has a gate on, with sessions that start elsewhere:** that gate comes
  back on.
- **An instance store whose gate was switched on in its home's file** (how the live store above was set, when its
  sessions started in the home folder): it stays off until the section is put in the instance's own file. For that
  store this is a one-time copy of the two calibrated sections; run read-only today at its calibrated cost, the
  sheaf pass would split none of its 266 summaries.
- **A project file that switched a gate on for a store that has it off:** that gate goes off, with the warning.
- **The Pi:** the one config found there has all three off. No change expected; the deploying ship reads the config
  beside each of the Pi's stores before the restart and says what it found.
- **Tests that hand the server a whole config in memory** (`tests/test_category_server.py`, one in
  `tests/test_server_registry.py`) replace `with_store_settings` as they already replace `load_config`: the config
  under test is theirs, gates included. Six of them failed on draft 1's code and were not run before it was pushed.

## Undo

Revert the commit, or set the section in the file beside the store.

## Not decided here

Whether the other memory sections (`[memory]`, `[compression]`, `[ranking]`, `[embedding]`) should move too. They
also shape a store, but they have per-project uses today (a project's default lane), so they stay.
