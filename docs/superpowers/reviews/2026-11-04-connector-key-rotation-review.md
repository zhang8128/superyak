# Fresh review of the connector key rotation spec

Law section 3. A fresh reviewer agent started on the Mac, with no part in the writing. Both verdicts are saved whole.

## Revision 2 (41867e1a): APPROVE WITH CHANGES

What I ran: three scripts in a scratch directory, each against a throwaway data dir, never touching `~/.superyak` or the live
station: probe_malformed_key.py, probe_short_hex_key.py, probe_leaked_key.py. Everything else (connector.py,
connector_routes.py, connector_apps.py, journal_mode.py, backups.py, static/app.js, static/consent.js, __main__.py, db.py, the
remote-connector design spec) was read, not executed.

Must-fix

1. connector.py:166-172, `_ensure_connector_key`. Every `Store(data_dir)` construction calls this unconditionally (db.py:137),
doing `bytes.fromhex(...)` on whatever is in `system_meta.connector_client_key` with no validation. Ran probe_malformed_key.py:
once that row holds a non-hex string, the next `Store(...)` call raises `ValueError` and never returns: the whole station, and
every trusted-local command including the rotate command itself, fails to start. Ran probe_short_hex_key.py: a valid-hex but
short value ("deadbeef") is accepted silently as a 4-byte HMAC key, with no error and no new key minted. Both contradict the
spec's own test 6 ("A system_meta with no key row, or one that isn't 64 hex characters, gets a new key and says so"): that is
exactly a disaster-recovery case, and the natural implementation, `Store(data_dir).transaction()`, which decision 5 needs anyway
to reach `_end_connection`, can never reach the command's own recovery logic, because the crash happens inside `Store.__init__`
before any command code runs. Decisions 3 and 5 must say explicitly that the key is read and rewritten through a raw connection
under the dispatch gate, as `switch_journal` (journal_mode.py:69-99) already does, since it never constructs a Store, and that
any `Store()` needed for `--end-connections` is built only after that raw fix, never before. backups.py:1151 already guards
against exactly this malformed value with `re.fullmatch(r'[0-9a-fA-F]{64}', ...)`; `_ensure_connector_key` has no equivalent
guard.

Should-fix

2. "Why a command" overclaims scope. Decision 2 reuses `journal_mode.units_active` (journal_mode.py:13-18), a fixed list of 11
named systemd units. It cannot see a Store opened outside those units: Makefile:340 launches admission jobs via `systemd-run
--user --unit=superyak-imprint-admit-<id> ... RuntimeMaxSec=3600`, a transient, dynamically-named unit that
`station-imprint-admit-begin` (__main__.py:799) opens as a real Store for up to an hour, invisible to `units_active`'s fixed
list. That job doesn't touch the connector, so it is not itself a hole, but it shows the check tests "is this named systemd unit
active," not "does anything hold this database open", so a `serve --public-origin` started by hand outside systemd (testing, a
stuck deploy) goes undetected too, which is the exact N2 scenario the command exists to close. Since this is inherited from
`station-journal` rather than new here, should-fix not must-fix: state the real, narrower guarantee, and name the residual risk
in "What it doesn't do."

3. "After a rotation"'s reasoning for decision 3, "deletes the undecided rows ... whose signatures can't pass any more",
overstates the mechanism for rows already past sign-in (person_id set, decided still NULL): `pending_decide`
(connector.py:338-346) never re-checks a signature, only `WHERE id=?`. Deleting still correctly forces a restart, just not
because of a signature check. Reword, or accept as a harmless simplification.

Notes

4. Decision 4 held up under the attack I tried (probe_leaked_key.py): a forged client_id is accepted by `check_client` with any
name, but `exchange_code` refuses a guessed code (400 invalid_grant); PKCE, the one fixed callback (`check_callback`,
connector.py:116-123), and the random CSRF/pending tokens close every path from a forged id to a code or token that I traced.
Worth noting: the "false name" the key is blamed for is free to anyone already via the unauthenticated `/register`
(connector_routes.py:148-165, no auth, no rate limit visible): probe step 3 registers the identical false name with no key at
all. The key's real marginal power is minting an id without ever calling `/register` (no log trail, a chosen `issued_at`),
narrower than decision 4's framing, which makes "doesn't let them receive a code or a token" even more solidly true.
consent.js:144-146 already labels the client-asserted name as self-asserted ("It calls itself..."), a mitigation the spec doesn't
mention but that shrinks this risk further.

5. Item 3 (deleting only `decided IS NULL` rows): checked sign-in lockouts (login_attempts/login_devices, an unrelated table), the
sweep (`_connector_sweep`, idempotent on early deletion), and `oauth_clients` cleanup (only accelerates an already-due cleanup by
one sweep cycle). Found no dependency this breaks.

6. Restore (decision 7): read `_keep_connector_key_like_replaced` (backups.py:1141) and its unconditional call from
`_keep_connections_like_replaced` (backups.py:1180), and `_clear_connector_sign_ins` (backups.py:1230), both run whenever a
replaced file is usable. Confirmed by reading (not by running `reconcile()` end-to-end, which needs a full station schema I didn't
build) that a backup predating a rotation keeps the replaced file's newer key. No change needed.

7. Open questions: (a) I could not break decision 4; see note 4. (b) Yes, one command is enough: `_end_connection`'s `WHERE
revoked IS NULL` guard (connector_apps.py:131) makes a second `--end-connections` run idempotent, and running a plain rotation
twice is just two independent atomic overwrites; no separate command is warranted.

Not checked: the actual implementation (none exists yet; this is a pure design), the runbook's exact wording, and any
end-to-end HTTP/browser-level OAuth/MCP flow.

## Revision 3 (a7753896): APPROVE

Ran: probe_raw_fix_then_store.py (scratch data dir): corrupts the key row, then fixes it via a raw sqlite3 connection under
DispatchGate (mirroring switch_journal: BEGIN IMMEDIATE, overwrite KEY_NAME, delete oauth_pending WHERE decided IS NULL, commit,
close), then constructs Store(data_dir) afterward, then repeats the raw-connection step once more. Only read: the diff,
backups.py's _keep_connector_key_like_replaced / _revoke_every_connection / restore_test, and tests/test_restore.py's existing
test_a_replaced_key_that_isnt_one_makes_a_new_key.

1. M1: achievable, confirmed by the probe. DispatchGate is a per-resolved-path, reentrant-within-a-thread flock; the raw fix fully
releases it before Store(data_dir) opens its own, so there's no deadlock, and Store reads back the freshly committed valid key
with no crash.

2. Decision 7 is the right call. Traced both reconcile() branches: with a usable --replaced, _keep_connector_key_like_replaced
never lets a malformed value survive into the copy (every path ends with either the valid replaced-file key or a freshly minted
one); without one, _revoke_every_connection unconditionally mints a fresh valid key. Both run before any Store() touches that copy
(station-restore-test's Store(scratch) at backups.py:1976, and go-live after a real restore), confirmed by the already-passing
test_a_replaced_key_that_isnt_one_makes_a_new_key. So raising in _ensure_connector_key breaks neither restore path. The two should
differ: restore already fails closed silently with no operator in the loop (the whole file's convention); a live station finding
a malformed row is itself the anomaly and deserves a person's attention rather than silent self-healing.

3. The S2/S3/leaked-key rewording is faithful, no more, no less. "What the key is" matches my probe and conclusion exactly. The
"What it doesn't do" bullet keeps the units_active gap at should-fix weight (inherited from station-journal, not new) and adds a
runbook mitigation I hadn't proposed, which answers rather than inflates the finding. "After a rotation" now correctly splits
"before sign-in: signature fails" from "after sign-in, pre-decision: row gone, pending_decide checks no signature," fixing the
overstatement I flagged.

4. Nothing newly wrong. One nit, not blocking: decision 7's "anything else raises" could be misread as covering "no row at all"
too; the Tests section correctly keeps that case auto-creating silently, but decision 7's own prose doesn't say so explicitly;
worth one clause.

Not checked: the actual error message text the raise would carry, and whether any other, non-restore test constructs a Store on a
bad key row (grepped the test tree; found none).
