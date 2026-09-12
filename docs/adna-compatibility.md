# Using aDNA with Superyak

Superyak can use an existing aDNA project as attributed context in terminal chat,
browser chat, and terminal coding. Lighthouse can project an aDNA lattice into
a digest-verifiable Snapshot. Each installation selects its own local sources;
projects retain their directories and original documents.

## Inspect a project without a model

From the Superyak checkout after `make setup`:

```sh
make adna ADNA_ARGS='inspect clinic=/path/to/Clinic.aDNA'
make adna ADNA_ARGS='search clinic=/path/to/Clinic.aDNA sleep'
make adna ADNA_ARGS='read clinic=/path/to/Clinic.aDNA adna:clinic:what/sleep.md'
```

The installed command is also available as `engram/.venv/bin/superyak-adna`.
`python -m adna_cli` works from `engram/`. All three commands return JSON;
inspection and search include scan coverage. They create no conversation store
and require no model credentials. Read accepts `--offset` and `--limit` and
returns `next_offset` for another page.

Select the project directory, not a parent containing several projects. Supported
layouts are:

| Layout | Knowledge root |
| --- | --- |
| Bare project | `Clinic.aDNA/{who,what,how}/` |
| Embedded project | `Clinic/.agentic/{who,what,how}/` |
| Framework workspace | `aDNA/.adna/{who,what,how}/` |

For the framework layout, the selected source is the framework itself. Sibling
`*.aDNA` projects each require their own selection. If several layouts exist in
one directory, precedence is bare, `.agentic`, then `.adna`; `inspect` reports
the chosen root.

## Use a project in a conversation or coding task

```sh
make chat ENGRAM_ARGS='--no-engram --adna-project clinic=/path/to/Clinic.aDNA --thread clinic-chat'
make serve ENGRAM_ARGS='--no-engram --adna-project clinic=/path/to/Clinic.aDNA' SERVE_ARGS='--port 7434'
```

The browser is at `http://127.0.0.1:7434`. The same source inspection controls
used for Engram documents resolve aDNA IDs to original pages. Retrieval uses
lexical matches against the current question and recent conversation, subject
to the existing context budget. The context manifest records selected IDs,
document versions, and source coverage. Documents that do not match or do not
fit the budget may be omitted.

For coding, run from `engram/`:

```sh
uv run --locked python -m context_cli \
  --no-engram --adna-project clinic=/path/to/Clinic.aDNA --thread clinic-tools \
  code --repo /path/to/code 'Use the project specifications to implement the import tool'
```

Coding includes aDNA retrieval between episodes and exposes selected documents
through `archive_search` and `archive_read`. Its printed resume command retains
the canonical project selections. Chat with the Responses provider also exposes
these read-only tools. Subscription chat receives the selected context at the
start of its episode; it retains its existing tool-disabled behavior. See the
[runtime guide](../engram/docs/dynamic-context.md) for provider setup, billing,
budget controls, and coding permissions.

Repeat `--adna-project` for up to six distinct sources. An origin is a locally
declared, lowercase name beginning with a letter and containing letters, digits,
or hyphens, at most 63 characters. For example:

```text
--adna-project clinic=/path/to/Clinic.aDNA --adna-project family=/path/to/Family.aDNA
```

## Identity, provenance, and boundaries

The ID `adna:clinic:what/sleep.md` names the origin and a path relative to its
knowledge root. UTF-8 paths are URL-encoded. Moving a project preserves its IDs
when the origin and relative paths stay the same. Each version is the SHA-256
of the full original file, including frontmatter. Retrieved excerpts retain
the origin, path, `who`/`what`/`how` location, offset, and uncertainty in the
source text. The origin label is attribution supplied by the operator; it is
not cryptographic proof of a peer's identity or an assertion that the content
is true.

The adapter reads Markdown and `.lattice.yaml`/`.lattice.yml` below the three
directories, plus `AGENTS.md`, `CLAUDE.md`, `MANIFEST.md`, `STATE.md`, and
`README.md` at the knowledge root. It treats their contents as source accounts;
it does not execute their skills or resolve their links. Hidden files,
symlinked files/directories, other extensions, and unrelated root files are
excluded. It does not create memory databases inside the aDNA project.

Default scan bounds are 1,024 eligible files, 8 MiB of text, 8,192 directory
entries, and one second per source search. Individual documents are limited to
64 KiB, paths to 12 components and 180 URL-encoded characters, and read pages to
4,096 characters. Search excerpts are at most 8,192 characters. These are
bounded samples, not exhaustive project audits; check `coverage` for truncation
or unreadable files. Source files and the root identity are rechecked before
dispatch. Changed material is dropped, or an active chat tool episode stops
when it has already used that material. Coding rechecks between episodes, not
inside every native model call.

Selecting a source makes eligible content available to the configured model
and to every thread in that runtime process. Tool excerpts and dialogue can be
retained in its local conversation archive. Use separate processes, data
directories, and source selections for different people or cases. The current
browser remains a local interface; this integration does not supply account
authentication or per-person authorization.

## Project a lattice into Lighthouse

From `lighthouse/`, after building the workspace:

```sh
pnpm lighthouse project-adna /path/to/workflow.lattice.yaml \
  --issuer urn:peer:clinic --id urn:snapshot:clinic:workflow \
  --issued-at 2026-09-11T12:00:00Z > /tmp/clinic-snapshot.json
pnpm lighthouse validate /tmp/clinic-snapshot.json
```

The input can also be a directory containing exactly one lattice YAML file.
Multiple candidates require explicit selection. Both the current `lattice:`
envelope and the original flat Lighthouse fixture are accepted. Node IDs must
be unique, and edges must reference included executable nodes; the reserved
`lattice_interface` node remains metadata.

The projection covers nodes, explicit port types, edges and data mappings,
named edge ports, unresolved node references, and workflow context.
`lattice://` references remain intact. Missing port types or mappings produce
an indeterminate port-compatibility result; the adapter does not invent types
from prompts or external references. It preserves the previous typed orders
fixture and scopes generated claims to the actual workflow.

This Snapshot is a projection for Lighthouse's typed-port profile, not a
lossless round trip of the workflow YAML. Prompts, execution settings, FAIR
metadata, and other workflow fields remain in the original. Export seals a
digest; it does not sign, publish, execute, or establish trust in the issuer.

This provides a local aDNA integration on which peers can build. Nebula mesh
setup, LatLab account provisioning, resolving remote lattice references, and
deployment to Stanley's Pi are separate work. Existing Engram/Lighthouse peer
sharing continues to use its explicit publisher/receiver policies.

## Verification

Regression tests exercise both project layouts, framework selection, content
provenance, relocation, file changes, traversal/symlink boundaries, source
inspection, chat dispatch, coding archive tools, and resume arguments. The
TypeScript suite includes the pinned upstream `hello_world.lattice.yaml`
example (with its license), the older typed-port fixture, external references,
ambiguous input rejection, and export/validate CLI round trips. These tests
use a recording provider; they do not spend model tokens or validate medical
claims.
