# Personal peer home verification — September 12, 2026

The first independently installable Superyak participant application is runnable.
It provides authenticated personal homes, persistent private drafts, exact active
releases, explicit audiences, private rooms, uploaded attachments, paired peer
exchange, selected-source interchange, and optional guarded local Gemma assistance.
See [the standalone guide](../../peer/README.md) for installation and commands.
This is a synthetic first application slice, not a clinical deployment or an HPC
capacity result. The richer product design remains a proposal beyond this scope.

## Current source artifact (candidate 9)

Current standalone archive: `superyak-peer-candidate-9.tar.gz`, SHA-256
`6f693dbe751f98a19d1a81b3be1cc678fb9ad90cd6cd72b98a02a8f4ec466c4a`.
Its 45-file manifest matches the current source; the archive has 46 regular entries.
Only `static/app.js` and `tests/test_browser.py` differ from candidate 8 below.
The final presentation uses plain operation labels and keeps IDs/peer metadata in
optional Connection details and file hashes in optional File details. All Python
backend and checker bytes remain identical to the exact measured candidate 8.
No additional Pi or model run was made for this presentation adjustment.

All **27 Chromium tests passed in 31.67 seconds** on the revised browser code.
A new exact-archive inspection rebuilt the sdist and both wheel paths with synthetic
private-state injection, confirmed exclusions and manifest/source equality, and
started the newly installed wheel outside the checkout. HTML/JS/CSS all served;
its temporary server stopped. Wheel SHA-256:
`514c6226eebdb5f92ed3ce6dc64e11df9356a2cd43da613af3d5bd8d6ccb7f95`.
Sdist SHA-256:
`6e09d90663514b44b27b0bccf66d75a51634c8e94cc3b616e7df6c2ca4d8be44`.
The inherited warning remains. Original archives, measurements and screenshots
are preserved; this is new browser/package evidence for candidate 9, with the
unchanged backend's two-host evidence attributed precisely below.

## Final-review fixes and exact candidate 8 acceptance

Candidate 8, `superyak-peer-candidate-8.tar.gz`, is the reviewed-fix source
artifact at the two-host measurement. SHA-256:
`06b472a5907d2cf63ee1482b594971b973f5ac6ad8b753558f68bbd112a87cea`.
It contains 46 regular entries, including the complete 45-file checksum manifest.
Every source byte in that manifest matched the final checkout at inspection.

The final fixes let an invited ordinary account create any supported space kind
with explicit local participants. Saved-version preview now shows selected file
metadata/inspection links and authoritative named space members; space changes
while preview is open cause an activation conflict. Current care-circle/project
release details use frozen members. Delivery status collects local queued events
without network I/O, identifies item/recipient/effective operation, and distinguishes
local withdrawal from waiting, failed, acknowledged, or canceled remote delivery.
Explicit delivery checks refresh content while retaining unsaved layer/chat text.
Native dialogs manage keyboard focus, mobile counts are compact, screenshots use
unique run directories, and public network errors report unavailability.

The covering browser/layer/federation/chat/transport run passed **74 tests**, including
**27 Chromium workflows**, in 38.24 seconds. Three real packaging tests passed in
3.31 seconds. A subsequent viewport-only preview capture passed all three ordinary
space-creation cases in 4.22 seconds. The inherited Starlette/AnyIO warning remains.
Engram and the other unchanged subsystems retain their earlier results below.

The exact candidate 8 archive was independently extracted and rebuilt after
synthetic private state was injected. Standard sdist and both wheel build paths
excluded it and retained the static assets/license. The newly installed wheel
served HTML, JavaScript and CSS from outside the parent/source checkout; its
owned temporary server stopped. Wheel SHA-256:
`8c1b33974988cc1df613be9e19bb8e7d994338eb9a49abe779e19b3766fe4055`.
Sdist SHA-256:
`eea6816f4298d22cb737c96832d68185f0ecb52724de177a434d7e99572c82e8`.

The controller then ran the exact candidate 8 on macOS ARM64 and the Linux aarch64
Pi. All ten two-host checks listed below passed in **7.311 seconds**, with both
local and remote cleanup confirmed stopped. This was a fresh synthetic run with
independent identities/stores and pinned signed HTTPS over loopback tunnels.
The controlled lost-acknowledgement retry retained event
`0f41fd4571d044609fc36c7b877afe03` and envelope SHA-256
`e15580adb7893e8209b7b63f4e05c810f9e01d7764b9225ed802195ab68705d7`;
the receiver kept one message. Nine remote receipts and one local receipt remain
in private evidence. Final status identified the actual delivered layer/room
withdrawal operations with item and destination. No model generation was repeated.

Candidate 8 changes `app.py`, `layers.py`, `federation.py`, `static/app.js` and
`static/app.css` from the original measured candidate 4. The other runtime files
and the two-host checker are unchanged. Candidate 8 therefore has its own exact
acceptance result; the following candidate 4 and candidate 7 records remain
historical evidence, not byte-equality claims for the revised runtime.

## Historical candidate 4 two-host acceptance

Candidate 4 (SHA-256
`0de0a19d830a5dd86d7a60b92b91a187a13c3e30e0aeb5b5a6e523898b42b627`)
ran on a macOS ARM64 host and a Linux aarch64
Raspberry Pi, with independent SQLite stores, accounts, Ed25519 identities and TLS
certificates. The remote runtime was Python 3.11.2. Both application servers bound
only to loopback. Two SSH forwards supplied routing; pinned application HTTPS and
signed envelopes remained independently enforced. SSH did not substitute for peer
pairing or application authentication.

The generic [two-host checker](../../peer/scripts/two_peer_check.py) passed all ten
recorded checks in 6.748 seconds, including setup and cleanup:

| Check | Observed result |
| --- | --- |
| Distinct origins | Different key-derived peer IDs and separate state |
| Private draft | Absent from the other host before activation |
| Selected share | Exactly the selected active body reached the paired participant |
| Bidirectional room | Both hosts sent private messages; reply appeared once on each |
| Private replacement/name correction | New draft stayed private; account ID and grants stayed unchanged |
| Corrected release | Remote active body changed only after explicit activation |
| Invalid peers | Unpaired sender, tampered signature and incorrect TLS identity were denied |
| Offline/restart/retry | Editing continued offline; both peers restarted with retained identity/state; queued event ID survived; signed retry retained byte-identical envelope and one recipient message |
| Withdrawal | Other host returned 404 and removed the active shared list item |
| Member removal | Removed remote member could neither read nor send in the hosted room |

The offline connection failed before signing, as designed. A separate controlled
fault discarded an acknowledgement *after a real pinned HTTPS delivery*; the
sender recorded failure. Both peers restarted, then retried the same signed bytes.
The recipient retained one message and returned duplicate acceptance. This is
explicit fault injection, not a claim of a naturally occurring network failure.
The final evidence contains nine remote receipts and one local receipt, with event
IDs and content digests. Temporary server processes and the SSH tunnel were
confirmed stopped. Existing research, model and network services were preserved.

The successful signed retry event was `97ff8475f3bb4ebf848ebd0cada20bde`, with envelope
SHA-256 `b80fa63c9d55c18d0e004be1c7e33762e0534936d200f525ab2c1902892f6544`.
Operational hostnames, SSH access details, full commands and synthetic state are
retained in private verification evidence rather than the standalone source.

## Historical candidate 7 packaging artifact

The packaging-only release candidate `superyak-peer-candidate-7.tar.gz` contains 46 regular
files: explicitly allowlisted source, tests, lockfile, static assets,
API/protocol/source-schema documentation, standalone README, Apache-2.0
LICENSE/NOTICE, scripts, a build hook, and per-file `CHECKSUMS.json`. SHA-256:

```text
734cf0f80ac00d6bdbb6363dd24fce65caf6d91eb4ee2adbae79b2611076b677
```

The original candidate 4 archive was safe, but review found that a later ordinary
`uv build` could include private demo state in an sdist and unlisted source in a
wheel. The packaging fix shares one explicit sdist inventory between Hatch and the
custom bundler, adds an explicit wheel inventory, and removes Hatch's implicit
source additions (including parent ignore files) through a small build hook.
Output reuse and allowlisted source symlinks remain refused by the custom bundler.

A real-build regression now creates synthetic demo credentials and injects `.env`,
`.gitignore`, private keys/database/identity files, and unlisted package source
before `uv build` and direct `uv build --wheel`. Both build paths exclude those
files and retain all browser assets and LICENSE/NOTICE.

This exact revised candidate was freshly extracted, installed from its own lock,
and subjected to the same private-state injection and sdist/direct-wheel inspection.
A separate fresh environment installed its wheel and served the page, JavaScript
and CSS from outside the source and parent repository. Its temporary server was
stopped. The wheel SHA-256 is
`7f9c01754d67dee7e02fa7d0fb4299aed451eb34146332f6af473fb7ae837c98`;
the sdist SHA-256 is
`bbc6bb313b449beb462660303afbf0902ac435d34e98c7c63963bd452dc8e221`.

Every application/runtime/static file and `scripts/two_peer_check.py` is byte-for-byte
identical between candidates 4 and 7. The revised artifact changes only packaging
metadata/build code, packaging tests and README. Candidate 4 retains the exact
measured two-host evidence above; candidate 7 carries that unchanged runtime/checker
evidence plus new package verification. No two-host or model run was repeated for
this packaging-only fix. Earlier source artifacts and evidence remain preserved.

Only newly authored `peer/` code is Apache-2.0. Dependencies keep their licenses;
imported Engram/Atlas/Lighthouse history is neither bundled nor relicensed. The
parent repository remains private. Preparing this artifact does not publish it
or authorize disclosure of historical operational notes.

## Automated checks

Before the packaging review fix, the integrated `make check` ran once and exited
successfully:

| Suite | Result |
| --- | --- |
| Engram | 2,495 passed; two expected opt-in live-host checks skipped |
| Lighthouse | Build/lint/typecheck, 139 tests, protocol and recall proofs passed |
| Atlas | 694 passed |
| Interoperability | Two matching schemas, seven socket checks, four validated receipts; three interop tests; Atlas 28 artifacts, 20 policy and two canonical checks |
| Portable research | 83 passed |
| Peer | 129 passed, including 21 Chromium workflows and two real-package tests |

The peer suite completed in 40.67 seconds. Existing deprecation warnings remain;
there were no failing checks. JavaScript syntax, lock consistency and whitespace
checks also passed. Tests used isolated fixtures and made no live model generation
requests. The packaging-only review fix subsequently passed all three focused packaging
tests in 3.02 seconds, with the same inherited warning. The broad suite was not
repeated for unchanged application code. The revised archive's manifest matches
its committed allowlisted source.

## Demo and model boundary

`make home-demo` seeds private fictional credentials and serves the local home.
The retained isolated demo passed actual Chromium login and page readiness. No
password is printed in this report; credentials stay in its private state file.
The default loopback URL is `http://127.0.0.1:7435`.

The demo opts into the exact previously validated `gemma4:31b` configuration.
Its read-only model status check succeeded; Task 5 made no generation request.
The preserved Task 4 measurement remains one authenticated fictional generation:
HTTP 200 in 22.562 seconds, unchanged saved draft, no active release. Assistance
is disabled in ordinary standalone installations until explicitly configured.
The component guard does not migrate the stopped MG research worker, change
legacy launch defaults, enforce other runtimes or establish cluster throughput.

## Limits

Hosting operators can read their local plaintext stores. Peer cryptography protects
transport and authenticates hosts; it is not browser-to-browser E2EE. Revocation
cannot erase recipient copies already saved elsewhere. No actual medical-record
provider, clinical suitability, universal model enforcement, key recovery/password
reset workflow, production operations or full-cluster throughput is validated.
Automatic discovery and a central account authority are deliberately absent.
Final independent review, repository integration, push and remote CI are owned by
the controller after this task's verified implementation commit.
