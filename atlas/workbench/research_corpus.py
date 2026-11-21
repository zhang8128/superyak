"""A frozen local corpus as a research source, beside Europe PMC (issues #8 and #10).

``build`` writes a read-only SQLite file once: each passage with its article id, revision id and the sha256 of its
text, an FTS5 index, the links between articles that are both in the corpus, and the manifest (what was read, from
which snapshot, with which hashes). It sees records and a manifest only, never a question, so nothing about an
evaluation can shape the corpus.

``FrozenCorpus`` is a provider with Europe PMC's shape: ``search(query, cursor, limit)`` and ``read(paper)``, so
Atlas's runner can use it unchanged, plus ``links(title)`` for navigation. ``read`` returns each passage byte for byte
and refuses one whose bytes no longer match the hash recorded at build time.

**Identity.** The corpus is named by its digest, not by the file's bytes (``built_at`` makes identical builds differ):
a sha256 over the format and the manifest, then every passage's page id, revision id, title, text hash and sorted
links, in page-id order, each row an escaped JSON line. A run records
the digest it expects and opens the corpus with ``FrozenCorpus(path, digest=...)``, which rehashes every text,
recomputes the digest from the rows and refuses a mismatch, so a file edited with its hashes rewritten is caught by a
value held outside it.

**Links** are kept only when both ends are in the corpus; the build returns how many it dropped. Redirects must be
resolved to their target titles before the build, or links through them are dropped. **A question-derived corpus**
(``question_derived: true``, built from an evaluation's own material) opens only with ``allow_question_derived=True``,
so an evaluation can't score itself on one by accident.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable

FORMAT = 3  # 2: the digest covers ids and links; 3: and the manifest, as one JSON line per row
_SEPARATORS = ("\t", "\n", "\x1f")
TEXT_LIMIT = 18000  # Europe PMC's passage cap; a longer record is refused at build time
_WORD = re.compile(r"\w+", re.UNICODE)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest(db: sqlite3.Connection, manifest: dict, *, rehash: bool) -> str:
    """The corpus's identity: the format and manifest, then one row per passage, each an escaped ASCII JSON line,
    so no field's text can stand in for a separator. With ``rehash``, each text's hash is recomputed, not read."""
    links: dict[str, list[str]] = {}
    for src, dst in db.execute("SELECT src, dst FROM links ORDER BY src, dst"):
        links.setdefault(src, []).append(dst)
    digest = hashlib.sha256()
    digest.update((json.dumps({"format": FORMAT, "manifest": manifest}, sort_keys=True) + "\n").encode("ascii"))
    for page_id, rev_id, title, text, sha in db.execute(
            "SELECT page_id, rev_id, title, text, sha256 FROM passages ORDER BY page_id"):
        if rehash and _sha(text) != sha:
            raise ValueError(f"passage {page_id}'s text no longer matches its recorded hash")
        line = json.dumps([page_id, rev_id, title, sha, links.get(title, [])])
        digest.update((line + "\n").encode("ascii"))
    return digest.hexdigest()


def _check_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    for key in ("id", "name", "snapshot"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f"manifest.{key} must be a nonblank string")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", manifest["id"]):
        raise ValueError("manifest.id must be lowercase letters, digits, dots and dashes")
    try:
        date.fromisoformat(manifest["snapshot"])
    except ValueError as exc:
        raise ValueError("manifest.snapshot must be an ISO date") from exc
    if not isinstance(manifest.get("question_derived"), bool):
        raise ValueError("manifest.question_derived must be true or false")
    template = manifest.get("url_template")
    if template is not None and (not isinstance(template, str) or "{rev_id}" not in template
                                 or not template.startswith("https://")):
        raise ValueError("manifest.url_template must be an https URL containing {rev_id}")
    return manifest


def _check_record(record: dict) -> tuple[str, int, int, str, list[str]]:
    if not isinstance(record, dict):
        raise ValueError("a record must be an object")
    title, text, links = record.get("title"), record.get("text"), record.get("links", [])
    page_id, rev_id = record.get("page_id"), record.get("rev_id")
    if not isinstance(title, str) or not title.strip() or len(title) > 512 or any(c in title for c in _SEPARATORS):
        raise ValueError("record.title must be a nonblank string of at most 512 characters, with no tab or newline")
    for name, value in (("page_id", page_id), ("rev_id", rev_id)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 10**18:  # read's key is 1-18 digits
            raise ValueError(f"record.{name} must be a positive integer")
    if not isinstance(text, str) or not text.strip() or len(text) > TEXT_LIMIT:
        raise ValueError(f"record.text must be nonblank and at most {TEXT_LIMIT} characters")
    if not isinstance(links, list) or not all(isinstance(link, str) and not any(c in link for c in _SEPARATORS)
                                              for link in links):
        raise ValueError("record.links must be a list of titles, with no tab or newline")
    return title, page_id, rev_id, text, links


def build(records: Iterable[dict], manifest: dict, path) -> dict:
    """Write the corpus once. A file already at ``path`` is never touched."""
    manifest = _check_manifest(manifest)
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    partial = path.with_name(path.name + ".partial")
    partial.unlink(missing_ok=True)
    db = sqlite3.connect(partial)
    try:
        db.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE passages (rowid INTEGER PRIMARY KEY, page_id INTEGER NOT NULL UNIQUE, rev_id INTEGER NOT NULL,
                                   title TEXT NOT NULL UNIQUE, text TEXT NOT NULL, sha256 TEXT NOT NULL);
            CREATE TABLE raw_links (src TEXT NOT NULL, dst TEXT NOT NULL);
            CREATE VIRTUAL TABLE passages_fts USING fts5(title, text, content='passages', content_rowid='rowid');
        """)
        for record in records:
            title, page_id, rev_id, text, links = _check_record(record)
            try:
                db.execute("INSERT INTO passages (page_id, rev_id, title, text, sha256) VALUES (?, ?, ?, ?, ?)",
                           (page_id, rev_id, title, text, _sha(text)))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"duplicate page_id or title: {title!r}") from exc
            db.executemany("INSERT INTO raw_links VALUES (?, ?)", [(title, dst) for dst in dict.fromkeys(links)])
        db.executescript("""
            INSERT INTO passages_fts (rowid, title, text) SELECT rowid, title, text FROM passages;
            CREATE TABLE links (src TEXT NOT NULL, dst TEXT NOT NULL, PRIMARY KEY (src, dst)) WITHOUT ROWID;
            INSERT OR IGNORE INTO links SELECT r.src, r.dst FROM raw_links r JOIN passages p ON p.title = r.dst
                WHERE r.src != r.dst;
        """)
        offered = db.execute("SELECT count(*) FROM raw_links WHERE src != dst").fetchone()[0]
        db.execute("DROP TABLE raw_links")
        count = db.execute("SELECT count(*) FROM passages").fetchone()[0]
        if not count:
            raise ValueError("a corpus needs at least one record")
        digest = _digest(db, manifest, rehash=True)
        link_count = db.execute("SELECT count(*) FROM links").fetchone()[0]
        db.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("format", str(FORMAT)), ("manifest", json.dumps(manifest, sort_keys=True)),
            ("digest", digest), ("built_at", datetime.now(timezone.utc).isoformat())])
        db.commit()
        db.execute("VACUUM")
    except BaseException:
        db.close()
        partial.unlink(missing_ok=True)
        raise
    db.close()
    partial.rename(path)
    return {"passages": count, "links": link_count, "links_dropped": offered - link_count, "digest": digest,
            "path": str(path)}


class FrozenCorpus:
    """Search, read and follow links in a corpus ``build`` wrote, opened read-only."""

    def __init__(self, path, digest: str | None = None, *, allow_question_derived: bool = False):
        self.path = Path(path)
        self._db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        meta = dict(self._db.execute("SELECT key, value FROM meta"))
        if meta.get("format") != str(FORMAT):
            raise ValueError(f"unsupported corpus format {meta.get('format')!r}")
        self.manifest = _check_manifest(json.loads(meta["manifest"]))
        if self.manifest["question_derived"] and not allow_question_derived:
            raise ValueError("this corpus was built from an evaluation's own material; pass allow_question_derived")
        self.digest = meta["digest"]
        self.verified = False
        if digest is not None:
            actual = _digest(self._db, self.manifest, rehash=True)
            if actual != digest or self.digest != digest:
                raise ValueError("the corpus's rows don't match the digest the run expects")
            self.verified = True
        self.year = date.fromisoformat(self.manifest["snapshot"]).year

    def _paper(self, page_id: int, rev_id: int, title: str, text: str, query: str) -> dict:
        key = f"corpus:{self.manifest['id']}:{page_id}"
        template = self.manifest.get("url_template")
        url = template.format(rev_id=rev_id) if template else f"corpus:{self.manifest['id']}/{page_id}"
        citation = f"{title}. {self.manifest['name']}, revision {rev_id} ({self.manifest['snapshot']})."
        source = {"id": "s-corpus-" + hashlib.sha256(key.encode()).hexdigest()[:20],
                  "title": title, "url": url, "year": self.year, "citation": citation}
        return {"key": key, "doi": "", "pmcid": "", "id": str(page_id), "provider_id": str(page_id),
                "provider_source": "corpus", "title": title, "year": self.year, "citation": citation,
                "source": source, "abstract": text, "publication_types": [],
                "search_url": f"corpus:{self.manifest['id']}?q={query}", "is_open_access": True,
                "page_id": page_id, "rev_id": rev_id}

    @staticmethod
    def _match(query: str) -> tuple[list[str], str]:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError("query must be nonblank and at most 2000 characters")
        words = list(dict.fromkeys(_WORD.findall(query.lower())))[:64]
        return words, " OR ".join('"' + word.replace('"', '""') + '"' for word in words)

    def search(self, query: str, cursor: str = "*", limit: int = 5) -> dict:
        words, match = self._match(query)
        if not isinstance(cursor, str) or not (cursor == "*" or re.fullmatch(r"\d{1,9}", cursor)):
            raise ValueError("cursor must be '*' or an offset")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
            raise ValueError("limit must be between 1 and 25")
        offset = 0 if cursor == "*" else int(cursor)
        if not words:
            return {"papers": [], "next_cursor": None, "skipped": []}
        rows = self._db.execute(
            "SELECT p.page_id, p.rev_id, p.title, p.text FROM passages_fts f JOIN passages p ON p.rowid = f.rowid "
            "WHERE passages_fts MATCH ? ORDER BY bm25(passages_fts), p.page_id LIMIT ? OFFSET ?",
            (match, limit + 1, offset)).fetchall()
        papers = [self._paper(*row, query="+".join(words)) for row in rows[:limit]]  # never the raw query text
        next_cursor = str(offset + limit) if len(rows) > limit else None
        return {"papers": papers, "next_cursor": next_cursor, "skipped": []}

    def rank(self, query: str, titles: list[str], limit: int = 25) -> list[dict]:
        """The papers among ``titles`` that match ``query``, best BM25 first, never one outside the list: for
        choosing which of an article's links to follow."""
        words, match = self._match(query)
        if not isinstance(titles, list) or len(titles) > 1000 or not all(isinstance(t, str) for t in titles):
            raise ValueError("titles must be a list of at most 1000 strings")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if not words or not titles:
            return []
        rows = self._db.execute(
            "SELECT p.page_id, p.rev_id, p.title, p.text FROM passages_fts f JOIN passages p ON p.rowid = f.rowid "
            f"WHERE passages_fts MATCH ? AND p.title IN ({','.join('?' * len(titles))}) "
            "ORDER BY bm25(passages_fts), p.page_id LIMIT ?", (match, *titles, limit)).fetchall()
        return [self._paper(*row, query="+".join(words)) for row in rows]

    def read(self, paper: dict) -> dict:
        prefix = f"corpus:{self.manifest['id']}:"
        key = paper.get("key") if isinstance(paper, dict) else None
        if not isinstance(key, str) or not key.startswith(prefix) or not re.fullmatch(r"[1-9]\d{0,17}", key[len(prefix):]):
            raise ValueError("paper is not from this corpus")
        row = self._db.execute("SELECT page_id, rev_id, title, text, sha256 FROM passages WHERE page_id = ?",
                               (int(key[len(prefix):]),)).fetchone()
        if row is None:
            raise ValueError("paper is not in this corpus")
        page_id, rev_id, title, text, sha = row
        if _sha(text) != sha:
            raise ValueError("passage bytes no longer match the hash recorded at build time")
        passages = [{"id": "p0001", "locator": f"{title} (page {page_id}, revision {rev_id}), lead section",
                     "text": text}]
        paper_view = self._paper(page_id, rev_id, title, text, query="")
        serialized = json.dumps(passages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {"source": dict(paper_view["source"]), "passages": passages, "coverage": "full_text_excerpt",
                "coverage_note": (f"The article's lead section from the frozen corpus {self.manifest['id']} "
                                  f"(snapshot {self.manifest['snapshot']}, digest {self.digest[:12]})."),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "content_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                "document_url": paper_view["source"]["url"], "publication_types": [],
                "corpus": {"id": self.manifest["id"], "digest": self.digest, "page_id": page_id,
                           "rev_id": rev_id, "text_sha256": sha}}

    def links(self, title: str) -> list[str]:
        if not isinstance(title, str):
            raise ValueError("title must be a string")
        return [row[0] for row in self._db.execute("SELECT dst FROM links WHERE src = ? ORDER BY dst", (title,))]
