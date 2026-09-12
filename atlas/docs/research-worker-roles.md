# Research worker roles

One selected local model takes five different roles in fresh calls. The default
order is `research`, `audit`, `question`, `overlap`, `connect`.

| Role | Work in one turn | Durable effect |
| --- | --- | --- |
| `research` | Read up to three papers for one active question; extract and separately check scoped assertions. | Add proposed findings, reuse an identical scoped finding with a reviewed question link, or hold the candidate. |
| `audit` | Reassess one original finding/comparison or graph addition against its bound source packet. Alternate source and graph backlogs when both have work. | Append an assessment. Negative assessments remove affected inputs from subsequent reasoning and scheduling. |
| `question` | Propose at most one distinct question from eligible evidence; separately check scope, usefulness, duplicates and parent links. | Atomically add one proposed question, its incoming evidence links and one or more broader questions. |
| `overlap` | Revisit existing findings, methods and experiments against a question; review each proposed relation separately. | Add up to three justified links without copying records. Retain held/no-op outcomes. |
| `connect` | Compare two source-checked claims from distinct sources, including different question neighborhoods. Review the comparison and both links. | Add one proposed comparison with `supports`/`challenges` links and an `informs` question link, or hold/skip it. |

All roles share one process and model. Each request has separate instructions and
selected evidence; there is no conversation history carried between roles.
Machine additions retain scientific status `proposed`. Automated support and
usefulness decisions do not establish independent scientific review.

## Running and observing

From the Superyak root after `make atlas-demo`, with the configured model
available through local Ollama. `ATLAS_PROJECT` selects the research project.

```sh
make atlas ATLAS_ARGS='start'
make atlas ATLAS_ARGS='research-status --once'
```

Repeat `--role` to override the order or give a role more turns. Use
`--role research` for paper research alone. `--cycles` counts role turns:

```sh
make atlas ATLAS_ARGS='run --role question --role overlap --cycles 2 --interval 1'
```

The default pause is 60 seconds between turns. `start` reports an existing worker
without changing its settings; `stop` waits for a checkpoint through a persisted
stop request. Restart after the worker stops to apply new settings. Supervision
preserves explicitly selected roles and a pause remains a pause.

Status includes role metrics for records saved, links added, reviews, holds,
skips, errors and elapsed seconds. These measure work performed, not scientific
accuracy. `question_agenda` reports each question's scheduling state and counts.

## An overlapping question agenda

There is one graph. A finding can answer, partially answer, raise or inform
several questions through independently reviewed links. A method can
`addresses` several questions; an experiment can `tests` several questions.
A question may be `part_of` several broader questions. Self-links and cycles in
that parent relationship are rejected. Obsidian keeps one readable note per
record, with related questions, parent/subquestion links and visible reasons.

Answers remain claims, so competing answers can support or challenge one
another through the existing comparison links. The overlap worker chooses:

| Claim → question relation | Meaning | Required worker explanation |
| --- | --- | --- |
| `answers` | A direct response covering the question within its explicit scope. | Answer scope; no remaining issue within that scope. |
| `partially_answers` | A direct response to a bounded part of the question. | Answer scope and what remains unresolved. |
| `raises_question` | A concrete gap, tension or missing measurement motivates the question. | The open issue. |
| `informs` | Relevant evidence or background. | Why it is relevant; no implied answer. |

Each review must assess the exact proposed predicate against the original
passages. A reviewer cannot silently downgrade an answer to relevance. The
answer scope and remaining issue appear in Obsidian alongside the link's
latest assessment. New question premises use `raises_question`; broader
question links remain `part_of`. No answer relation closes a question or
promotes a claim's scientific status.

The persisted agenda initially allows 12 active questions, including pinned
seed and user questions. Generated questions wait for an overlap attempt before
new paper research; an attempt with no suitable links still qualifies. Active
slots and research turns rotate fairly across restarts. A generated question
must receive a research turn before it can generate children. Additional
questions remain queued; rejected premises put dependent questions into
`needs_reassessment`. These are operational states, separate from scientific
record status. The `QuestionAgenda(..., active_limit=N)` interface sets the
persisted limit; it must accommodate all eligible pinned questions.

Question discovery compares nearby existing questions, including queued ones,
with another comparison around the proposed wording. A separate model review
can return useful, duplicate, unsupported or uncertain. Duplicate detection is
an automated judgment and may miss paraphrases. It never forces the worker to
invent a question to fill a quota.

Overlap considers new questions against older records, new records against
existing questions, and a rotating backfill. Revision `question-overlap-v3`
also revisits legacy `informs` pairs once for explicit classification. Existing
generic links stay intact, and a generic fallback is not duplicated. Unchanged
classified pairs are not resubmitted. Lexical ranking selects candidates;
it does not establish relevance or answer strength.
A rejected link does not invalidate an otherwise supported source finding or an
independently accepted sibling link.

Existing explicit links retain their recorded meanings. Changing a question's
scope can make its old bindings stale; automatic replacement or rebinding of
those links is not part of this pass.

## Evidence and recovery

Eligible primary claims must still match their original saved job, source,
quotation, scope and exact original relation IDs. A latest negative source audit
overrides an initial positive check. Additional graph links are assessed
independently. Methods and experiments need located evidence in cached sources;
their descriptions alone do not qualify as source text. Attributed required
passages must fit intact within the context budget. Accepted proposals quote
4–25 contiguous source words and each premise or relation needs its own evidence.

Cross-question paper jobs can reuse cached publication text. Conservative reuse
requires the same normalized scoped assertion and exact evidence quote; distinct
assertions or scopes from the same paper remain separate. Reusing a finding for
a new question still needs fresh relevance review. Original job ownership and
provenance remain intact.

Before capture, workers recheck input identities and eligibility under the inbox
lock. Question creation additionally checks that duplicate comparison inputs and
all selected parents remain eligible. Local question relevance does not add an
existing record to another Lighthouse publication view. View membership stays
an explicit recorder choice, separate from graph connectivity.

`.atlas/research/rotation.json` and append-only `turns/` retain turn progress.
Paper jobs and source assessments remain under `jobs/` and `reviews/`.
Comparisons use `connections/`. Question/overlap jobs use `graph-jobs/`; exact
atomic captures use the separate immutable `.atlas/graph-drafts/` journal.
Graph assessments append to `graph-reviews/`, with bounded audit attempt state
in `graph-audits/`. `agenda.json` preserves scheduling. Existing drafts and
receipts remain compatible and are never rewritten to add relations.

Transport outages retry the saved candidate. Malformed generation/review output
has a bounded attempt budget so it cannot starve unrelated work. Prepared graph
captures remain recoverable; retrying the same session and idempotency key
returns the saved receipt. Negative assessments leave the original journal and
notes intact. Later bound graph audit verdicts are shown in the human views.

No experiment-proposal worker is enabled. Sharing a model across roles can
produce shared errors; assess the system through inspected outputs and their
later effects.
