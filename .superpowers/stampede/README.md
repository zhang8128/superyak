# Preserved Stampede bootstrap implementation notes

These September 12, 2026 notes were retained in the original
`codex/stampede-bootstrap` worktree after its implementation was merged at
`e417885`. They are committed here to preserve the development and review record.
The five original note files are unchanged.

Their commands, line references, test counts, and capacity assumptions describe
that implementation stage. For current behavior and agreed scope, read
[`README.md`](../../README.md),
[`HANDOFF.md`](../../HANDOFF.md), and
[`docs/stampede3-deployment.md`](../../docs/stampede3-deployment.md).
The bounded launcher's limits do not replace the agreed whole-Stampede3 scope.
Actual model hosting and cluster throughput remain unmeasured.

- [Cluster and Intel profiles](cluster-report.md)
- [Memory experiment](experiment-report.md)
- [Launcher and recovery](launcher-report.md)
- [Independent review](review.md)
- [Integration progress snapshot](progress.md)
