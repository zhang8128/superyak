"""Export a frozen corpus (``atlas/workbench/research_corpus.build``'s SQLite format) to the two
plain TSV files the Rust ``corpus-index`` crate's ``build`` subcommand reads.

Opens the corpus read-only and writes:
- ``docs.tsv``: one line per passage, ``page_id\\ttitle\\ttext``. A passage's title is never
  allowed to contain a tab, newline or carriage return (``research_corpus._check_record`` refuses
  one that does at build time), but its text can, so any such byte in either field is replaced
  with a single space here, as `corpus-index build`'s own format requires.
- ``links.tsv``: one line per link, ``src_page_id\\tdst_page_id``. ``research_corpus``'s own
  ``links`` table is keyed by title, by construction kept only when both ends are already in the
  corpus (see its module docstring), so every link here should resolve; one that somehow doesn't
  (a title no longer in ``passages``) is dropped and counted rather than raising, matching
  ``corpus-index build``'s own "drop and count" rule for links it can't place.

Nothing here reads a question: this is a format conversion over the corpus's own rows, so a
question-derived corpus is exported the same as any other.

Usage: ``python3 export_corpus_tsv.py --corpus corpus.sqlite3 --docs docs.tsv --links links.tsv``
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys

_BAD = re.compile(r"[\t\r\n]")


def _clean(text: str) -> str:
    return _BAD.sub(" ", text)


def export(corpus_path, docs_path, links_path) -> dict:
    db = sqlite3.connect(f"file:{corpus_path}?mode=ro", uri=True)
    try:
        title_to_page_id: dict[str, int] = {}
        docs_written = 0
        with open(docs_path, "w", encoding="utf-8", newline="\n") as docs_out:
            for page_id, title, text in db.execute(
                    "SELECT page_id, title, text FROM passages ORDER BY page_id"):
                title_to_page_id[title] = page_id
                docs_out.write(f"{page_id}\t{_clean(title)}\t{_clean(text)}\n")
                docs_written += 1

        links_kept = links_dropped = 0
        with open(links_path, "w", encoding="utf-8", newline="\n") as links_out:
            for src_title, dst_title in db.execute("SELECT src, dst FROM links ORDER BY src, dst"):
                src_id = title_to_page_id.get(src_title)
                dst_id = title_to_page_id.get(dst_title)
                if src_id is None or dst_id is None:
                    links_dropped += 1
                    continue
                links_out.write(f"{src_id}\t{dst_id}\n")
                links_kept += 1
    finally:
        db.close()
    return {"docs": docs_written, "links_kept": links_kept, "links_dropped": links_dropped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True, help="a frozen corpus SQLite file")
    parser.add_argument("--docs", required=True, help="docs.tsv to write")
    parser.add_argument("--links", required=True, help="links.tsv to write")
    args = parser.parse_args(argv)
    summary = export(args.corpus, args.docs, args.links)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
