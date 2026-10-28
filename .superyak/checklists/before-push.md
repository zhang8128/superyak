---
id: before-push
title: Before any push
when: command git push; command push origin; command push -u origin; command push https://
version: 1
owner: ships of this repository
see: docs/checklists.md#before-any-push
---
- [ ] The branch's base is on the rewritten history: `git merge-base --is-ancestor 60dd851 HEAD`. Where `git config core.hooksPath` prints scripts/git-hooks, the pre-push hook checks it too.
- [ ] killer: Nothing in the diff names a person with health, contact or identity details, or holds a key or token (gitleaks, plus a read of every new doc). Once pushed, it can't be pulled back.
- [ ] killer: Nothing in the diff describes a security hole that isn't fixed and live yet, in code, docs, lessons or commit messages. It stays in a members-only room until the fix ships.
- [ ] The push is needed now: a build branch goes up once, when ready for review or merge (every push runs CI).
- [ ] Each commit's message says which ship made it: every ship commits as zhang8128, so the author field can't tell them apart.
