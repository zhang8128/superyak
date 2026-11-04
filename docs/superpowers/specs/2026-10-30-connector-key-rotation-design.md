# Rotating the connector's key

Revision 3, 2026-11-04, Serenity, approved: a fresh reviewer's APPROVE WITH CHANGES on revision 2, then APPROVE on this one. Law section 3: a fresh
reader approves; Andy can veto. From 9a's review, N2: "Key rotation has no command. You delete the row and restart, and a
running process keeps the old key." Draft 1 (32a52cff, 2026-10-30) was never reviewed. Verdicts:
`docs/superpowers/reviews/2026-11-04-connector-key-rotation-review.md`.

## What the key is, and what it guards

- **The key:** 32 random bytes as hex in `system_meta` (`KEY_NAME`, `connector_client_key`), made at a Store's first start
  and held in each process's memory from then on (`_connector_key`). It is backed up: "it protects what an id says, not a
  secret" (connector.py, at `KEY_NAME`). So a copied backup or disk holds it.
- **What it signs:**
  - a client id's payload (client name, grant types, issued-at), bound to the one callback (`register_client`);
  - a pending `/authorize` request, between the sign-in and the decision (`pending_request`).
- **What it doesn't guard:** where a code goes. Registration takes exactly the configured callback, and `/authorize` compares
  the redirect to it character for character, so a code only ever goes to that callback. Access and refresh tokens are
  random and stored hashed, not signed.
- **So what a leaked key adds is narrow.** It lets someone mint a client id without calling `/register`, so with no log trail
  and a chosen issue time. It doesn't add a false name: `/register` takes any name from anyone already, and the consent page
  labels that name as the client's own claim ("It calls itself..."). It doesn't let anyone receive a code or a token: a
  reviewer's probe with a leaked key forged an id that `check_client` accepted, and `exchange_code` still refused a guessed
  code, with PKCE, the one fixed callback and the random pending and CSRF tokens closing every path traced.

## After a rotation, with no connection ended

`known_client` takes a stored `oauth_clients` row first, "so a key rotation or a callback change disconnects no one" (spec
revision 4). A client is stored when its person allows, and a refresh checks the client through `known_client`. So:

- every live connection keeps working, refreshes included;
- a registration that never reached consent is unknown, since its tag fails, and its app registers again, silently;
- a sign-in not yet decided has to start again: before its sign-in its signature fails, and after it its row is gone
  (decision 3), since `pending_decide` finds a row by id and checks no signature;
- a decided request holding a code not yet exchanged still exchanges: `/token` finds it by the code's hash and checks no tag.

## Why a command

A person who thinks the key left the Pi (a copied backup, a disk) needs one act that replaces it in every process. Deleting
the row and restarting works today only with every process restarted, since each keeps the old key in memory, and nothing
checks that. The command closes that for the station's units. It can't see a process started by hand (see "What it doesn't
do").

## Decisions

1. **`make station-connector-rotate-key`** runs `python -m superyak_peer station-connector-rotate-key --data-dir`. It is a
   trusted local command, as `station-journal` is. A ship runs it only when Andy asks at its terminal.
2. **It refuses while any station unit runs,** with the check `station-journal` uses (`journal_mode.units_active`, which
   fails closed): a running unit would keep signing with the old key. That list names units, so this is a check on those
   units and not on the database file.
3. **It works through a raw connection, never a `Store`,** as `switch_journal` does (section 2 review, M1). `Store(...)` runs
   `_ensure_connector_key` on every construction, so a command built on one can't reach its own recovery when the key row is
   bad. In one transaction on that connection it writes 32 new random bytes over `KEY_NAME` and deletes the undecided rows
   of `oauth_pending` (`decided IS NULL`). A decided row stays, so a sign-in already finished isn't lost. The delete is what
   ends a sign-in in progress: past its sign-in, `pending_decide` checks no signature. Any `Store` that `--end-connections`
   needs is built only after this has committed.
4. **By default it ends no connection,** as revision 4 intends. Draft 1 leaned the other way, on the thought that a client
   allowed under a false name would survive. It would, under a name someone chose, but its code still went only to the
   configured callback, so its holder has no token by this route. Failing closed here would cost every person a reconnect
   to answer a risk the key doesn't carry.
5. **`--end-connections`** is there for a person who thinks more than the key left. After decision 3 has committed, it
   revokes every live connection through
   `_end_connection`, with `revoked_why = 'key_rotated'`, so each token ends as a fact. Connected apps says: "The home's
   connector key was changed, so this connection ended. Connect again if you still want it." That is a new `APP_ENDED`
   entry.
6. **It prints counts only:** pending sign-ins removed, connections kept or ended, and with the default, one line that says
   what it did not do: "Connections kept: N. If more than this key may have left, run it again with --end-connections." It
   never prints the key.
7. **A bad key row stops being silent.** `_ensure_connector_key` runs `bytes.fromhex` on whatever is in the row, with no
   check. On main, a row that isn't hex stops every `Store(...)`, so the whole station won't start, with a bare `ValueError`.
   A short hex value such as `deadbeef` is taken as a 4-byte key, silently. It now takes only 64 hex characters, the test
   `backups.py` already applies. No row at all still makes a new key silently, as at a first start. Any other value raises
   an error naming this command, and the station stays down until someone runs it. It doesn't mint a new key by itself: a
   bad row means something unexpected wrote to the store, and a person should see that. A restore differs on purpose: it
   has no person in the loop, and both of its paths leave a valid key before any `Store` opens that copy (re-check, 2).
8. **Restore needs no change.** `_keep_connector_key_like_replaced` already keeps the replaced file's key when it differs, so
   restoring a copy from before a rotation doesn't bring the old key back. A test holds that against this command.
9. **The runbook line:** stop the station's units (as `station-journal`'s step does), rotate, start them again.

## What it doesn't do

- It doesn't rotate on a schedule. Nothing here says one is needed.
- It doesn't touch `system_author`, peer identity keys or anything else in `system_meta`.
- It doesn't make the key a secret. It stays backed up.
- It doesn't prove no process holds the old key. `units_active` is a fixed list of named units, so it can't see a `serve`
  started by hand, as in a test or a stuck deploy, which would keep signing with the old key until it stops. The imprint
  jobs' transient units are invisible to it too, though they don't touch the connector. The runbook says to check for a
  hand-started server. This is the same limit `station-journal` has.

## Settled by the reviewer

- Decision 4's claim held under a probe with a leaked key. See "What the key is".
- One command is enough. `_end_connection`'s `WHERE revoked IS NULL` makes a second `--end-connections` harmless, and two
  plain rotations are two independent overwrites.

## Tests

- Refused while a unit runs (a stub `active`), and nothing is written. `units_active` raising refuses too.
- The key changes, and only that row in `system_meta`.
- A registration never allowed is now unknown; a stored client still refreshes; an undecided sign-in fails at its decision; a
  decided code still exchanges.
- The counts printed match, and the key, old or new, appears in no output or log.
- `--end-connections`: every live connection is revoked with `key_rotated`, its tokens end, and Connected apps says why. An
  already-ended connection keeps its reason.
- A row that isn't hex, a short hex row, and no row at all: the command works on each, gets a new key and says so, and it
  builds no `Store` before that commits. A test holds that through `--end-connections` too.
- `Store(...)` on a row that isn't 64 hex characters raises an error naming the command, for both a non-hex and a short value.
- A restore of a copy from before the rotation keeps the rotated key.
- The `APP_ENDED` map names `key_rotated`.
