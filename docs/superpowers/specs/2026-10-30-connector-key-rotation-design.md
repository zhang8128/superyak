# Rotating the connector's key

Revision 2, 2026-11-04, Serenity. Law section 3: a fresh reader approves; Andy can veto. From 9a's review, N2: "Key rotation
has no command. You delete the row and restart, and a running process keeps the old key." Draft 1 (32a52cff, 2026-10-30) was
never reviewed; this revision re-reads the code on main 4be306de and settles two of its three open questions.

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
- **So a leaked key lets someone** mint a client id naming any client, which can put a false name on the consent page. By
  reading, it doesn't let them receive a code or a token.

## After a rotation, with no connection ended

`known_client` takes a stored `oauth_clients` row first, "so a key rotation or a callback change disconnects no one" (spec
revision 4). A client is stored when its person allows, and a refresh checks the client through `known_client`. So:

- every live connection keeps working, refreshes included;
- a registration that never reached consent is unknown, since its tag fails, and its app registers again, silently;
- a sign-in between its first step and its decision fails, and the person signs in again;
- a decided request holding a code not yet exchanged still exchanges: `/token` finds it by the code's hash and checks no tag.

## Why a command

A person who thinks the key left the Pi (a copied backup, a disk) needs one act that replaces it in every process. Deleting
the row and restarting works today only with every process restarted, since each keeps the old key in memory, and nothing
checks that.

## Decisions

1. **`make station-connector-rotate-key`** runs `python -m superyak_peer station-connector-rotate-key --data-dir`. It is a
   trusted local command, as `station-journal` is. A ship runs it only when Andy asks at its terminal.
2. **It refuses while any station unit runs,** with the check `station-journal` uses (`journal_mode.units_active`, which
   fails closed): a running process would keep signing with the old key.
3. **In one transaction** it writes 32 new random bytes over `KEY_NAME` and deletes the undecided rows of `oauth_pending`
   (`decided IS NULL`), whose signatures can't pass any more. A decided row stays, so a sign-in already finished isn't lost.
4. **By default it ends no connection,** as revision 4 intends. Draft 1 leaned the other way, on the thought that a client
   allowed under a false name would survive. It would, under a name someone chose, but its code still went only to the
   configured callback, so its holder has no token by this route. Failing closed here would cost every person a reconnect
   to answer a risk the key doesn't carry.
5. **`--end-connections`** is there for a person who thinks more than the key left. It revokes every live connection through
   `_end_connection`, with `revoked_why = 'key_rotated'`, so each token ends as a fact. Connected apps says: "The home's
   connector key was changed, so this connection ended. Connect again if you still want it." That is a new `APP_ENDED`
   entry.
6. **It prints counts only:** pending sign-ins removed, connections kept or ended, and with the default, one line that says
   what it did not do: "N connections stay. If more than this key may have left, run it again with --end-connections." It
   never prints the key.
7. **Restore needs no change.** `_keep_connector_key_like_replaced` already keeps the replaced file's key when it differs, so
   restoring a copy from before a rotation doesn't bring the old key back. A test holds that against this command.
8. **The runbook line:** stop the station's units (as `station-journal`'s step does), rotate, start them again.

## What it doesn't do

- It doesn't rotate on a schedule. Nothing here says one is needed.
- It doesn't touch `system_author`, peer identity keys or anything else in `system_meta`.
- It doesn't make the key a secret. It stays backed up.

## Open, for the reader

- Decision 4 rests on "by reading, a leaked key yields no code or token". Please try to break that.
- A second run of `--end-connections` after a plain rotation should end connections without needing another rotation to mean
  anything. Rotating twice is harmless, so I'd keep one command and not add a separate one. Is that enough?

## Tests

- Refused while a unit runs (a stub `active`), and nothing is written. `units_active` raising refuses too.
- The key changes, and only that row in `system_meta`.
- A registration never allowed is now unknown; a stored client still refreshes; an undecided sign-in fails at its decision; a
  decided code still exchanges.
- The counts printed match, and the key, old or new, appears in no output or log.
- `--end-connections`: every live connection is revoked with `key_rotated`, its tokens end, and Connected apps says why. An
  already-ended connection keeps its reason.
- A `system_meta` with no key row, or one that isn't 64 hex characters, gets a new key and says so.
- A restore of a copy from before the rotation keeps the rotated key.
- The `APP_ENDED` map names `key_rotated`.
