# Sample event streams

Captured by the lead on 2026-11-14 from one tiny run of each command line on a throwaway repository holding one
file, `a.txt`. The prompt asked for a read of `a.txt`, a run of `ls`, a read of a file that does not exist, and
the word "done". Paths, ids and account details were removed, and the sandbox is written as `/sandbox`.

| File | From |
| --- | --- |
| `claude-stream-sample.jsonl` | `claude -p --output-format stream-json --verbose` |
| `codex-json-sample.jsonl` | `codex exec --json` |

They show the real shapes: a tool call, its result, a failed call, and token usage. Add fixtures beside them;
do not edit these two.
