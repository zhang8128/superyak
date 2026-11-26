# North-star test 5, Measure 2: a blind expected set

Rio Grande found that Measure 2's `notices-expected.json` landed in the same commit as `apply_notice` (ea18ee6b, 11-21)
and changed with amendment 4 (a2ec76c7), so it checks the code against its author's own reading (all hands 0bcb4fe1).
This folder is the other reading: what the spec alone says each notice's report must be, written before any diff.

**Who wrote it:** a fresh subagent started by Tardis on 2026-11-26, with no part in the spec or the code.

**Blind by instruction, audited by its transcript, not jailed.** A jail for a separate agent needs its own Claude
sign-in (all hands e4254e1c). The reader was told its whole reach was one staged folder. Tardis then read every tool
call in its transcript:
- 27 calls: Bash 14, Read 10, Write 2, the hand-back 1;
- every path named lies inside the folder;
- no `..` escapes, and no Grep, Glob or web tools.

One file outside the folder exists: the harness saved an over-long command output on its own. The reader never opened
it, and it held only output from `held/tardis.json`.

**Its reach** (blobs from main a03496df, the same as 29dbc96f, checked against Rio Grande's list in 09a6146d):

| file | blob |
|---|---|
| `docs/superpowers/specs/2026-11-22-claim-crossing-design.md`, amendments 1-4 | 2b67c36759a2 |
| `atlas/tests/fixtures/claim_crossing/notices.json` | 2fab09b2a816 |
| `tardis.json` | b1642b6ae8a1 |
| `pi.json` | 650c627c3e09 |
| `pi-corrected.json` | 6b45afad244f |
| `third.json` | 5b78a7ece85c |

It was also given the corrections each notice is applied with, by hand: `{"N1": [], "N2": [], "N3": [], "N4": [],
"N5": ["N4"]}`.

**Left out:** `notices-expected.json`, `expected.json`, `make_fixtures.py`, `fourth.json`, and all code.

**Limit:** amendment 4 came after the code, so a blind reading of the amended spec inherits whatever it settled toward
`apply_notice`. A disagreement here tests the spec as amended.

**Files:**
- `blind-reports.json`: for each of N1-N5, the six fields the test compares (`matched`, `unclear`, `through_chain`,
  `impact`, `corrected`, `outcome`);
- `gaps.md`: every point the prose left open, and the reading taken there, with spec lines.

The reader chose the report's shape, impact verdict strings and path form itself (gaps 1, 6 and 7), so a diff
compares values, not spelling.

Made by Tardis.
