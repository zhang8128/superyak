---
id: merging-to-main
title: Merging to main
when: command git push origin main; command push origin main; command push https://github.com/zhang8128/superyak.git main; command systemctl --user restart superyak-
version: 1
owner: ships of this repository
see: docs/checklists.md#merging-to-main-law-section-2
---
- [ ] killer: Safety code (authority, permissions, the public route, a person's data, the ledger) merges only on each partner's explicit yes posted in the room, the section 2 approver's among them.
- [ ] killer: The partners today are Rio Grande, Serenity and Tardis; an author's own branch counts as its yes. No ship's silence counts as consent. No ship pushes straight to main (law §7).
- [ ] Only Rio Grande and Serenity merge to main, on a verdict posted whole in the room: Rio Grande's for a Serenity branch; Serenity's, or a fresh Pi reviewer's that took no part, for a Rio Grande one.
- [ ] Main is merged into the branch (never a rebase), and the merge commit is the one the verdict names. An unpushed merge is agreed by tree: `git rev-parse <commit>^{tree}` on both machines.
- [ ] Pi suites pass (engram, peer, agent, as touched); a known failure is named and fails alike on main here. GitHub CI: a pushed head's before merge, main's after; red holds it unless known and boarded.
- [ ] The `only-include` lists name every new module and test file (peer's and agent's are held by test_packaging; check others by hand); the package builds and imports in a clean venv.
- [ ] The station database is backed up (`make station-backup`).
- [ ] killer: Main is pushed once. The affected Pi services are restarted and checked, and a touched public route is probed from outside; if a check fails, revert and restart.
- [ ] killer: A security fix is merged on the Pi, restarted and probed live before main is pushed, so its code is never public before the fix is live.
- [ ] If it breaks at 3 a.m., what tells us, and who? Name the check: a dying unit alerts Odo in Ops; route-watch watches a route once its timer is installed; else say that nothing watches it yet.
- [ ] The merge is announced in the room, and its board item is marked done.
- [ ] Reflect is run once the merge is announced.
