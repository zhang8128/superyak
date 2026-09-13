# Optional local assistance and selected sources

Superyak works without inference. Assistance is disabled by default, and the browser
cannot select a provider, endpoint, model, fallback, or another person's draft.

## Operator configuration

To opt in, create an operator-owned JSON file with exactly these values:

```json
{
  "model": "gemma4:31b",
  "publisher": "Google",
  "digest": "6316f0629137b426c9d9b853ffc4c8209589f30ee39aebede6285096c0ff47e7",
  "endpoint": "http://127.0.0.1:11434"
}
```

Pass its path when starting your own peer:

```sh
uv run --locked python -m superyak_peer serve --data-dir .engram/home --model-config /path/to/model.json
```

The file is bounded to 4 KiB. Unknown fields or different values are rejected by
the CLI before serving. The app factory accepts the same optional `model_config`
dictionary; an unapproved factory configuration leaves the assistant disabled.
This command does not install, pull, start, or restart a model service.

Eligibility follows the operator-approved Google publisher and this exact artifact,
under this application’s American-model requirement. The native Ollama
`/api/tags` entry must match the exact model name and digest before generation.
Status may perform that read-only check; every generation repeats it. Local service
and tag integrity are trust assumptions: this is not a cryptographic attestation
of a running model process, and the native API does not atomically pin a tag across
metadata read and generation. Only the explicitly configured loopback destination
is used, with no proxies, redirects, provider environment variables, or fallback.

An explicit request sends only the entered text and selected saved layer title/body.
The user sees the selected saved version. Unsaved editor text, attachments, chats,
audiences, source collections, account metadata, and other drafts are excluded.
No layer is selected when `layer_id` is absent. Limits are 8,000 entered characters,
32,000 selected-body characters, and a combined canonical JSON prompt budget of
12,000 bytes. Oversized input is rejected before any endpoint call. Generation uses
16,384 context tokens, at most 1,024 output tokens, nonstreaming native output and
thinking disabled; replies are capped at 128 KiB and suggestions at 16,000 characters.
A length-truncated, incomplete, wrong-model, empty, or malformed response is a failure.

Native identity requests have a five-second total deadline; generation has a
120-second total deadline. Socket shutdown enforces this even for trickling headers
or bodies. There is one generation at a time per application process, and no POST
retry. A verification or generation failure disables that adapter instance; no
suggestion is claimed for a failure or unknown outcome. After the operator resolves
the cause, a new explicitly configured application instance can check identity again.
A timeout does not prove the native server stopped computation.

Suggestions live only in the authenticated response and account-bound browser memory.
The browser's apply action **appends** to the latest unsaved draft text, never replaces
newer typing, saves, or activates. A delayed response is discarded after logout or
account change. Saving and releasing retain their existing explicit version checks.

A single fictional picnic-note request was measured on September 12, 2026: native
Gemma returned a suggestion in 22.56 seconds end to end, with the draft unchanged
and no active release. This is one integration measurement, not a capacity or
clinical-quality claim. Validation did not persist a default-enabled configuration.

## Selected-source document

The [backend data-source catalog](API.md#backend-data-sources) manages manual
file and selected-record imports independently of model assistance. Accounts own
their sources, settings, item links and receipts. Pausing stops new imports into
that source; it does not withdraw already shared layers or erase stored inputs.
Existing selected records are retained and cataloged without invented historical
import receipts. No connector, URL fetch, background worker or model request is
started by registering a source. CSV/JSON uploads are stored as exact file bytes,
not interpreted as clinical records or executed instructions.

`superyak.selected-sources.v1` is a standalone JSON interchange format. A document
has exactly `format` and `records`; select 1–20 records, totaling at most 512 KiB.
Each record contains these fields:

| Field | Meaning |
|---|---|
| `id`, `origin` | Origin-qualified `peer:<origin>:<path>` or `adna:<origin>:<path>` source identity; preserved on import |
| `source_locator` | Opaque original source/version locator; never fetched or executed |
| `source_hash` | SHA-256 of selected `content` canonical JSON: sorted keys, compact separators, ASCII escapes, UTF-8 bytes |
| `revision` | Source revision string; local exports use `draft:N` or `active:N` |
| `revision_of` | Previous source/version locator or `null`; active exports reference the previous actual release, skipping withdrawals |
| `correction_of` | Up to 20 opaque correction references; preserved verbatim |
| `author` | Original author assertion; local exports use exact `peer_id:user_id` |
| `content` | Exactly `title` (200 characters) and `body` (100,000 characters) |
| `audience` | Exactly `kind` (`draft`/`active`), `public` boolean, qualified `people`, and qualified `spaces` |

Hashes verify the selected title/body projection, **not** an unselected original
file or the author's identity. The full record retains attribution fields, but is
not a signed proof of provenance or content truth. Origin labels convey no account,
peer pairing, membership, or grant authority. Draft audiences describe intended
release selections. Active audience labels describe recorded release selections;
organization membership can change and audience metadata is not a receiver ACL.

Exports require explicit owned layer IDs and exact saved versions or active release
revisions. No bulk ambient export, attachments, chat history, sessions, identity
keys, unselected drafts, or private backing stores are included. Remote people keep
their original peer/person identity, not the exporting peer's contact alias.

Imports are validated atomically and kept in a private `imported_sources` collection
owned by the importing local account. They never create layers, files, accounts,
spaces, grants, outbox deliveries, or public releases. Same owner/source/revision
imports are idempotent only if all content and attribution agree; conflicts return
409. Each source gets a local selection ID, while its original record remains
unchanged. Explicitly downloading a selected imported record preserves that record.
The source UI shows origin, author, locator, hash, revision/correction references,
and the recorded audience separately from effective access here (only the owner).
No imported instructions, links, or common-origin declarations are executed.

## aDNA projection

The authenticated owner can download one current active local layer as Markdown.
Place the downloaded `selected-source.md` under a selected aDNA project's `what/`
directory to make it discoverable by the existing read-only aDNA adapter. JSON
literals in YAML frontmatter preserve source identity, locator, hash, revision,
author, audience and correction references; the selected body follows the frontmatter.
The complete Markdown download, including frontmatter and separators, must fit
65,536 UTF-8 bytes and contain no literal NUL characters to match the reader.
Incompatible exports return a clear HTTP 400; selected content is never truncated
or modified. Multibyte body text and escaped frontmatter consume this same byte
budget. The parent adapter will independently hash the entire Markdown file, as described
in [aDNA compatibility](../docs/adna-compatibility.md). Those two hash scopes differ.

This export is a knowledge document, not an executable lattice, a mount of a live
research store, a grant, or a model request. A withdrawn layer cannot be exported
through the active route; a private next draft is excluded. The peer package uses
only its own modules and standard-library projection code.
