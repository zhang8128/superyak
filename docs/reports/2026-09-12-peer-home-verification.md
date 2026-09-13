# Personal peer home verification — September 12, 2026

The first independently installable Superyak participant application is runnable.
It provides authenticated personal homes, persistent private drafts, exact active
releases, explicit audiences, private rooms, uploaded attachments, paired peer
exchange, selected-source interchange, and optional guarded local Gemma assistance.
See [the standalone guide](../../peer/README.md) for installation and commands.
This is a synthetic first application slice, not a clinical deployment or an HPC
capacity result. The richer product design remains a proposal beyond this scope.

## Measured two-host acceptance

The same allowlisted source archive ran on a macOS ARM64 host and a Linux aarch64
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

## Source artifact and installation

The reviewed candidate `superyak-peer-candidate-4.tar.gz` contains 45 regular files:
explicitly allowlisted source, tests, lockfile, static assets, API/protocol/source
schema documentation, standalone README, Apache-2.0 LICENSE/NOTICE, scripts, and
per-file `CHECKSUMS.json`. SHA-256:

```text
0de0a19d830a5dd86d7a60b92b91a187a13c3e30e0aeb5b5a6e523898b42b627
```

Inspection rejected dot-directory entries and found no private host/login/key-path
markers. Packaging regressions inject unlisted environment files, keys, database,
operational notes, and even an unlisted Python module; none enters the archive.
Output reuse and allowlisted source symlinks are refused without overwriting them.

This exact candidate was extracted into a new directory, installed from its own
lock, and used to build both sdist and wheel. Both include all three browser assets;
the wheel includes the license. A separate fresh environment installed that wheel
and served the page, JavaScript and CSS successfully from outside the source and
parent repository. Its temporary server was stopped afterwards.

The wheel SHA-256 is
`e99380db511556e2d2f39094d8b49759ddf858751799d0b83cd61636cb6d4b6e`;
the sdist SHA-256 is
`781cd59871ff5b326c5373a707947b465b5689b9f1f65eef496cae570877b417`.

Only newly authored `peer/` code is Apache-2.0. Dependencies keep their licenses;
imported Engram/Atlas/Lighthouse history is neither bundled nor relicensed. The
parent repository remains private. Preparing this artifact does not publish it
or authorize disclosure of historical operational notes.

## Automated checks

The final integrated `make check` ran once and exited successfully:

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
requests. The final archive's manifest matches the committed allowlisted source.

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
