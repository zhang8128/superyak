# superyak-memory

Engram memory for a ship's Claude Code sessions, from this checkout: the `engram` MCP server (remember, recall, share
and the rest) and Engram's hooks (wake at session start, sleep at stop, nudge on each prompt when the shared embedder
runs).

Install, once per machine, from the repo root:

```sh
make setup-engram                                   # Engram's environment, if engram/.venv is missing
claude plugin marketplace add "$PWD"
claude plugin install superyak-memory@superyak
```

Settings come from `~/.config/superyak/runtime.json` (`memory_home`, `default_instance`, `embedder_socket`;
`SUPERYAK_RUNTIME_CONFIG` names another file). Without it, memory lives under `$HOME/.engram` in the instance
`default`.

Memory: with the shared embedder's socket present (`superyak-embedder`), no session loads a model. Without it, the
server loads the model on its first embed and drops it after five idle minutes (`ENGRAM_EMBED_IDLE_SECONDS`), and the
nudge hook is skipped, since it would load the model on every prompt. Measured on the Pi, 2026-11-02: 241 MB at rest,
1.09 GB while the model is loaded.

If Engram's own plugin (`engram/hooks/hooks.json`, run through `superyak-runtime`) is also installed, the hooks run
twice: keep one.
