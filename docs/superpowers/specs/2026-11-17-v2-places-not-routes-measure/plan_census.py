"""Serenity's count for the next pilot (all hands 207be54d, rule fixed there before this was written; source
directory from 03b19335). Over the 188 commits of `v2/probes/documents/census-2026-11-18.txt` at v2 0cafe565:

(a) how many add at least one counted name, by "the rule as the maker reads it" (section 2 of
    docs/superpowers/specs/2026-11-18-v2-a-document-offered.md at 0cafe565);
(b) of those, at how many no Markdown file tracked at the first parent, in any folder and with no five-file limit,
    holds any counted name as a whole word.

Written from the rule's words alone, without reading the maker's code or Serenity's numbers. Tardis's reading, where
the words leave a choice:
- The commit's change is `git diff --no-renames <first parent> <commit> -- peer/superyak_peer`; an added line is a
  line of it that begins "+" (not "+++"). Every file type under the directory is read, not only Python.
- `def`, `async def` and `class` may be indented. A capitals name assigns at the line's very start: no indent, then
  the name, then an optional annotation, then "=" that is not "==". Only the first name of the line is taken.
- A whole word is a maximal run of ASCII letters, digits and underscores. "Anywhere in the parent's files under the
  source directory" is every tracked file there, read as bytes.
- A Markdown file is a tracked path ending in .md or .markdown, any case.
- "Counted" in (a) is the rule's "It counts" bullet alone (eight characters, an inner underscore, no leading double
  underscore, not a whole word in the parent's source). The five-file limit belongs to "a file holds it", so it is
  not applied in (a), and (b) drops it as asked.
Usage: plan_census.py <repo> <census file>"""
import re
import subprocess
import sys
from collections import Counter

repo, census = sys.argv[1], sys.argv[2]
SRC = "peer/superyak_peer"
DEF = re.compile(r"^\+\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.A)
CAPS = re.compile(r"^\+([A-Z][A-Z0-9_]{3,})\s*(?::[^=\n]*)?=(?!=)", re.A)
WORD = re.compile(rb"[A-Za-z0-9_]+")


def git(*args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True).stdout


_words = {}


def words_of(blob):
    if blob not in _words:
        _words[blob] = set(WORD.findall(git("cat-file", "blob", blob)))
    return _words[blob]


def tree(commit, *paths):
    out = []
    for line in git("ls-tree", "-r", commit, "--", *paths).decode().splitlines():
        meta, path = line.split("\t", 1)
        mode, kind, blob = meta.split()
        if kind == "blob":
            out.append((path, blob))
    return out


def counted(name, parent_src_words):
    return (len(name) >= 8 and "_" in name[1:-1] and not name.startswith("__")
            and name.encode() not in parent_src_words)


rows = []
for line in open(census):
    commit, part = line.split()[:2]
    parent = git("rev-parse", f"{commit}^1").decode().strip()
    src_words = set().union(*(words_of(b) for _, b in tree(parent, SRC)))
    diff = git("diff", "--no-color", "--no-ext-diff", "--no-renames", "-U0", parent, commit, "--", SRC)
    names = set()
    for d in diff.decode("utf-8", "replace").splitlines():
        if d.startswith("+++"):
            continue
        m = DEF.match(d) or CAPS.match(d)
        if m:
            names.add(m.group(1))
    names = sorted(n for n in names if counted(n, src_words))
    md = [(p, b) for p, b in tree(parent) if p.lower().endswith((".md", ".markdown"))]
    held = sorted({p for p, b in md for n in names if n.encode() in words_of(b)}) if names else []
    rows.append((commit, part, names, held))

a = [r for r in rows if r[2]]
b = [r for r in a if not r[3]]
print(f"commits {len(rows)}; (a) add a counted name: {len(a)}; (b) of those, no Markdown file holds one: {len(b)}")
print("by part, (a):", dict(sorted(Counter(r[1] for r in a).items())),
      "(b):", dict(sorted(Counter(r[1] for r in b).items())))
for commit, part, names, held in rows:
    if names:
        print(commit[:8], part, "names", len(names), "md", len(held), "NONE" if not held else "")
