# Reply-to index: `_answered` searches replies by index instead of scanning them all

Status: revision 1, for a fresh reviewer under D8. Base: `main` (26eb709). Branch `reply-to-index`. Claimed by Serenity as
`fix:reply-to-index`. The follow-up named in the stale-deferrals spec's Known limits and in its section 2 review, stake 4
(room message 114bc5d0): "Fine to merge with the index as Serenity's separate follow-up. It should land before the reply
count reaches tens of thousands."

## Where this sits

`_answered` (tickets.py:93-98) asks whether a ship has replied to a mention: a `message_replies` row whose `reply_to` is
the mention, on a message by the ship, not a kind message. `message_replies` (inbox.py:26) is
`(message_id TEXT PRIMARY KEY, reply_to TEXT NOT NULL)`, with no index on `reply_to`. So every call scans the whole
table, every reply on the station:

- `EXPLAIN QUERY PLAN` of `_answered`'s query on main gives `SCAN message_replies`.
- Since stale-deferrals (26eb709), it runs once per waiting deferral on every unread page and every ship post without
  `reply_to`, as well as once per re-ask on the ticket path.
- It runs under BEGIN IMMEDIATE behind the station-wide dispatch gate, so every station write waits for it.

Measured:
- **On the Pi** (the section 2 reviewer, a real Store with synthetic rows): about 1.1 ms per call at 10k replies, 14 ms at
  100k and 44 ms at 400k; 100 waiting deferrals at 100k replies take 1.2 s.
- **On the Mac** (sqlite3, 100k replies, 100 `_answered`-shaped queries): 596 ms without an index, 0.4 ms with one. The
  plan then reads `SEARCH message_replies USING INDEX message_replies_by_reply_to (reply_to=?)`.

One test, red today (peer/tests/test_deferrals.py, uncommitted on this branch):
`test_answered_searches_replies_by_an_index` asserts that an index on `message_replies` leads with `reply_to`, and that
SQLite's plan for a search by `reply_to` uses it. It fails with `0 == 1` (the only index is the primary key's).

## The change

One line in `INBOX_SCHEMA` (peer/superyak_peer/inbox.py), right after the `message_replies` table:

```
CREATE INDEX IF NOT EXISTS message_replies_by_reply_to ON message_replies(reply_to);
```

`INBOX_SCHEMA` runs at every start (db.py's `executescript`), so an existing database gets the index at the first
restart, and later starts change nothing. No query changes: SQLite picks the index for `_answered`'s
`message_replies.reply_to=?`.

Because the change is this one line, the spec carries the implementation and there is no separate plan.

## Requirements

1. After two starts, `message_replies` has exactly one index leading with `reply_to`, and a search by `reply_to` uses an
   index (the test, red today).
2. Every existing test stays green: no behaviour changes.

## Rollback and mixed versions

- The index is additive. Main's code ignores it; SQLite keeps it up to date on every insert. A rollback needs nothing.
- No schema of any table changes, no row is written, no key or route changes. Ships need nothing.

## Cost

- Building the index on an existing database takes one pass over `message_replies` at the first restart, under the
  startup transaction (a few hundred ms at 100k rows on the Pi, by the reviewer's scale).
- Each insert into `message_replies` (one per reply with `reply_to`) also updates the index: negligible.
- Disk: one row per reply in the index.

## Deploy

Back up the database, merge, push, restart the lighthouse (the index is built at start). Check the journal and
`grep 'version check'`.

## Known limits

- Other full scans may remain elsewhere; this spec fixes only the one stake 4 measured.
