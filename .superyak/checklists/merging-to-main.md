---
id: merging-to-main
title: Merging to main
when: command git push origin main; command push origin main; command push https://github.com/zhang8128/superyak.git main; command systemctl --user restart superyak-
version: 1
owner: ships of this repository
see: docs/checklists.md#merging-to-main-law-section-2
---
- [ ] killer: Safety code (authority, permissions, the public route, a person's data) merges only on explicit yeses posted in the room, the section 2 approver's among them. No ship's silence counts.
- [ ] A section 2 verdict is posted whole in the room: Serenity for Rio Grande's branches, Rio Grande for Serenity's, or a fresh Pi reviewer.
- [ ] Main is merged into the branch (never a rebase), and the merge commit is the one the verdict names. An unpushed merge is agreed by tree: `git rev-parse <commit>^{tree}` on both machines.
- [ ] The Pi suites pass at that commit (engram, peer and agent, whichever the diff touches); known failures are named (the 3 Kuzu tests).
- [ ] GitHub CI's result is read, including the jobs the Pi can't run.
- [ ] The `only-include` lists name every new module and test file (by hand for agent's modules and peer's tests until their tests are on main); the package builds and imports in a clean venv.
- [ ] The station database is backed up (`make station-backup`).
- [ ] killer: Main is pushed once. Affected Pi services are restarted and checked, a touched public route probed from outside; if a check fails, revert and restart. A security fix is live before its push.
- [ ] If it breaks at 3 a.m., what tells us, and who? Name the check: a dying unit alerts Odo in Ops; route-watch watches a route once its timer is installed; else say that nothing watches it yet.
- [ ] The merge is announced in the room, and its board item is marked done.
- [ ] Reflect is run once the merge is announced.
