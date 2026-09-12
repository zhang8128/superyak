# Source-support review

The local researcher now checks each proposed claim in a second, fresh model
call before capturing it. The reviewer receives the current question, the
candidate and retrieved source passages. It receives no earlier graph claims.
The candidate's original cited passage is required; more whole passages are
selected within the existing context budget.

The reviewer checks method identity, study system, intervention, measurements,
comparisons, scope and the relationship to the question. Its evidence entries
refer to supplied passage IDs, whose exact text and locators remain in the
cached job. The existing extractor still has to supply an exact 4–25 word
quotation. A source-support check does not independently establish scientific
truth, replication, or clinical validity.

## New claims

- `supported`: eligible for capture as a **proposed** draft. The job preserves
  the full assessment; the draft includes the model, revision, input digest and
  reason.
- `unsupported` or `uncertain`: the job becomes `held`, retaining the candidate,
  source and assessment. No new draft is captured. Held jobs are not silently
  regenerated or repeatedly submitted.
- Model/transport failure: the candidate stays retryable. A new attempt reviews
  the persisted candidate instead of generating another claim.
- Malformed review: diagnostics are retained in `rejected_reviews` and the
  existing bounded generation-attempt policy applies. Invalid review output is
  distinct from an unsupported scientific claim.

Already-captured drafts retain exact idempotent replay. A prepared draft that
has not been captured must pass the review and match the reviewed candidate's
derived evidence, source attribution and links. Changes to a prepared submission
are refused rather than silently repaired.

The terminal monitor shows `Checking source support` and a held count. A newly
started worker reports `source_review: enabled` in `research-status --json`.
Restart an older running worker to load this code.

## Existing claims

From the Superyak root, run a bounded pass over saved bot jobs in the selected
`ATLAS_PROJECT` (default `.engram/atlas/project`):

```sh
make atlas ATLAS_ARGS='review-backlog --limit 10'
```

The default reviewer is `qwen3.8:27b-mlx`; it must already be available through
local Ollama. `--model` selects another installed model. To review specific
claims, repeat `--record` with IDs from the selected project:

```sh
make atlas ATLAS_ARGS='review-backlog --limit 2 --record FIRST_RECORD_ID --record SECOND_RECORD_ID'
```

The low-level entry point from `atlas/` is
`python3 -m workbench.automation --project /absolute/path/to/project`. The pass uses
cached source passages and recorded jobs; it does not fetch new papers. It
prioritizes candidates that repeat a summary supplied in their extraction
context. Repetition is a screening signal, not itself a rejection.

Results are appended under `.atlas/research/reviews/`. The command reports
record IDs, verdicts, reasons, cached counts and errors. Exit code 2 means at
least one assessment could not complete; unsupported/uncertain verdicts are
completed assessments, not command errors. Running the same pass again skips
unchanged current assessments. Input hashes bind actual question, candidate,
source content, reviewer name and review revision; the record digest binds the
assessment to the saved item. A fresh assessment of revisited inputs is a new
immutable observation.

The backlog pass refuses a saved claim whose source, evidence, links or material
content differ from its recorded extraction. Such a record needs an explicit
assessment of the amendment rather than a verdict on the old candidate.

## How feedback affects subsequent research

Before selecting context for planning or extraction, the researcher reads the
latest applicable assessment for each saved item. `unsupported` and `uncertain`
items and their incident links are omitted from its research context. These
exclusions survive worker restarts and changes of writer model. A later
supported assessment can restore eligibility. Changing a saved record's content
invalidates the old assessment's binding.

Original drafts, published graph records and their scientific review statuses
are unchanged. The existing browser still displays those originals; inspect the
backlog command output and review ledger for automated assessment results.
This is a filter on the bot's research context, not an automatic withdrawal or
a human review. Unassessed older claims remain eligible until checked.

Backlog review can be explicitly invoked or scheduled with the `audit`
[worker role](research-worker-roles.md). Each audit turn checks at most one
uncached claim. The current bot's per-paper source check is enabled by default.

The same model can still share reasoning errors across extraction and review.
Separate calls remove the earlier-claim context from the reviewer but do not
create independent training or establish an accuracy rate. The selected real
examples and deterministic recovery tests measure this implementation's behavior;
broader scientific assessment remains necessary.
