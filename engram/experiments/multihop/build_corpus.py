"""Issue #8's corpus v0: build a frozen corpus from a Wikipedia multistream dump, in one pass over the dump.

Pass 1 reads the dump's page streams, the first ``--streams`` or all of them. It keeps redirects in a SQLite work
table, and writes every article record (lead section, ids, raw links) to a JSONL file. A full dump's records never
sit in memory. Pass 2 reads the JSONL back, resolves each link through the redirects one step, and streams the
records into ``workbench.research_corpus.build``.

The manifest records the dump's name, the snapshot date, the byte range of the dump read with its sha256, and the
index file's sha256. Nothing reads a question.

Usage, from the repository root, with both packages importable:
``PYTHONPATH=engram:atlas python -m experiments.multihop.build_corpus --dump D --index I --snapshot 2026-11-07
--out corpus.sqlite3 --work DIR [--streams N]``
"""
from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

try:
    from experiments.multihop.wiki_dump import TEXT_LIMIT, canonical, clean, lead, parse_pages, read_streams
except ImportError:  # pragma: no cover
    from wiki_dump import TEXT_LIMIT, canonical, clean, lead, parse_pages, read_streams


def stream_offsets(index, streams: int | None) -> list[int]:
    offsets: list[int] = []
    with bz2.open(index, "rt", encoding="utf-8") as lines:
        for line in lines:
            offset = int(line.split(":", 1)[0])
            if not offsets or offset != offsets[-1]:
                if streams is not None and len(offsets) == streams:
                    offsets.append(offset)          # the next stream's start ends the range read
                    break
                offsets.append(offset)
    return offsets


def sha256_range(path, start: int, end: int | None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        handle.seek(start)
        remaining = None if end is None else end - start
        while remaining is None or remaining > 0:
            chunk = handle.read(1 << 22 if remaining is None else min(1 << 22, remaining))
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


def first_pass(dump, index, streams: int | None, work: Path) -> dict:
    work.mkdir(parents=True, exist_ok=False)
    redirects = sqlite3.connect(work / "redirects.sqlite3")
    redirects.execute("CREATE TABLE r (title TEXT PRIMARY KEY, target TEXT NOT NULL) WITHOUT ROWID")
    counts = {"pages": 0, "articles": 0, "redirects": 0, "skipped_empty_or_long": 0, "other_namespaces": 0}
    count_streams = streams if streams is not None else 10**12
    with open(work / "records.jsonl", "w", encoding="utf-8") as out:
        for page in parse_pages(read_streams(dump, index, count_streams)):
            counts["pages"] += 1
            if page["ns"] != 0:
                counts["other_namespaces"] += 1
            elif page["redirect"]:
                redirects.execute("INSERT OR REPLACE INTO r VALUES (?, ?)",
                                  (canonical(page["title"]), canonical(page["redirect"])))
                counts["redirects"] += 1
            else:
                text, links = clean(lead(page["text"]))
                if not text or len(text) > TEXT_LIMIT:
                    counts["skipped_empty_or_long"] += 1
                    continue
                out.write(json.dumps({"title": canonical(page["title"]), "page_id": page["page_id"],
                                      "rev_id": page["rev_id"], "text": text, "links": links}) + "\n")
                counts["articles"] += 1
    redirects.commit()
    redirects.close()
    return counts


def resolved_records(work: Path):
    redirects = sqlite3.connect(f"file:{work / 'redirects.sqlite3'}?mode=ro", uri=True)
    try:
        with open(work / "records.jsonl", encoding="utf-8") as lines:
            for line in lines:
                record = json.loads(line)
                resolved = []
                for name in record["links"]:
                    row = redirects.execute("SELECT target FROM r WHERE title = ?", (name,)).fetchone()
                    resolved.append(row[0] if row else name)
                record["links"] = list(dict.fromkeys(resolved))   # build drops self-links
                yield record
    finally:
        redirects.close()


def main(argv: list[str] | None = None) -> int:
    from workbench.research_corpus import FrozenCorpus, build
    parser = argparse.ArgumentParser(description="Issue #8: a frozen corpus from a Wikipedia multistream dump")
    parser.add_argument("--dump", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--snapshot", required=True, help="the dump's date, YYYY-MM-DD")
    parser.add_argument("--out", required=True)
    parser.add_argument("--work", required=True, help="a new directory for the work files")
    parser.add_argument("--streams", type=int, help="only the first N page streams (a slice)")
    parser.add_argument("--id", help="the corpus id (default enwiki-<snapshot>[-sN])")
    args = parser.parse_args(argv)
    started = time.time()
    offsets = stream_offsets(args.index, args.streams)
    end = offsets[args.streams] if args.streams is not None and len(offsets) > args.streams else None
    counts = first_pass(args.dump, args.index, args.streams, Path(args.work))
    read_range = [offsets[0], end if end is not None else os.path.getsize(args.dump)]
    corpus_id = args.id or ("enwiki-" + args.snapshot.replace("-", "") + (f"-s{args.streams}" if args.streams else ""))
    manifest = {
        "id": corpus_id, "name": "English Wikipedia", "snapshot": args.snapshot,
        "url_template": "https://en.wikipedia.org/w/index.php?oldid={rev_id}", "question_derived": False,
        "inputs": [{"file": os.path.basename(args.dump), "bytes": read_range,
                    "sha256": sha256_range(args.dump, *read_range)},
                   {"file": os.path.basename(args.index), "sha256": sha256_range(args.index, 0, None)}],
        "streams": args.streams, "extraction": "engram/experiments/multihop/wiki_dump.py, lead sections",
        "counts": counts,
    }
    summary = build(resolved_records(Path(args.work)), manifest, args.out)
    FrozenCorpus(args.out, digest=summary["digest"])   # a run-time self-check: the digest reproduces from the rows
    summary |= {"counts": counts, "seconds": round(time.time() - started, 1), "manifest_inputs": manifest["inputs"]}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
