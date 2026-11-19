# The second pilot's selection: what is here

For `docs/superpowers/specs/2026-11-19-v2-a-line-that-says-a-plan-may-exist.md`, section 4.

- `used-before.txt`: the commits at which a turn with a model worker was run before this pilot, one a
  line. Taken by the lead from its run records. These are left out of both orders.
- `pool-p.order.json`, `pool-n.order.json`: the two pools in the order the spec fixes (ascending SHA-256
  of the ASCII text `20261120:pick:<commit>`), each item with its place `n`, its commit, its first
  parent, and the names the commit adds that the first pilot's second rule counts. A pool P item also
  has its matching files and its direct path. Made with the maker's own functions.
- `pool-p.record.json`, `pool-n.record.json`: the selecting readers' records, one for each pool, written
  by the reader. The lead changes one thing only, and says so in the record's `lead_note` with a count
  and the hash of the reader's own file: a path string that the lead's private-word scan flags is
  replaced by a placeholder. No verdict, reason, subject, term or query is changed. Pool N's record has
  27 such strings; pool P's has none.
- A record may hold more than the form below asks (pool N's has the reader's notes on method and on how
  each file was read), and pool N's names the last place walked `last_n` where the form says
  `stopped_n`. Both are the reader's and are left as written.

## A reader's record

One JSON object, sorted keys, indent 1, a final newline:

```
{"pool": "P" or "N",
 "reader": the reader's worker name,
 "repository_read": "the item list's repository",
 "walked": [ one entry for each item walked, in the order's own order, none left out ],
 "stopped": "nine accepted" | "the pool ended" | "time",
 "stopped_n": int, the place `n` of the last item walked}
```

An entry of `walked`, for either pool:

```
{"n": int, "commit": the forty characters, "verdict": "accepted" or "skipped",
 "reason": one or two sentences in the reader's words}
```

"Nine accepted" counts at most two accepted items of one plan group in pool P.

A pool P entry adds these and no terms or queries, since the reader reads the matching files the order
gives:

```
 "files_read": [paths read at the item's first parent],
 "plan_group": a short name for the piece of planned work the item belongs to,
 "plan_group_reason": why these matching files are one group, or why this file stands alone,
 "gives": what the item's tests use that the plan gives, in one sentence
```

A pool N entry adds:

```
 "subject": the work's subject in a few words,
 "terms": [the distinctive terms taken from the commit's message and change],
 "queries": [ {"query": the exact text searched,
               "mode": "whole word" or "substring"; "case kept" or "case folded"; "path" or "text",
               "hits": [every path the query found, complete] } ],
 "files_read": [every path read],
 "found": null, or the path of a document that specifies the work
```

The review's scope is the Markdown files tracked at the item's first parent. A verdict of "accepted" in
pool N means "none found by this review", and nothing more.
