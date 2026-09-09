# Runtime installation

The Superyak runtime binds one source checkout to one existing Engram memory
home. Source code, its virtual environment, and executable scripts come from
the checkout containing `scripts/runtime.py`. Databases, receiver settings,
publisher settings, and policies remain under the separately configured memory
home.

The launcher never derives source paths from `ENGRAM_HOME`, creates a runtime
configuration, or creates a missing memory database. This makes a typo fail
before Engram starts. Existing Engram behavior still permits a named instance
to use the legacy `<memory_home>/.engram/graph.db` when that file already
exists.

## Configure the binding

Create `~/.config/superyak/runtime.json` explicitly:

```json
{
  "memory_home": "/absolute/path/to/existing/engram-data",
  "default_instance": "engram"
}
```

`memory_home` must be an absolute, existing directory. `default_instance` must
contain only letters, digits, `_`, or `-`, start with a letter or digit, and be
at most 64 characters. The launcher does not create or repair either value.
Use `--config PATH` to select another file, or set `SUPERYAK_RUNTIME_CONFIG`.
The default path is still explicit state: the file must already exist.

The default instance applies when the caller's project has no binding. An
existing `<project>/.engram/config.toml` `instance` value keeps its established
precedence. `ENGRAM_PROJECT_ROOT` selects that project root when set; otherwise
the caller's current directory is used. `--instance NAME` overrides the
runtime default but does not replace a project binding.

## Install the stable command

Keep host integrations pointed at one stable path while the canonical checkout
can be replaced or rolled back. For example, install
`~/.local/bin/superyak-runtime` with this content, substituting the checkout's
absolute path:

```sh
#!/bin/sh
exec /absolute/path/to/superyak/engram/.venv/bin/python \
  /absolute/path/to/superyak/scripts/runtime.py "$@"
```

Make the wrapper executable. Do not put `ENGRAM_HOME` in it; `runtime.json` is
the single source for data routing. The Python path in the wrapper selects the
checkout, and `scripts/runtime.py` independently confirms source paths from its
own location.

Codex can retain its per-process session binding while using the wrapper:

```sh
ENGRAM_RUN_KEY="codex:$PPID" exec "$HOME/.local/bin/superyak-runtime" mcp
```

Set `ENGRAM_HARNESS=codex` in the Codex MCP environment. Claude Code uses the
same wrapper with `ENGRAM_HARNESS=claude-code`. The launcher preserves the
caller environment, including `ENGRAM_HARNESS` and `ENGRAM_RUN_KEY`, and does
not change the caller's current directory.

## Run the services and hooks

Options precede the command:

```sh
superyak-runtime mcp
superyak-runtime hook wake
superyak-runtime hook nudge
superyak-runtime hook sleep
superyak-runtime publisher
superyak-runtime --instance research mcp
superyak-runtime --config /absolute/path/runtime.json status
```

The publisher reads the existing
`<memory_home>/.engram/lighthouse-daemon.toml`. Supervise
`superyak-runtime publisher` as a long-running user service, such as a macOS
LaunchAgent with the wrapper and `publisher` as its `ProgramArguments`. Keep
the existing daemon TOML and publisher policies in the memory home; installation
does not broaden audiences, extend grants, or republish memories.

Receiver enablement remains scoped to the selected named instance. Its
`<memory_home>/.engram/instances/<instance>/lighthouse-receiver.toml` must set
`enabled = true`, list only the chosen publishers, and point to the intended
Unix socket and receiver policy. The receiver policy independently controls
`recall`, `read`, and `inject_context` for the declared context and purpose.
See [Run a Lighthouse crossing](../engram/docs/lighthouse-receiver.md) for the
bounded receiver format and policy details.

Restart MCP and hook host processes after changing the source build, wrapper,
or runtime binding. Restart the supervised publisher after changing its source
build or launch arguments. Receiver and policy files are re-read during normal
operations, though restarting after an installation cutover gives every
process the same source revision.

## Inspect health without initializing Engram

Run:

```sh
make status
make status RUNTIME_CONFIG=/absolute/path/runtime.json
make status RUNTIME_ARGS='--instance research'
```

`status` emits one JSON object. It reports the configured source path and
revision, interpreter, memory home, runtime default, project override,
effective instance and database, receiver state and chosen publishers,
publisher resources, socket connectivity, and the newest Lighthouse receipt
ID and timestamp. The revision is the configured checkout revision; it does
not claim that an already-running process has restarted onto that revision.

The command exits zero only when required source, interpreter, selected-store,
receiver, publisher, policy-file parseability, and socket checks succeed. A
disabled receiver is reported as `disabled`; malformed enabled settings or an
unreadable policy are `invalid`; a configured socket that cannot be connected
is reported as disconnected. A new installation can be healthy with
`latest_lighthouse_receipt: null`.

Status uses bounded file reads, a bounded socket connection without sending a
request, and a read-only SQLite metadata query. It does not import the Engram
server, initialize embeddings or models, run migrations, expose environment
values, or print query or memory content. A parseable policy report means only
that bounded JSON parsing succeeded; authorization is verified by the explicit
Lighthouse crossing tests.

## Preserve data and roll back

Back up runtime and host configuration before a cutover, and use SQLite's
online backup mechanism for active stores. Do not move or merge memory
databases as part of installing the launcher. The runtime binding can continue
to point at the existing memory home while source changes independently.

To roll back, stop the publisher service, restore the previous host bindings
and runtime JSON from backup, point the stable wrapper at the previous known
source checkout, and restart MCP hosts and the publisher. Keep the current and
previous memory-home paths untouched during this process. Run `status` through
the restored wrapper before reconnecting clients.
