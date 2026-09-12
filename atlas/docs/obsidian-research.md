# Research in Obsidian and the browser

From the Superyak root after `make atlas-demo`, run:

```sh
make atlas ATLAS_ARGS='open --obsidian'
```

This refreshes the current research and opens `Research/Start Here.md` in
Obsidian. Open the selected project (`.engram/atlas/project` by default) as a
vault first if it is not already registered. `ATLAS_PROJECT` selects another
project. The `Research` folder can also be opened as its own
vault: internal links use unique note names, so both layouts work. No community
plugins are required.

For the searchable offline browser:

```sh
make atlas ATLAS_ARGS='open'
```

The browser is written to `Research/index.html`. It contains every current
record and source, with search, category filters, evidence, relationships,
scope, and review status. The worker's existing `.atlas/research/index.html`
continues to update as well. Reload an open browser tab to see new results.

## What to open

- **Graph view** opens the native network with readable node names and four
  type colors: gold questions, blue findings, green methods, purple experiments.
  **Graph Guide** in the Research folder has a legend and useful filters.
- **Start Here** lists the full collection, with recent findings first.
- **Atlas Map.canvas** shows each active question and up to six recently
  recorded connected items. Click a note link for its full evidence and scope.
  The map is an overview; additional findings remain in the notes and browser.
- **Records** contains questions, approaches, findings, and proposed experiments.
- **Sources** contains citations, publication links, and links back to the
  records that cite them.
- **Lighthouses** contains the configured local groupings. A record shared by
  two Lighthouses has one note identity and appears in both indexes.

Obsidian's built-in **Graph view** starts with research records, excluding
archived and withdrawn records. Its default search is
`path:"Research/Records" -tag:#atlas/archived -tag:#atlas/withdrawn`.
To include papers, use
`(path:"Research/Records" OR path:"Research/Sources") -tag:#atlas/archived -tag:#atlas/withdrawn`.
Collection indexes and Start Here are navigation pages, so they are outside
these filters. Isolated findings remain visible. Open a note and use **Open
local graph** to explore its neighborhood. In a standalone Research vault,
use `path:Records` and `path:Sources` instead.

Graph lines represent note links; the native graph does not label relationship
types. Open **Connected research** to read the direction, rationale, and status
of a relationship. Colors identify record types, not scientific validity.
Each note leads with its summary, scope,
evidence, and review status. Full context, IDs, attribution, and relationship
metadata remain in the collapsed **Technical details** callout. The canvas
provides labeled arrows and omits withdrawn records and relations.

The current collection is the evidence pilot plus the selected project's
immutable research inbox. The older cleaned archive was excluded from the
monorepo import and remains in the standalone checkout.

## Automatic updates and personal notes

New `atlas_record`/CLI saves and `make atlas ATLAS_ARGS='refresh'` export the complete
current collection. The continuous worker refreshes it after saves and at the
end of each pass. Obsidian notices Markdown and canvas changes on disk.
Previously running worker or MCP processes need to load the updated code;
fresh CLI calls use it immediately.

Write annotations under **Personal notes**, below the generated section of
each note. Atlas preserves this section, and unchanged notes are not rewritten.
The graph filter and colors are installed once, with the previous graph
settings backed up. Later refreshes preserve your graph customization.

Readable filenames such as `Finding - A scoped finding.md` replace opaque
record hashes. Duplicate titles get a number, and the ID-to-filename registry
at `.atlas/research/note-paths.json` keeps those choices stable across refreshes.
The original record IDs in the evidence store never change. Keep this registry
when backing up the vault.

On the first refresh after upgrading, Atlas checks and backs up legacy notes
before migrating them. Personal annotations move with their note. Wikilinks,
Markdown links, and Obsidian workspace/bookmark destinations are updated to the
readable filenames. Changed files have exact backups under
`.atlas/research/obsidian-backups/`, outside the visible vault graph. Literal
code examples are preserved. A pending migration resumes on the next refresh.

The generated part of a note is marked by HTML comments. If it is edited,
Atlas preserves the file and reports an export conflict. Put annotations in
the Personal notes section to keep that note updating automatically.

If a recognized Atlas canvas has been edited, Atlas saves an exact copy under
`Research/Preserved edits/`, verifies it, and refreshes the live map. Start Here
links to these separate editable copies. Repeated refreshes reuse identical
copies. If copying fails, the edited original stays intact and the export
reports the error. Foreign files, symlinks and invalid canvases remain protected.
During filename migration, preserved canvases also receive a **Your research
map** companion copy with their layout retained and their note links updated;
the historical copy remains exact.

Records removed from a later snapshot retain their old notes, clearly labeled
as archived exports. These preserve the original displayed evidence and your
annotations; they are listed separately on the start page.

Capture and Lighthouse publication have separate status from these derived
views. A view conflict cannot erase a saved finding or claim it was not
recorded. Inspect `research_views` in `make atlas ATLAS_ARGS='status'` or the scrolling
`make atlas ATLAS_ARGS='research-status'` log, then use `make atlas ATLAS_ARGS='refresh'` after
resolving the conflict.

`Research/` and `.obsidian/` are local, Git-ignored output/settings. Code is
versioned in the GitHub repository; live findings and personal notes need a
separate backup or sync arrangement. Opening the project in Obsidian does not
turn GitHub pushes into automatic research backups.

The integration uses Obsidian's documented [internal links](https://obsidian.md/help/links),
[Graph view](https://obsidian.md/help/plugins/graph), [Search filters](https://obsidian.md/help/plugins/search),
[callouts](https://obsidian.md/help/callouts), [open-note URI](https://obsidian.md/help/uri),
and the [JSON Canvas format](https://jsoncanvas.org/spec/1.0/).

## Overlapping questions

Each record still has one note. Its related-question links can point to several
question neighborhoods; questions show broader questions, subquestions,
findings, methods and experiments. Findings appear in separate sections:

- **Proposed answers** directly respond within their stated answer scope.
- **Partial answers** address a bounded aspect and name the remaining uncertainty.
- **Findings that raise this question** identify a gap, tension or missing measurement.
- **Relevant findings** supply background without claiming to answer the question.

Finding notes group their question links by the same roles. One finding can
answer one question, partly answer another and raise a third, using the same
note in every neighborhood. Answer scope, remaining uncertainty, link reasons
and the latest automated review of the current link are visible beside each connection.
A later rejected answer stays inspectable with its review reason; rejecting the
link does not by itself reject the original finding. Existing generic relevance
links remain visible when a new explicit answer relationship is recorded.

An answer link does not close a question or promote its scientific status.
An empty answer section means no answer relationship is recorded. Competing
proposed answers can coexist, with separate evidence and assessments. The
offline browser and canvas use readable labels such as **partially answers**
and **raises question**; open the notes or browser for the scoped explanation.

Question notes show operational agenda state separately from scientific status.
New questions wait for overlap
before research, and questions with rejected premises need reassessment.

The default worker rotation includes question discovery and overlap. See
[worker roles](research-worker-roles.md) for evidence checks and scheduling.
