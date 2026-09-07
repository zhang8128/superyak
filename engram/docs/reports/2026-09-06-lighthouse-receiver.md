# Lighthouse receiver validation — September 6, 2026

The `feat/lighthouse-receiver` branch adds the local receiver crossing to Engram
base `eec90fa`. It is opt-in: an existing named receiver must choose publishers,
provide its own policy, and declare the recall context. The implementation keeps
neighbor content separate from local recall and saves a verified receipt before
returning it. See the [run guide](../lighthouse-receiver.md).

## Evidence

- Clean baseline: 1,762 tests passed.
- Final full suite: **1,953 passed**, three existing warnings, 160.28 seconds.
- Installed-wheel packaging: six tests passed, including all runtime modules.
- Independent review: receiver permission sequencing, content budget, receipt
  integrity, local failure isolation, publisher withdrawal, pilot isolation and
  explicit labels reviewed. Final focused review run: 84 tests passed; no
  remaining substantive findings.
- The unchanged sibling Lighthouse kit (`0a9f615`) validated four generated
  receipts and both policies. The explicit synthetic labels document also passed
  its existing parser.

The full suite command was:

```sh
/Users/kairos/Projects/engram/.venv/bin/python -m pytest -q --tb=short
```

The final disposable run lives at
`/tmp/engram-lighthouse-receiver-final-20260906/report.json`. Its results:

| Scenario | Selected | Delivered |
| --- | ---: | ---: |
| Allowed explicit personal-lane share | 1 | 1 |
| Receiver lacks content-delivery grants | 1 | 0 |
| Publisher policy withdrawn | 0 | 0 |
| Published share removed | 0 | 0 |

The restricted audience was absent throughout. Publisher database bytes stayed
unchanged during requests, and the private source stayed unchanged throughout.
The pilot starts its own temporary Unix socket daemon and refuses an existing
output directory.

## Corrections established by regression tests

Publisher policy is reloaded once per operation for both actions and audiences.
Complete schema validation rejects malformed selectors and mismatched issuers;
the publisher's clock prevents backdated requests from reviving expired grants.
An invalid policy never preserves the previous allow.

Receiver delivery rechecks permissions after all reads and applies the content
budget in fused rank order, after removing revoked peers. Source receipts hash
the actual bounded trace snapshot. Unavailable sources carry no invented digest.
Weights use the protocol's existing artifact extension, preserving strict policy
and receipt schema compatibility.

The initial full-suite run found a packaging failure because its source-copy
helper uses `git ls-files` and the parent receiver files were still untracked.
After staging those files, packaging and the complete suite passed. This did not
require weakening the packaging test.

## Limits and rollout state

This validates a synthetic local mechanism. The human usefulness study remains
unfinished; the report explicitly records `humanUsefulnessEvaluated: false`.
Cross-machine authentication, discovery, identity lifecycle, and real independent
adapters remain outside this milestone. A digest establishes integrity, not
authenticated identity or truth.

The build is committed locally on its isolated branch. Main remains at `eec90fa`.
Validation used disposable stores. No live receiver settings, publisher policies,
group memberships, or running MCP/daemon processes were changed. A normal process restart
is required when adopting this code; subsequent policy changes apply per request.
