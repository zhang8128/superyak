---
id: before-push
title: Before any push
when: command git push; command push origin; command push -u origin; command push https://
version: 2
owner: ships of this repository
see: docs/checklists.md#before-any-push
---
- [ ] No commit in the push is from the old history: in bash or zsh, with B=60dd85175a1709627be63a4678694029c5721b74 and the ref you push in place of HEAD, the comm line (docs) prints nothing, and no error.
- [ ] Before merging a gh/*, origin/* or bundle ref: `git merge-base --is-ancestor $B <ref>` says ok, and the comm line with <ref> for HEAD prints nothing. A fetch without + can leave a stale ref.
- [ ] killer: Nothing in the diff names a person with health, contact or identity details, or holds a key or token (gitleaks, plus a read of every new doc). Once pushed, it can't be pulled back.
- [ ] killer: Nothing in the diff describes a security hole that isn't fixed and live yet, in code, docs, lessons or commit messages. It stays in a members-only room until the fix ships.
- [ ] The push is needed now: a build branch goes up once, when ready for review or merge (every push runs CI).
- [ ] Each commit's message says which ship made it: every ship commits as zhang8128, so the author field can't tell them apart.
- [ ] A fix that isn't live yet goes between machines by Taildrop bundle, never a push, until it is live: a push publishes its diff, tests and messages.
