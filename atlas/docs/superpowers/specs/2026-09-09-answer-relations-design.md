# Explicit answers and question motivation

Status: approved for planning and implementation by the user on 2026-09-09.

## Behavior

Keep one shared graph and existing claim records. Add three directed claim-to-
question predicates: `answers`, `partially_answers`, and `raises_question`.
`informs` remains valid for relevant background. Claims can still support or
challenge other claims, and questions retain parent/subquestion links.

`answers` means a direct response covering the question within its stated scope.
`partially_answers` means a direct response to a bounded aspect, with the
remaining uncertainty named. `raises_question` means the finding motivates a
specific unresolved gap, tension or missing measurement. Mere relevance uses
`informs`. Methods still `addresses` questions; experiments still `tests` them.

Answer links have an explicit `answer_scope` and `remaining` text. A full answer
has nonblank answer scope and no claimed unresolved remainder inside that scope;
a partial answer has both. A raises-question proposal names the open issue in
`remaining`. Generic relevance/method/experiment proposals use empty answer
fields. Each link has its own source evidence, rationale and separate review.
An answer is a proposed relationship, not a promotion of scientific status or
a decision that a question is closed. Several competing claims may answer the
same question; one claim can play different roles for different questions.

## Worker integration

Keep the five-role default. Extend overlap to choose the precise relationship
for each candidate and require its reviewer to assess that exact predicate,
answer scope and remainder. The reviewer can reject a strong answer claim; it
cannot silently downgrade it to a different relationship. Consider old generic
`informs` pairs for explicit classification under a new worker revision. Retain
old links and old journal entries; do not rewrite or silently upgrade them.
Avoid duplicate generic links and repeated unchanged classified pairs.

New question-worker premise links use `raises_question`; parent links remain
`part_of`. Existing v1/v2 jobs, proposals, receipts and graph audits keep their
original semantics and exact bindings. Prepared submissions replay unchanged.
Question discovery and later audits continue checking original cached evidence.

Reuse, connector neighborhoods and research context recognize every claim-to-
question predicate. A claim with an answer/motivation link already belongs to
that question neighborhood. A rejected answer link excludes that link, not an
otherwise supported original finding. A rejected initial motivation link still
requires reassessing its generated question.

## Human views and publication

Question notes distinguish proposed answers, partial answers, findings that
raise the question and other relevant findings. Claim notes show the reciprocal
question groups, answer scope, remaining uncertainty and the latest bound link
assessment. Keep one note per record and readable filenames. The offline browser
and Lighthouse validation accept the new predicates. Explicit publication
membership and grants remain unchanged by graph connectivity.

## Compatibility and verification

Extend the vocabulary additively; no immutable journals or generated versions
are edited. Preserve old evidence packets: adding a kind field to old packet
records would break comparison bindings. New overlap jobs instead carry a
separately bound `record_kinds` map for model instructions and endpoint checking.

Test valid/reversed endpoints and publication round-trips, direct and partial
answer validation, exact-predicate review, legacy job replay/auditing, generic
link reclassification without duplicates, independent rejection, generated-
question motivation, neighborhood/reuse behavior and human notes. Run a bounded
real-Qwen classification/review trial on a copy and restore the live worker with
its previous options and five roles. Zero accepted answer links is a valid
outcome when evidence cannot answer the question.
