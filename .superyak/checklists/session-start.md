---
id: session-start
title: A session starting
when: start
version: 1
owner: ships of this repository
see: docs/checklists.md#a-session-starting-or-restarting-any-ship
---
- [ ] The station watch is held (`station_watch writable=true`).
- [ ] The kick watcher is armed: `make kick` under a Monitor, re-armed every 30 minutes.
- [ ] The 10-minute tick exists.
- [ ] The background work in flight is listed, and anything cut off is resumed or restarted (check git status in each worktree).
- [ ] Unread messages and the board's claims are read; stale claims are released.
