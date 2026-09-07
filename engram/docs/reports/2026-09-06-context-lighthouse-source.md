# Lighthouse sources in dynamic chat

Implementation `858db840fe7c9a02f39403bed14d08ea3f916fa7` connects explicitly
configured Lighthouse publishers to terminal and browser chat. The runtime
admits attributed shared accounts under its existing context budget, re-reads
selected shares after counting, and records a content-free receipt before
provider dispatch. Configuration is documented in the
[chat guide](../dynamic-context.md#opt-into-lighthouse-sources-for-chat).

## Verification

The final full suite passed **2,195 tests**, with three existing warnings, in
147.86 seconds. The 47 focused checks passed in 1.34 seconds. The full suite
includes installed-wheel packaging. Warnings remain the Pydantic class-config
deprecation and the two deliberate fork tests.

Tests observe the actual request received by a recording provider. They cover
receipt persistence before generation, unchanged counted payloads, context-budget
omission, receiver/settings/publisher withdrawal during counting, changed
content, independent peer failures, receiver withdrawal during another peer's
read, source and tool-page dependencies across model rounds, receipt failures,
thread isolation, source inspection, forgetting, and turn deadlines. A disposable
real Unix-socket daemon additionally checks allowed delivery, restricted-audience
exclusion, and publisher-policy withdrawal after counting.

Standards and requirements were reviewed separately. Review corrections preserve
healthy peers after malformed reads and cap repeated source-page validation by
the turn deadline. A historical handle now receives a receipt naming the current
chat turn. Regression tests demonstrated both the earlier failures and the
corrected behavior. Both final reviews found no remaining blockers against patch
SHA256 `b4518c3aaf4c96adf4c063dc3ae58e933b27000ba86884df92f85495f295793f`.

## One live synthetic call

A fresh synthetic publisher, private source, named receiver, and explicit
policies exercised the real Codex subscription adapter with `gpt-6-astra`.
There was one provider dispatch and no retry. The permitted account was:

> Synthetic bridge maintenance: inspect the upstream support.

That account was present in the dispatched request; the restricted account was
absent. The answer was:

> The upstream support should be inspected.

The turn completed in 15.86 seconds, including retrieval and generation. The
provider reported 10,332 input and 42 output tokens. The local manifest's input
estimate was 2,193; it does not cover hidden Codex context or certify each
internal model call. The adapter remains explicitly `strict: false` and operates
between episodes. This single synthetic result does not establish human
usefulness or continuity quality.

Preparation and dispatch receipts both passed the unchanged sibling Lighthouse
kit at `0a9f615e681f84386d0088fc0f5ddde18ed00966`. The dispatch receipt names the
current turn and exact supplied-payload digest. The private source and publisher
database bytes stayed unchanged. The synthetic daemon stopped after the call.

## Retention and operating boundary

The feature requires `--instance`, `--lighthouse-context`, and
`--lighthouse-purpose`, plus the receiver's opt-in settings and both sides'
existing grants. Context/purpose apply to the whole chat process; the bounded
query includes current text and the latest two dialogue excerpts. Coding mode
rejects these flags. No live settings, grants, MCP processes, or publisher
daemons were changed by this implementation.

Source bodies are held in each turn's session. The archive keeps receipt metadata
and source references; raw Lighthouse tool pages are not persisted or indexed.
Fresh inspection requires a recent handle in the same thread and current
permissions. Ordinary provider output and visible answers are still archived
and may quote or derive from shared content. Withdrawal cannot erase previously
received answers or an earlier API preflight disclosure. Receipt phases describe
boundary delivery, not proof of successful generation or model use.

Main remains at `eec90fa`; the implementation is committed locally on
`feat/dynamic-context`. Existing running services have not adopted the new flags.
Human usefulness and continuity acceptance remain open.

## Evidence

- [Live result and manifest](2026-09-06-context-lighthouse-source-data/report.json),
  [exact supplied request](2026-09-06-context-lighthouse-source-data/supplied-request.json),
  and [provider response](2026-09-06-context-lighthouse-source-data/provider-response.json).
- [Final full-suite log](2026-09-06-context-lighthouse-source-data/full-suite-final.log),
  [implementation and review provenance](2026-09-06-context-lighthouse-source-data/provenance.json),
  and [receipt validation output](2026-09-06-context-lighthouse-source-data/receipt-validation.json).
- [Reproduction script](2026-09-06-context-lighthouse-source-data/reproduce.py):
  run from this checkout with `PYTHONPATH=.` and a fresh output-directory
  argument. It makes one real subscription-backed call and stops on failure.
- [Complete synthetic run archive](2026-09-06-context-lighthouse-source-evidence.tar.gz),
  including stores, policies, raw response artifact, receipts, and per-file hashes.
- [Artifact checksums](2026-09-06-context-lighthouse-source-sha256.json).
