# Settings that act on a store come from the store's home: design

2026-11-20, by Serenity. Branch `serenity/store-settings-from-home`. Found while measuring the sheaf for
`2026-11-20-sheaf-kernel-design.md`.

## The fault

An Engram server keeps its memories under `ENGRAM_HOME` and reads its config from the folder the session starts in
(`load_config(PROJECT_ROOT)`). `load_config` writes a default config into any folder that has none. The defaults
switch off the three gates that act on a store during maintenance:

| Section | What it does to the store |
| --- | --- |
| `[cohesion]` | the sheaf's sleep pass: splits a summary whose source episodes do not glue |
| `[persistence]` | guarded forgetting |
| `[category_evolution]` | the evolving-category runtime |

So a store calibrated and switched on in its home ran with those gates off from every other folder, and nothing
said so. On one live store, read on 2026-11-20: its home config has `[cohesion] enabled = true` at a calibrated cost
and `[category_evolution] enabled = true` in shadow; the sheaf pass ran 107 times from 2026-07-01 to 2026-09-07 and
never since; every maintenance report since then lists the sheaf step as `ok` with nothing done; the
evolving-category store was last written on 2026-09-18. The sessions since then started in other folders.

## The rule

A setting that changes a store is the store's. `config.with_store_settings` takes those three sections from
`<ENGRAM_HOME>/.engram/config.toml`. Every other section still comes from the project's file, the instance binding
included.

- A section the home's file leaves out, a home with no config file, and a home file that can't be parsed all give
  that section's defaults, which are off. A gate never comes on because a file was missing or broken.
- The project's value for these three is never used. A project that asks for one the store has off gets a warning
  naming both files, so the reverse of this fault can't happen quietly.
- Reading the home's config writes nothing there.

## What changes when this is deployed

- **A store whose home has a gate on and whose sessions start elsewhere:** the gate comes back on. For the store
  above that is the sheaf pass (run read-only today at its calibrated cost, it would split none of 266 summaries)
  and the category runtime in shadow, which influences no recall.
- **A project file that switched a gate on for a store whose home has it off:** that gate goes off, with the warning.
- **The Pi:** the one config found there has all three off. No change expected; the deploying ship reads the Pi's
  home config before the restart and says what it found.

## Undo

Revert the commit, or set the section in the home's config.

## Not decided here

Whether the other memory sections (`[memory]`, `[compression]`, `[ranking]`, `[embedding]`) should move too. They
also shape a store, but they have per-project uses today (a project's default lane), so they stay.
