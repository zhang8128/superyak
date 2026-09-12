# Continuous research with Ollama

From the Superyak root, initialize the selected project with `make atlas-demo`.
To start model-backed research against an existing local Ollama service:

```sh
make atlas ATLAS_ARGS='start'
```

The default model is `qwen3.8:27b-mlx`. The command checks that Ollama has the
model, launches a detached worker, and returns its status. It does not download
a model. Repeating the command reports the existing worker. The worker continues
after the launching terminal closes, until stopped. `ATLAS_PROJECT` selects its
research project, defaulting to `.engram/atlas/project`. Superyak setup does not
install the standalone checkout's login or periodic supervision services.

Dynamic context is on by default. Before each model call, the worker selects relevant original graph records and paper passages within a fixed request budget, preserving their sources and limitations. Earlier research stays available across fresh calls. `research-status` shows `context_mode: dynamic`; saved jobs retain what was selected and omitted. See [dynamic research context](dynamic-research-context.md) for limits and verification.

```sh
make atlas ATLAS_ARGS='research-status'
make atlas ATLAS_ARGS='stop'
```

In a terminal, `research-status` shows a readable status header and up to 20 recent log events, then keeps scrolling as research progresses. It shows planning, searches, paper reading and analysis, saving proposed findings, Lighthouse refreshes, pass totals, errors, and the next scheduled pass. Times use your local timezone. **Ctrl-C closes the monitor without stopping the research worker.** The monitor can stay open across worker restarts and log replacement. Activity appears when the worker emits an event; model generation can be quiet until the next step.

Use `make atlas ATLAS_ARGS='research-status --once'` for a readable snapshot, or
`make atlas ATLAS_ARGS='research-status --json'` for machine-readable status.
Redirected or piped output defaults to the JSON snapshot. Add `--follow` to
stream readable activity through a pipe or into a file.

Stop requests apply to the current worker instance. The worker checks between operations and during waits; an active HTTP request is bounded by its deadline. No new draft is submitted after a stop checkpoint. Check `research-status --json` for `running: false` before treating a requested stop as completed.

The live browser is `.atlas/research/index.html` inside the selected project.
It refreshes on disk after each pass; reload an open browser tab to see additions.
`research-status` reports its absolute path, the worker log, current phase,
question/paper, last completed pass, errors, and new record IDs.
`make atlas ATLAS_ARGS='status'` reports the inbox and Lighthouse publication state.

Run `make atlas ATLAS_ARGS='open'` for the current searchable browser, or
`make atlas ATLAS_ARGS='open --obsidian'` for linked notes and the visual canvas.
These are generated under the project's `Research/` and refresh after saves
and research passes. Annotations below **Personal notes** are preserved.
See [research in Obsidian](obsidian-research.md) for opening the vault and recovery.

## What it researches

The initial configuration contains the cell-fate and gene-regulation questions.
The worker alternates between active questions selected by its configured
publication views. Each new claim follows the view membership of its target
question. The old research archive was excluded from this source import.

Select an existing configured question or adjust the cadence when starting a stopped worker:

```sh
make atlas ATLAS_ARGS='start --question q-fate --question q-regulation --model qwen3.8:27b-mlx --batch-size 3 --interval 60'
```

By default, turns rotate through paper research, auditing, question discovery, question overlap, and source-grounded comparison, with a 60-second pause between turns. A research turn processes up to three papers for one question. Search pages and unfinished jobs are saved; the next research turn continues from the saved page or asks Qwen for another query when the search is exhausted. Papers already completed for that question are skipped. The same finding can inform multiple questions through separately reviewed links; distinct scoped assertions from one paper remain separate records. Generated questions enter a bounded agenda and receive an overlap attempt before paper research. See [worker roles](research-worker-roles.md) for outputs and overrides; `--role research` selects paper research alone.

To measure a finite run in the foreground:

```sh
make atlas ATLAS_ARGS='run --question q-fate --batch-size 1 --cycles 1'
```

`run` also enforces the single-worker lock. Without `--cycles`, it continues until
stopped or interrupted. A finite run exits with code 2 when its final pass has
errors; startup/operational failures use code 1. The low-level equivalent, from
`atlas/`, is `python3 -m workbench.automation --project /absolute/path/to/project`.

## Sources and records

Qwen proposes a literature query using the question and its existing graph context. Europe PMC supplies the publication identity, title, citation, and abstract. If PMC full text is available, the adapter extracts a bounded selection of article paragraphs. The model receives the retrieved passages and their locators, with explicit `abstract_only` or `full_text_excerpt` coverage.

Qwen can decline an irrelevant paper. Otherwise it proposes one claim with its scope, limitations, a short exact quotation, and a rationale for its connection to the question. The runner rejects unknown fields, invalid relevance values, missing limitations, invented passage IDs, and quotations that do not match 4–25 words in the selected passage. Model-generated URLs, publication identities, or review statuses are not accepted.

After quotation validation, a separate model call checks the claim against the current source without earlier graph claims in its context. Only `supported` candidates proceed to the existing `ResearchInbox` API, with an `informs` relation to the question. Unsupported or uncertain candidates remain held jobs. The claim and relation remain **proposed**. Scope, uncertainty, retrieval coverage, source hash, actual model name, worker attribution and automated assessment remain attached. These checks do not establish independent scientific validity. Use `make atlas ATLAS_ARGS='review-backlog --limit 10'` to assess saved claims and exclude flagged records from later bot context; see [source-support review](source-support-review.md).

Later overlap turns can add explicit `answers`, `partially_answers` or
`raises_question` links, each with its own source review, answer scope and
remaining issue where applicable. The same claim can connect to multiple
questions. Existing relevance links remain intact, and an answer link does not
close a question. Obsidian groups these relationships by meaning and shows the
latest assessment on each link.

The integration uses Ollama's documented [chat endpoint](https://docs.ollama.com/api/chat) and [structured output format](https://docs.ollama.com/capabilities/structured-outputs), plus the [Europe PMC literature services](https://europepmc.org/developers). Generation stays local; literature searches and document retrieval use the network.

## Recovery and storage

Runtime state is under gitignored `.atlas/research/`. `jobs/` holds retrieved passage snapshots, model responses and timing metrics, exact prepared drafts, and capture receipts. `frontier.json` holds search cursors and unfinished jobs; `worker.json` and `worker.log` hold process progress. The worker has a stable local attribution identity across restarts. Do not edit job submissions or the existing `.atlas/drafts/` journal in place.

The exact draft is saved before submission. If capture succeeds but its response is lost, replay uses the same session, key, and content, so it resolves to the existing record. A publication failure does not erase a saved draft. Subsequent passes refresh the complete bundle and browser; manual recovery remains available through `make atlas ATLAS_ARGS='refresh'`.

Temporary network/model/storage failures stay retryable, with increasing delays between failed passes up to 15 minutes. Under supervision, five consecutive operationally failed passes release the worker so a fresh process can resume the saved jobs, including recovery from a stuck HTTP transport.

Invalid retrieved data or model answers are tried at most three times in a generation round, then retained as failed jobs. Rejected parsed analyses do not increase the worker-wide delay: other papers continue at the configured interval. Their answers, model metrics and selected-context manifests remain in each job's `rejected_extractions`; `last_cycle.errors` and the job's `last_error` retain the reason. Retries receive the preceding rejected quote and validation error as diagnostic data. Feedback is reduced or omitted if needed to retain a complete source passage within the request budget.

When an improved analyzer revision is installed, exhausted analysis jobs automatically receive one new bounded round for that revision. `recoveries` retains the earlier revision, attempts and error. Completed jobs keep their submission identities and are not regenerated. Rolling back to an already attempted revision does not reset its retry allowance. Prior research is background for relevance; a new claim and its quotation must use the current document's passages. Every fresh answer still passes the exact evidence checks before capture; a rejected answer is never silently rewritten into a claim.

The existing inbox limit is 1,000 drafts. At capacity, new paper analysis pauses
and the worker reports the condition while allowing saved publications to recover.
Existing Lighthouse grants are not renewed by the worker; expiry affects overlap
admission, not the underlying draft's saved status. Work remains inside the
selected research project; the bundled seed files are unchanged.
