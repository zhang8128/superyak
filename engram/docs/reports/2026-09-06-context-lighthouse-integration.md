# Dynamic context and Lighthouse receiver integration

The existing Lighthouse receiver implementation is now merged into the isolated
dynamic-context branch at `86785947e400138c691284ead30d6293cc11a391`. The combined
tree passed **2,172 tests**, including installed-wheel packaging, and all seven
checks in a fresh disposable local-socket pilot. Four saved receipts also pass
the unchanged sibling Lighthouse kit's validator.

The merge combines dynamic-context parent `8574e39` with receiver parent
`8016bcf`; Git merged the overlapping `pyproject.toml` module lists cleanly.
There were no manual conflict resolutions or new receiver behavior changes.
The [receiver implementation report](2026-09-06-lighthouse-receiver.md) describes
the earlier scoped review and regression coverage.

## Combined verification

The full suite ran in the merged checkout with the project's virtual environment:

```sh
/Users/kairos/Projects/engram/.venv/bin/python -m pytest -q --tb=short
```

Result: 2,172 passed, three existing warnings, 327.11 seconds. The warnings
concern Pydantic class configuration and the two deliberate fork tests.
The [full log](2026-09-06-context-lighthouse-pilot/full-suite.log) is preserved.

A new `python -m lighthouse_pilot --output
/tmp/engram-context-lighthouse-pilot-20260906` run exercised actual Unix socket
requests with synthetic stores and policies:

| Scenario | Selected | Delivered |
| --- | ---: | ---: |
| Allowed explicit share | 1 | 1 |
| Receiver lacks delivery grants | 1 | 0 |
| Publisher policy withdrawn | 0 | 0 |
| Published share removed | 0 | 0 |

All seven checks passed: allowed delivery, restricted-audience exclusion,
publisher-policy withdrawal, unchanged private source, unchanged publisher
database during requests, receiver denial, and unshare withdrawal.
The [pilot report](2026-09-06-context-lighthouse-pilot/report.json) and four
content-free receipts are saved together. Their committed copies were validated
using sibling Lighthouse kit commit `0a9f615e681f84386d0088fc0f5ddde18ed00966`.
[Validation commands and outputs](2026-09-06-context-lighthouse-pilot/validation.json)
and [checksums](2026-09-06-context-lighthouse-pilot/sha256.json) make that evidence
inspectable. The kit checkout remained clean.

## Current integration boundary

The receiver connects explicitly chosen local publishers to **MCP recall**.
It checks separate receiver and publisher permissions and records a verified
receipt before returning neighbor content. The combined branch does not yet
make Lighthouse an additional source for the standalone dynamic chat runtime.
That next source adapter must carry provenance and recheck delivery permission
at the actual model-dispatch boundary; merging the two branches does not supply
that behavior automatically.

This milestone validates a synthetic local mechanism. The pilot explicitly
records `humanUsefulnessEvaluated: false`. Human continuity/usefulness review,
normal-use configuration, and cross-machine authentication/discovery remain
outside this validation.

Main remains at `eec90fa`. The merge is local to
`/Users/kairos/Projects/engram/.worktrees/dynamic-context`; nothing was pushed.
No live receiver settings, grants, publisher policies, or running MCP/daemon
processes were changed. Adopting the receiver build requires a normal process
restart before its per-request policy reloads can take effect. The
[receiver guide](../lighthouse-receiver.md) documents configuration and the
disposable pilot.
