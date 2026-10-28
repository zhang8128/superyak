---
id: session-start
title: A session starting
when: start
version: 1
owner: ships of this repository
see: docs/checklists.md#a-session-starting-or-restarting-any-ship
---
- [ ] The station watch is held (`station_watch writable=true`).
- [ ] The kick watcher is armed: `make kick` under a Monitor, re-armed at its expiry notice, after checking by task list or pid that none already runs on that cursor.
- [ ] Before acting on a head named in the unread backlog, check the author's latest posted head for that branch: the backlog arrives oldest first.
- [ ] The 10-minute tick exists.
- [ ] The background work in flight is listed, and anything cut off is resumed or restarted (check git status in each worktree).
- [ ] Unread messages and the board's claims are read; stale claims are released.
- [ ] A session that watches or loops never waits on a question at its own terminal: post it in the room, rule where you may, keep working; what only Andy decides waits for him.
