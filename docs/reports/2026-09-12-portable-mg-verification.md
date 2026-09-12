# Portable MG task verification — September 12, 2026

The bounded preparation slice adds a portable question/source task, native Ollama
and chat-completions adapters, durable extraction/review checkpoints, and isolated
Atlas capture. It also fixes the observed paper/model HTTP coupling. See
[usage and limits](../portable-research-tasks.md).

## Tests and independent review

- Engram: 2,495 tests passed, two expected live-configuration skips and three
  existing warnings in the corrected full run.
- Atlas: 694 tests passed after the transport, native raw-response and proxy fixes.
- Portable task/provider/CLI: 83 tests passed in their own Python process.
- Independent review: 159 combined transport/model/task tests and 33 existing
  Stampede provider compatibility tests passed; no remaining material findings.
- Atlas/TypeScript interoperability: 28 artifacts, 20 policy checks and two
  canonical checks passed.
- Source packaging: the real allowlisted archive was extracted. All 116 code
  fingerprint paths were present. Native Qwen's completed task replayed from
  the extracted source using Python `-S`, with networking blocked and no site
  packages/editable installation.

The full Engram run initially found stale POC mocks targeting `_json_response`
instead of the new native byte boundary. That run was interrupted at 141 passes
and three failures after unintended local fixture-model requests. Test fixtures
now target the byte boundary and block unexpected HTTP connections; the focused
bridge/monorepo check passed all 20 tests. The original failed log is retained.
No POC implementation or historical run was rewritten.

Independent review also found and resolved native malformed-reply audit loss,
environment-proxy routing of loopback requests, loss of publication-type metadata,
abstract search-query/error-text export, and reviewed-question projection without
reviewer metadata. Regression tests cover these cases.

## Real fixed-evidence calls

One already-recorded live MG literature job was explicitly selected, read without
changing its journal, and exported as a new fixed-input task. The packet contains
the current therapeutic-evidence question and the cached paper headed
“Comparing Efficacy and Safety of Various Monoclonal Antibodies in Myasthenia
Gravis: A Systematic Review and Network Meta-Analysis of Randomized Controlled
Trials.” No patient or participant record was involved.

- Task hash: `dce5e7ced51f0ef930a647569814ebdfe74cc16784a5de6f382b543978aa2bfd`.
- Model: `qwen3.8:27b-mlx`; the local tags endpoint reported NVFP4 and digest
  `5642e97495e1a088883805981563dcdc4a040c2f53388b7a41d1f24d3622cf7e`.
  This is a server observation, not independent weight verification.
- Native Ollama: extraction completed in 46.27 seconds; the fresh source-support
  check completed in 67.36 seconds. The automated check supported the candidate.
  One proposed claim was saved in the isolated run, with current publications.
- Chat completions, `research` protocol: the extraction timed out at 120.01
  seconds. No completed response, review or finding was recorded. The request and
  error remain saved; no automatic retry occurred. A client timeout does not prove
  that server work stopped or that the request was never processed.

These calls used the same packet but different provider request formats. The model
server was shared with the continuing MG worker and, during the native run, stale
POC fixture requests. Timings therefore include unmeasured contention and are not
a serving-speed comparison. The timeout alone does not identify its cause. This
is not a demonstration of K3/GLM hosting or Stampede throughput.

Completed native replay and extracted-archive replay each made zero network calls
and preserved all 31 run-file hashes. The failed completions run replayed its
saved failure with zero network calls and all ten files unchanged. Controlled
crash tests separately show that lost Atlas receipts recover the same journal
entry without repeating completed extraction/review calls. Unknown requests with
no saved reply are refused on resume.

The native record is
`draft-f0848f3587fce1ede7b8f319459e96b9a32975fa08a0dc94c1bdc6606f82b071`.
Its status remains proposed. The same-model source check is not independent
scientific validation; the result is a workflow measurement, not a clinical
recommendation.

## Local artifacts

The preserved worktree is `.worktrees/mg-portable/`. Its ignored
`.engram/mg-portable/` directory contains:

- `task.json`, `server-model-observation.json`, and `real-comparison.json`;
- `qwen-ollama/` and `qwen-completions/`, including exact requests and all available
  response/error evidence;
- `replay-*.json`, `prepared-source.tar.gz`, `extracted-source/` and test logs.

Real source excerpts remain local and are excluded from the executable archive.
No cluster job, model download, external message or push was performed. The
current synthetic cluster launcher remains distinct from the portable task CLI.
The next measured slice is individual/shared researcher memory and corrections;
whole-Stampede3 placement and the agreed four K3/four GLM leads remain the plan.
